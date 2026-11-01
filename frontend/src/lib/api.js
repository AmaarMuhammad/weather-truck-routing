export const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

async function request(path, options) {
  const res = await fetch(`${API_URL}${path}`, options);
  // a bad body on an error response falls back to {}; on a 2xx (e.g. aborted
  // mid-read) it must reject rather than resolve to garbage
  const data = await res.json().catch((e) => {
    if (res.ok) throw e;
    return {};
  });
  if (!res.ok) {
    const first = Object.values(data)?.[0];
    const msg =
      data.error ||
      (Array.isArray(first) ? first[0] : typeof first === "object" ? Object.values(first)[0]?.[0] : null) ||
      `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return data;
}

export const planTrip = (input) =>
  request("/api/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });

export const searchPlaces = (q, signal) =>
  request(`/api/places?q=${encodeURIComponent(q)}`, { signal }).then((d) => d.results);

// Free-tier hosting sleeps when idle; wake it as soon as the page opens.
export const wakeServer = () => fetch(`${API_URL}/api/health`).then((r) => r.ok).catch(() => false);
