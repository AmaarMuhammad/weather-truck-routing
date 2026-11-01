"""Place autocomplete via Photon (komoot) — keyless, OSM-based, and unlike
Nominatim its usage policy allows search-as-you-type."""
from __future__ import annotations

import hashlib

import requests
from django.conf import settings
from django.core.cache import cache

US_BBOX = "-125,24,-66,50"  # minLon,minLat,maxLon,maxLat
_TIMEOUT = 8


class PlacesUnavailable(Exception):
    pass


def suggest(query: str, limit: int = 6) -> list[dict]:
    query = " ".join(query.split())
    if len(query) < 2:
        return []
    key = f"photon:{hashlib.sha1(query.lower().encode()).hexdigest()}:{limit}"
    hit = cache.get(key)
    if hit is not None:
        return hit
    try:
        resp = requests.get(
            settings.PHOTON_URL,
            params={"q": query, "limit": limit, "lang": "en", "bbox": US_BBOX},
            headers={"User-Agent": settings.HTTP_USER_AGENT},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        features = resp.json().get("features", [])
    except (requests.RequestException, ValueError) as exc:
        raise PlacesUnavailable(f"Place search unavailable: {exc}") from exc

    places, seen = [], set()
    for f in features:
        props = f.get("properties", {})
        lon, lat = f["geometry"]["coordinates"]
        name = props.get("name") or props.get("city") or props.get("street")
        if not name:
            continue
        parts = [name]
        for k in ("city", "state"):
            v = props.get(k)
            if v and v not in parts:
                parts.append(v)
        label = ", ".join(parts)
        if label in seen:
            continue
        seen.add(label)
        places.append({"label": label, "lat": lat, "lon": lon})
    cache.set(key, places, 24 * 3600)
    return places
