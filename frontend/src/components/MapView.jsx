import { useEffect, useMemo, useRef, useState } from "react";
import Map, { Layer, NavigationControl, Popup, ScaleControl, Source, useMap } from "react-map-gl/maplibre";
// MapLibre looks for its worker next to its own module, which bundling moves
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { levelInfo } from "../lib/risk";
import { fmtDateTime, fmtDuration, positionAt, ROUTE_COLORS } from "../lib/format";

const STYLE = "https://tiles.openfreemap.org/styles/positron";
const US_VIEW = { longitude: -96, latitude: 38.5, zoom: 3.6 };
const INTERACTIVE = ["checkpoints", "rest-stops", "routes-line"];

const fc = (features) => ({ type: "FeatureCollection", features });
const point = (lat, lon, properties) => ({
  type: "Feature", properties, geometry: { type: "Point", coordinates: [lon, lat] },
});

export default function MapView({ plan, heat, frameIndex, frameTime, selected, onSelect }) {
  const mapRef = useRef(null);
  const [popup, setPopup] = useState(null);
  const [cursor, setCursor] = useState("");
  const rec = plan?.recommendation.route_id;

  const routes = useMemo(() => fc((plan?.routes ?? []).map((r) => ({
    type: "Feature",
    properties: {
      id: r.id,
      color: ROUTE_COLORS[r.id],
      order: r.id === selected ? 3 : r.id === rec ? 2 : 1,
      dim: selected && r.id !== selected ? 1 : 0,
    },
    geometry: { type: "LineString", coordinates: r.geometry.map(([la, lo]) => [lo, la]) },
  }))), [plan, selected, rec]);

  const checkpoints = useMemo(() => fc((plan?.routes ?? []).flatMap((r) =>
    r.checkpoints.map((c, i) => point(c.lat, c.lon, {
      route: r.id, idx: i, color: levelInfo(c.level).color,
      dim: selected && r.id !== selected ? 1 : 0,
    })))), [plan, selected]);

  const rests = useMemo(() => fc((plan?.routes ?? []).flatMap((r) =>
    r.rest_stops.map((s, i) => point(s.lat, s.lon, { route: r.id, idx: i, kind: s.kind })))), [plan]);

  const trucks = useMemo(() => {
    if (!plan || frameTime == null) return fc([]);
    const elapsed = (frameTime - Date.parse(plan.inputs.departure)) / 1000;
    return fc(plan.routes.map((r) => {
      const [lat, lon] = positionAt(r.track, elapsed);
      return point(lat, lon, { id: r.id, color: ROUTE_COLORS[r.id] });
    }));
  }, [plan, frameTime]);

  useEffect(() => {
    setPopup(null);
    const map = mapRef.current;
    if (!plan || !map) return;
    let [w, s, e, n] = [180, 90, -180, -90];
    for (const r of plan.routes) for (const [la, lo] of r.geometry) {
      w = Math.min(w, lo); e = Math.max(e, lo); s = Math.min(s, la); n = Math.max(n, la);
    }
    map.fitBounds([[w, s], [e, n]], { padding: { top: 60, bottom: 110, left: 50, right: 50 }, duration: 900 });
  }, [plan]);

  const onClick = (e) => {
    const f = e.features?.[0];
    if (!f) return setPopup(null);
    const { route, idx } = f.properties;
    const r = plan.routes.find((x) => x.id === (route ?? f.properties.id));
    if (f.layer.id === "routes-line") return onSelect(r.id);
    const data = f.layer.id === "checkpoints" ? r.checkpoints[idx] : r.rest_stops[idx];
    setPopup({ kind: f.layer.id, route: r.id, data });
  };

  return (
    <Map
      ref={mapRef}
      workerUrl={workerUrl}
      initialViewState={US_VIEW}
      mapStyle={STYLE}
      interactiveLayerIds={plan ? INTERACTIVE : []}
      onClick={onClick}
      onMouseEnter={() => setCursor("pointer")}
      onMouseLeave={() => setCursor("")}
      cursor={cursor}
      attributionControl={{ compact: true, customAttribution: "Weather: Open-Meteo.com · Routing: TomTom" }}
    >
      <NavigationControl position="top-left" showCompass={false} />
      <ScaleControl position="bottom-left" unit="imperial" />

      {plan && (
        <>
          <Source id="routes" type="geojson" data={routes}>
            <Layer id="routes-casing" type="line"
              layout={{ "line-join": "round", "line-cap": "round", "line-sort-key": ["get", "order"] }}
              paint={{ "line-color": "#ffffff", "line-width": ["case", [">=", ["get", "order"], 2], 9, 7],
                "line-opacity": ["case", ["==", ["get", "dim"], 1], 0.4, 1] }} />
            <Layer id="routes-line" type="line"
              layout={{ "line-join": "round", "line-cap": "round", "line-sort-key": ["get", "order"] }}
              paint={{ "line-color": ["get", "color"], "line-width": ["case", [">=", ["get", "order"], 2], 5, 3.5],
                "line-opacity": ["case", ["==", ["get", "dim"], 1], 0.3, 0.95] }} />
          </Source>
          <Source id="rest-stops" type="geojson" data={rests}>
            <Layer id="rest-stops" type="circle" paint={{
              "circle-radius": ["case", ["==", ["get", "kind"], "rest"], 6, 4.5],
              "circle-color": "#0f172a", "circle-stroke-color": "#fff", "circle-stroke-width": 2 }} />
          </Source>
          <Source id="checkpoints" type="geojson" data={checkpoints}>
            <Layer id="checkpoints" type="circle" paint={{
              "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 3.5, 8, 6, 11, 8],
              "circle-color": ["get", "color"],
              "circle-stroke-color": "#fff",
              "circle-stroke-width": 1.5,
              "circle-opacity": ["case", ["==", ["get", "dim"], 1], 0.35, 1],
              "circle-stroke-opacity": ["case", ["==", ["get", "dim"], 1], 0.35, 1] }} />
          </Source>
          <Source id="trucks" type="geojson" data={trucks}>
            <Layer id="trucks-halo" type="circle" paint={{
              "circle-radius": 11, "circle-color": "#0f172a", "circle-opacity": 0.25, "circle-blur": 0.6 }} />
            <Layer id="trucks" type="circle" paint={{
              "circle-radius": 7.5, "circle-color": ["get", "color"],
              "circle-stroke-color": "#fff", "circle-stroke-width": 3 }} />
          </Source>
          {heat && (
            <Source key={plan.inputs.departure + heat.coordinates.flat().join()} id="heatmap"
              type="image" coordinates={heat.coordinates}>
              <Layer id="heatmap" type="raster" beforeId="routes-casing"
                paint={{ "raster-fade-duration": 0, "raster-opacity": 0.8, "raster-resampling": "linear" }} />
            </Source>
          )}
          <HeatmapFrame heat={heat} frameIndex={frameIndex} />
        </>
      )}

      {popup && (
        <Popup longitude={popup.data.lon} latitude={popup.data.lat} onClose={() => setPopup(null)}
          closeOnClick={false} maxWidth="280px">
          {popup.kind === "checkpoints" ? <CheckpointPopup route={popup.route} c={popup.data} />
            : <RestPopup route={popup.route} s={popup.data} />}
        </Popup>
      )}
    </Map>
  );
}

