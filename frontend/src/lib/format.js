export const ROUTE_COLORS = { A: "#2563eb", B: "#334155", C: "#0891b2" };

export function fmtDuration(seconds) {
  const m = Math.round(seconds / 60);
  const h = Math.floor(m / 60);
  return h ? `${h}h ${String(m % 60).padStart(2, "0")}m` : `${m}m`;
}

const dtf = new Intl.DateTimeFormat(undefined, {
  weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
});
export const fmtDateTime = (iso) => dtf.format(new Date(iso));

export const fmtMiles = (mi) =>
  `${mi.toLocaleString(undefined, { maximumFractionDigits: mi < 10 ? 1 : 0 })} mi`;

/** Position along a route's (elapsed_s, lat, lon) track at `elapsed` seconds. */
export function positionAt(track, elapsed) {
  if (elapsed <= track[0][0]) return [track[0][1], track[0][2]];
  const last = track[track.length - 1];
  if (elapsed >= last[0]) return [last[1], last[2]];
  let lo = 0;
  let hi = track.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (track[mid][0] <= elapsed) lo = mid;
    else hi = mid;
  }
  const [t0, la0, lo0] = track[lo];
  const [t1, la1, lo1] = track[hi];
  const f = t1 === t0 ? 0 : (elapsed - t0) / (t1 - t0);
  return [la0 + (la1 - la0) * f, lo0 + (lo1 - lo0) * f];
}
