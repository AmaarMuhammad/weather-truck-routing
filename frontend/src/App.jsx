import { Component, useEffect, useMemo, useState } from "react";
import { planTrip, wakeServer } from "./lib/api";
import { buildHeatmap } from "./lib/heatmap";
import { LEVELS, UNKNOWN } from "./lib/risk";
import TripForm from "./components/TripForm";
import RouteCards, { Recommendation } from "./components/RouteCards";
import MapView from "./components/MapView";
import ForecastSlider from "./components/ForecastSlider";

export default function App() {
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);
  const [hour, setHour] = useState(0);
  const [server, setServer] = useState("waking");

  useEffect(() => {
    wakeServer().then((ok) => setServer(ok ? "ready" : "down"));
  }, []);

  const heat = useMemo(() => {
    if (!plan) return null;
    const t = performance.now();
    const built = buildHeatmap(plan.heatmap, plan.rules, plan.inputs.load_lb,
      plan.routes.map((r) => r.geometry), plan.heatmap.buffer_mi);
    console.debug(`heatmap: ${built.frames.length} frames in ${Math.round(performance.now() - t)} ms`);
    return built;
  }, [plan]);
  const frameTime = plan ? Date.parse(plan.heatmap.start) + hour * 3600e3 : null;

  const handleSubmit = async (input) => {
    setLoading(true);
    setError("");
    try {
      const data = await planTrip(input);
      setPlan(data);
      setSelected(null);
      setHour(0);
      setServer("ready");
    } catch (e) {
      setError(e.message === "Failed to fetch" ? "Can't reach the server — it may still be waking up. Try again in a few seconds." : e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="logo">⛈️</div>
        <div className="titles">
          <h1>Weather-Aware Truck Routing</h1>
          <p>Pick the safest route by weather, load weight and travel time</p>
        </div>
        <div className="spacer" />
        <div className={`tag server-${server}`}>
          {server === "waking" ? "Waking server…" : server === "ready" ? "Server ready" : "Server unreachable"}
        </div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <TripForm onSubmit={handleSubmit} loading={loading} error={error} />
          {plan && (
            <>
              {plan.notices.map((n) => <div key={n} className="notice">ℹ {n}</div>)}
              <Recommendation plan={plan} />
              <RouteCards plan={plan} selected={selected} onSelect={setSelected} />
            </>
          )}
        </aside>

        <main className="map-card card">
          <MapErrorBoundary>
            <MapView plan={plan} heat={heat} frameIndex={hour} frameTime={frameTime}
              selected={selected} onSelect={setSelected} />
          </MapErrorBoundary>
          <Legend />
          {plan && (
            <ForecastSlider hours={plan.heatmap.hours} hour={hour} onChange={setHour}
              startIso={plan.heatmap.start} loadLb={plan.inputs.load_lb} />
          )}
          {loading && (
            <div className="map-overlay">
              <div className="overlay-box"><span className="spinner dark" />Routing truck options and fetching forecasts…</div>
            </div>
          )}
          {!plan && !loading && (
            <div className="map-overlay soft">
              <div className="overlay-box">Enter a trip to compare three truck routes by weather risk.</div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function Legend() {
  return (
    <div className="legend">
      {[...LEVELS, UNKNOWN].map((l) => (
        <span key={l.key}><i style={{ background: l.color }} />{l.label}</span>
      ))}
      <span><i className="ring" />Truck at slider time</span>
      <span><i style={{ background: "#0f172a" }} />HOS rest</span>
      <small className="legend-note">Dots: weather when the truck arrives · Shading: weather at the slider time</small>
    </div>
  );
}

class MapErrorBoundary extends Component {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed) {
      return <div className="map-fallback">The map needs WebGL 2, which this browser or device doesn't provide. Route results are still listed on the left.</div>;
    }
    return this.props.children;
  }
}
