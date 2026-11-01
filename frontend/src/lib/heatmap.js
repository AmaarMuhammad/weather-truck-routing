// Turns the corridor grid (raw wind/rain/snow per cell per hour) into one RGBA
// frame per forecast hour, ready for MapLibre's ImageSource.updateImage.
//
// Raw values are bilinearly interpolated per pixel and only then classified,
// so colours change exactly where the thresholds are crossed and always agree
// with the checkpoint levels. The image is stretched linearly in Web Mercator,
// so pixel rows are spaced in Mercator y, not latitude.

import { classify, LEVELS, UNKNOWN } from "./risk";

const LEVEL_RGBA = LEVELS.map((l, i) => [...hexToRgb(l.color), [70, 150, 170, 185, 200][i]]);
const UNKNOWN_RGBA = [...hexToRgb(UNKNOWN.color), 90];

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

const mercY = (lat) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
const latFromMercY = (y) => (360 / Math.PI) * Math.atan(Math.exp(y)) - 90;

function flatten(rows, hours) {
  const out = new Float32Array(rows.length * hours);
  rows.forEach((row, i) => {
    for (let h = 0; h < hours; h++) out[i * hours + h] = row[h] == null ? NaN : row[h];
  });
  return out;
}

const MI_PER_DEG = 69.05;

/** Route vertices densified so consecutive samples are at most `stepMi` apart. */
function densify(geometries, stepMi) {
  const out = [];
  for (const g of geometries) {
    for (let i = 0; i < g.length; i++) {
      out.push(g[i]);
      if (i === g.length - 1) break;
      const [la0, lo0] = g[i];
      const [la1, lo1] = g[i + 1];
      const d = Math.hypot((la1 - la0) * MI_PER_DEG, (lo1 - lo0) * MI_PER_DEG * Math.cos((la0 * Math.PI) / 180));
      const n = Math.floor(d / stepMi);
      for (let k = 1; k <= n; k++) out.push([la0 + ((la1 - la0) * k) / (n + 1), lo0 + ((lo1 - lo0) * k) / (n + 1)]);
    }
  }
  return out;
}

/** Fade factor per pixel: 1 inside the corridor tube, easing to 0 at `bufferMi`
 * from the nearest route. Route samples are bucketed so each pixel only checks
 * its neighbourhood. */
function corridorFade(W, H, pixelLat, pixelLon, routes, bufferMi) {
  const samples = densify(routes, 3);
  // size longitude buckets for the most poleward point (plus one bucket), where
  // a degree of longitude is shortest, so the ±1-bucket search never misses
  const bLat = bufferMi / MI_PER_DEG;
  const maxAbsLat = samples.reduce((m, p) => Math.max(m, Math.abs(p[0])), 0);
  const bLon = bLat / Math.cos((Math.min(85, maxAbsLat + bLat) * Math.PI) / 180);
  const buckets = new Map();
  for (const [la, lo] of samples) {
    const key = `${Math.floor(la / bLat)},${Math.floor(lo / bLon)}`;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(la, lo);
  }
  const fade = new Float32Array(W * H);
  const edge = bufferMi * 0.3;
  for (let py = 0; py < H; py++) {
    const lat = pixelLat[py];
    const cosLat = Math.cos((lat * Math.PI) / 180);
    const bi = Math.floor(lat / bLat);
    for (let px = 0; px < W; px++) {
      const lon = pixelLon[px];
      const bj = Math.floor(lon / bLon);
      let best = Infinity;
      for (let di = -1; di <= 1; di++) {
        for (let dj = -1; dj <= 1; dj++) {
          const pts = buckets.get(`${bi + di},${bj + dj}`);
          if (!pts) continue;
          for (let k = 0; k < pts.length; k += 2) {
            const dy = (lat - pts[k]) * MI_PER_DEG;
            const dx = (lon - pts[k + 1]) * MI_PER_DEG * cosLat;
            const d2 = dx * dx + dy * dy;
            if (d2 < best) best = d2;
          }
        }
      }
      const d = Math.sqrt(best);
      fade[py * W + px] = Math.min(1, Math.max(0, (bufferMi - d) / edge));
    }
  }
  return fade;
}

