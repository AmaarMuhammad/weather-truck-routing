// Table-driven mirror of backend/routing/engine/risk.py. The tables themselves
// come from the API (`plan.rules`), so the heatmap and the checkpoints are
// classified by exactly the same thresholds.

export const LEVELS = [
  { key: "low", label: "Low", color: "#22c55e" },
  { key: "moderate", label: "Moderate", color: "#eab308" },
  { key: "high", label: "High", color: "#f97316" },
  { key: "severe", label: "Severe", color: "#dc2626" },
  { key: "no_travel", label: "No Travel", color: "#6b21a8" },
];
export const UNKNOWN = { key: "unknown", label: "Unknown", color: "#94a3b8" };

export const levelInfo = (level) => (level == null ? UNKNOWN : LEVELS[level]);

function bandLevel(bands, value) {
  let level = 0;
  for (const b of bands) {
    if (value > b.min || (b.inclusive && value === b.min)) level = b.level;
  }
  return level;
}

/** Overall level 0–4, or null when any input is missing (Unknown). */
export function classify(rules, wind, rain, snow, loadLb) {
  if (wind == null || rain == null || snow == null) return null;
  let w = bandLevel(rules.thresholds.wind, wind);
  for (const r of rules.load_rules) {
    if (w === r.wind_level && loadLb > r.load_over_lb) {
      w = Math.max(w, r.result);
      break;
    }
  }
  return Math.max(w, bandLevel(rules.thresholds.rain, rain), bandLevel(rules.thresholds.snow, snow));
}