/** Swaps the heatmap texture to the current frame — no re-layout, no network. */
function HeatmapFrame({ heat, frameIndex }) {
  const { current: map } = useMap();
  useEffect(() => {
    if (!map || !heat) return;
    const apply = () => map.getSource("heatmap").updateImage({ image: heat.frames[frameIndex] });
    if (map.getSource("heatmap")) return void apply();
    // source not added yet; updateImage itself fires sourcedata, so unsubscribe first
    const retry = () => {
      if (!map.getSource("heatmap")) return;
      map.off("sourcedata", retry);
      apply();
    };
    map.on("sourcedata", retry);
    return () => map.off("sourcedata", retry);
  }, [map, heat, frameIndex]);
  return null;
}

function CheckpointPopup({ route, c }) {
  const info = levelInfo(c.level);
  return (
    <div className="popup">
      <div className="popup-head">
        <span className="route-badge sm" style={{ "--route": ROUTE_COLORS[route] }}>{route}</span>
        Mile {c.mile.toFixed(0)}
        <span className="pill" style={{ background: info.color, color: "#fff" }}>{info.label}</span>
      </div>
      <div className="popup-eta">ETA {fmtDateTime(c.eta)}</div>
      {c.wind != null ? (
        <table>
          <tbody>
            <tr className={c.drivers?.includes("wind") ? "drv" : ""}><td>Wind</td><td>{c.wind} mph{c.gust != null && <small> (gust {c.gust})</small>}</td></tr>
            <tr className={c.drivers?.includes("rain") ? "drv" : ""}><td>Rain</td><td>{c.rain.toFixed(2)} in/hr</td></tr>
            <tr className={c.drivers?.includes("snow") ? "drv" : ""}><td>Snow</td><td>{c.snow.toFixed(2)} in/hr</td></tr>
          </tbody>
        </table>
      ) : <p className="muted">No forecast available for this time.</p>}
      {c.load_escalated && <p className="warn">Escalated by load weight (wind + heavy load rule).</p>}
    </div>
  );
}

function RestPopup({ route, s }) {
  return (
    <div className="popup">
      <div className="popup-head">
        <span className="route-badge sm" style={{ "--route": ROUTE_COLORS[route] }}>{route}</span>
        {s.kind === "rest" ? "10-hour rest (HOS)" : "30-minute break (HOS)"}
      </div>
      <div className="popup-eta">Mile {s.mile.toFixed(0)} · starts {fmtDateTime(s.start)}</div>
      <p className="muted">{fmtDuration(s.duration_s)} off duty</p>
    </div>
  );
}
