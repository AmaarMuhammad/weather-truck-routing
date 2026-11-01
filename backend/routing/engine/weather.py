"""Reading an hourly forecast at an arbitrary instant.

Open-Meteo semantics: wind_speed_10m is instantaneous at the timestamp;
rain/showers/snowfall are totals over the *preceding* hour and gusts are the
preceding hour's maximum. So for an arrival at 13:20Z wind is interpolated
between 13:00 and 14:00, while rain/snow/gust come from the 14:00 bucket
(13:00–14:00], which is already an in/hr rate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class HourlySeries:
    start_epoch_h: int           # epoch hour of index 0 (UTC)
    wind: list[float | None]     # mph, instantaneous
    gust: list[float | None]     # mph, max of preceding hour
    rain: list[float | None]     # in/hr, rain + showers, preceding hour
    snow: list[float | None]     # in/hr of snowfall, preceding hour

    def __len__(self) -> int:
        return len(self.wind)


@dataclass(frozen=True)
class Sample:
    wind: float
    gust: float | None   # informational only; risk uses sustained wind
    rain: float
    snow: float


def sample_at(series: HourlySeries, epoch_s: float) -> Sample | None:
    """Weather at ``epoch_s``, or None when outside the series or missing."""
    h = epoch_s / 3600.0 - series.start_epoch_h
    if h < 0 or h > len(series) - 1:
        return None
    i0 = min(int(math.floor(h)), len(series) - 2) if len(series) > 1 else 0
    f = h - i0
    bucket = int(math.ceil(h - 1e-9))
    w0 = series.wind[i0]
    w1 = series.wind[i0 + 1] if len(series) > 1 else w0
    if any(v is None for v in (w0, w1, series.rain[bucket], series.snow[bucket])):
        return None
    return Sample(
        wind=w0 + (w1 - w0) * f,
        gust=series.gust[bucket],
        rain=series.rain[bucket],
        snow=series.snow[bucket],
    )


def hour_slice(series: HourlySeries, epoch_h: int, hours: int) -> dict[str, list]:
    """``hours`` consecutive hourly values starting at ``epoch_h`` (None-padded
    where the series doesn't reach) — used for heatmap frames."""
    out = {"wind": [], "rain": [], "snow": []}
    for k in range(hours):
        i = epoch_h + k - series.start_epoch_h
        inside = 0 <= i < len(series)
        for name in out:
            out[name].append(getattr(series, name)[i] if inside else None)
    return out
