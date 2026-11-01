import { useState } from "react";
import PlaceInput from "./PlaceInput";

const EXAMPLES = [
  {
    label: "Chicago → Denver",
    origin: { label: "Chicago, Illinois", lat: 41.8756, lon: -87.6244 },
    destination: { label: "Denver, Colorado", lat: 39.7392, lon: -104.9849 },
  },
  {
    label: "Dallas → Atlanta",
    origin: { label: "Dallas, Texas", lat: 32.7763, lon: -96.7969 },
    destination: { label: "Atlanta, Georgia", lat: 33.749, lon: -84.388 },
  },
  {
    label: "Salt Lake City → Seattle",
    origin: { label: "Salt Lake City, Utah", lat: 40.7596, lon: -111.8868 },
    destination: { label: "Seattle, Washington", lat: 47.6038, lon: -122.3301 },
  },
];

// datetime-local wants "YYYY-MM-DDTHH:mm" in local time
function localInputValue(date) {
  const d = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return d.toISOString().slice(0, 16);
}

function nextQuarterHour() {
  const d = new Date();
  d.setMinutes(Math.ceil((d.getMinutes() + 1) / 15) * 15, 0, 0);
  return d;
}

export default function TripForm({ onSubmit, loading, error }) {
  const [origin, setOrigin] = useState(EXAMPLES[0].origin);
  const [destination, setDestination] = useState(EXAMPLES[0].destination);
  const [departure, setDeparture] = useState(localInputValue(nextQuarterHour()));
  const [load, setLoad] = useState("42000");
  const [intervalMi, setIntervalMi] = useState(25);
  const [hos, setHos] = useState(true);

  const now = new Date();
  const submit = (e) => {
    e.preventDefault();
    if (!origin || !destination) return;
    onSubmit({
      origin,
      destination,
      departure: new Date(departure).toISOString(), // browser-local -> UTC
      load_lb: Number(load),
      interval_mi: intervalMi,
      hos,
    });
  };

  return (
    <div className="card">
      <div className="card-head">
        <h3>Plan a trip</h3>
        <span className="sub">3 truck routes, scored by weather</span>
      </div>
      <form className="card-pad" onSubmit={submit}>
        <PlaceInput label="Origin" icon="🚚" value={origin} onChange={setOrigin}
          placeholder="City or address" />
        <PlaceInput label="Destination" icon="🏁" value={destination} onChange={setDestination}
          placeholder="City or address" />

        <div className="field-row">
          <div className="field">
            <label htmlFor="departure">Departure</label>
            <input id="departure" className="plain" type="datetime-local" value={departure}
              min={localInputValue(new Date(now.getTime() - 15 * 60000))}
              max={localInputValue(new Date(now.getTime() + 7 * 86400000))}
              onChange={(e) => setDeparture(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="load">Load weight (lb)</label>
            <input id="load" className="plain" type="number" min="0" max="48000" step="1"
              value={load} onChange={(e) => setLoad(e.target.value)} required />
          </div>
        </div>

        <div className="field">
          <label>Weather checkpoint every</label>
          <div className="segmented" role="radiogroup">
            {[10, 25, 50].map((mi) => (
              <button type="button" key={mi} role="radio" aria-checked={intervalMi === mi}
                className={intervalMi === mi ? "on" : ""} onClick={() => setIntervalMi(mi)}>
                {mi} mi
              </button>
            ))}
          </div>
        </div>

        <label className="check">
          <input type="checkbox" checked={hos} onChange={(e) => setHos(e.target.checked)} />
          Include Hours-of-Service rests in ETAs
        </label>

        <button className="btn-primary" type="submit" disabled={loading || !origin || !destination}>
          {loading ? (<><span className="spinner" />Checking routes &amp; weather…</>) : "Find the safest route"}
        </button>
        {(!origin || !destination) && <div className="hint">Pick each place from the suggestions.</div>}
        {error && <div className="error-box">⚠ {error}</div>}

        <div className="examples">
          {EXAMPLES.map((ex) => (
            <button type="button" key={ex.label} className="chip"
              onClick={() => { setOrigin(ex.origin); setDestination(ex.destination); }}>
              {ex.label}
            </button>
          ))}
        </div>
      </form>
    </div>
  );
}