export function buildHeatmap(heatmap, rules, loadLb, routes, bufferMi = 25, maxSide = 512) {
  const { lat0, lon0, dlat, dlon, nrows, ncols, cells } = heatmap.grid;
  const hours = heatmap.hours;

  const cellAt = new Int32Array(nrows * ncols).fill(-1);
  cells.forEach(([r, c], i) => (cellAt[r * ncols + c] = i));

  const west = lon0 - dlon / 2;
  const east = lon0 + (ncols - 0.5) * dlon;
  const south = lat0 - dlat / 2;
  const north = lat0 + (nrows - 0.5) * dlat;
  const yN = mercY(north);
  const yS = mercY(south);
  const aspect = ((east - west) * Math.PI) / 180 / (yN - yS);
  const W = Math.max(2, Math.round(aspect >= 1 ? maxSide : maxSide * aspect));
  const H = Math.max(2, Math.round(aspect >= 1 ? maxSide / aspect : maxSide));

  const pixelLat = Float64Array.from({ length: H }, (_, py) => latFromMercY(yN - ((py + 0.5) / H) * (yN - yS)));
  const pixelLon = Float64Array.from({ length: W }, (_, px) => west + ((px + 0.5) / W) * (east - west));
  const fade = corridorFade(W, H, pixelLat, pixelLon, routes, bufferMi);

  // per-pixel bilinear stencil over corridor cells (independent of the hour)
  const corner = new Int32Array(W * H * 4).fill(-1);
  const weight = new Float32Array(W * H * 4);
  for (let py = 0; py < H; py++) {
    const gy = (pixelLat[py] - lat0) / dlat;
    const r0 = Math.floor(gy);
    const fy = gy - r0;
    for (let px = 0; px < W; px++) {
      const p = py * W + px;
      if (fade[p] === 0) continue;
      const gx = (pixelLon[px] - lon0) / dlon;
      const c0 = Math.floor(gx);
      const fx = gx - c0;
      const ws = [(1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy];
      [[r0, c0], [r0, c0 + 1], [r0 + 1, c0], [r0 + 1, c0 + 1]].forEach(([r, c], k) => {
        if (r < 0 || c < 0 || r >= nrows || c >= ncols) return;
        const cell = cellAt[r * ncols + c];
        if (cell < 0) return;
        corner[p * 4 + k] = cell;
        weight[p * 4 + k] = ws[k];
      });
    }
  }

  const wind = flatten(heatmap.wind, hours);
  const rain = flatten(heatmap.rain, hours);
  const snow = flatten(heatmap.snow, hours);
  const sample = (arr, p, h) => {
    let sum = 0;
    let wsum = 0;
    for (let k = 0; k < 4; k++) {
      const cell = corner[p * 4 + k];
      if (cell < 0) continue;
      const v = arr[cell * hours + h];
      if (Number.isNaN(v)) continue;
      sum += v * weight[p * 4 + k];
      wsum += weight[p * 4 + k];
    }
    return wsum > 0 ? sum / wsum : null;
  };

  const frames = [];
  for (let h = 0; h < hours; h++) {
    const img = new ImageData(W, H);
    const px = img.data;
    for (let p = 0; p < W * H; p++) {
      if (fade[p] === 0) continue;
      const level = classify(rules, sample(wind, p, h), sample(rain, p, h), sample(snow, p, h), loadLb);
      const rgba = level == null ? UNKNOWN_RGBA : LEVEL_RGBA[level];
      px[p * 4] = rgba[0];
      px[p * 4 + 1] = rgba[1];
      px[p * 4 + 2] = rgba[2];
      px[p * 4 + 3] = rgba[3] * fade[p];
    }
    frames.push(img);
  }

  return {
    frames,
    coordinates: [[west, north], [east, north], [east, south], [west, south]],
  };
}
