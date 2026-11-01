import { useEffect, useState } from "react";
import { fmtDateTime } from "../lib/format";

const STEP_MS = 300;

export default function ForecastSlider({ hours, hour, onChange, startIso, loadLb }) {
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => onChange((h) => (h + 1) % hours), STEP_MS);
    return () => clearInterval(t);
  }, [playing, hours, onChange]);

  const time = new Date(Date.parse(startIso) + hour * 3600e3).toISOString();
  return (
    <div className="slider-panel">
      <button className="play" onClick={() => setPlaying((p) => !p)}
        aria-label={playing ? "Pause forecast animation" : "Play forecast animation"}>
        {playing ? "❚❚" : "▶"}
      </button>
      <div className="slider-body">
        <div className="slider-labels">
          <span><b>{fmtDateTime(time)}</b> · departure +{hour}h</span>
          <span className="muted">Corridor risk for {Number(loadLb).toLocaleString()} lb</span>
        </div>
        <input type="range" min="0" max={hours - 1} step="1" value={hour}
          onChange={(e) => { setPlaying(false); onChange(Number(e.target.value)); }}
          aria-label="Forecast hour" />
        <div className="slider-ticks"><span>0h</span><span>12h</span><span>24h</span><span>36h</span><span>48h</span></div>
      </div>
    </div>
  );
}
