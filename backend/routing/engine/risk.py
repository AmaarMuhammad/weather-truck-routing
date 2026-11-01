"""Weather risk classification — the brief's threshold table and load rules.

Boundary interpretation (see README "Interpretations"):
  * every band includes its lower edge, so a value sitting on a shared edge
    (0.25 in/hr rain, 35 mph wind) falls into the higher, safer band;
  * the table states No Travel for rain/snow as strictly ``>1.00`` / ``>3.0``,
    so exactly 1.00 in/hr rain and 3.0 in/hr snow stay Severe;
  * raw values are never rounded (34.5 mph is Moderate).

The tables below are also served to the frontend (``rules_payload``) so the
heatmap classifies pixels with exactly the same rules as the checkpoints.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Level(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return self.name.replace("_", " ").title()


# condition -> ascending (level, lower bound, lower bound inclusive?)
THRESHOLDS: dict[str, list[tuple[Level, float, bool]]] = {
    "wind": [  # sustained wind, mph
        (Level.MODERATE, 25.0, True),
        (Level.HIGH, 35.0, True),
        (Level.SEVERE, 45.0, True),
        (Level.NO_TRAVEL, 55.0, True),
    ],
    "rain": [  # in/hr
        (Level.MODERATE, 0.10, True),
        (Level.HIGH, 0.25, True),
        (Level.SEVERE, 0.50, True),
        (Level.NO_TRAVEL, 1.00, False),
    ],
    "snow": [  # in/hr of snowfall
        (Level.MODERATE, 0.5, True),
        (Level.HIGH, 1.0, True),
        (Level.SEVERE, 2.0, True),
        (Level.NO_TRAVEL, 3.0, False),
    ],
}

# Load rules escalate the *wind* level only, and only ever upward. The
# ">=55 mph -> No Travel for any load" rule is already the wind table's top band.
LOAD_RULES: list[tuple[Level, float, Level]] = [
    # (wind band, load strictly greater than lb, resulting level)
    (Level.SEVERE, 30_000, Level.NO_TRAVEL),  # 45–54 mph + >30,000 lb
    (Level.HIGH, 40_000, Level.SEVERE),       # 35–44 mph + >40,000 lb
]


def classify_value(condition: str, value: float) -> Level:
    level = Level.LOW
    for band, bound, inclusive in THRESHOLDS[condition]:
        if value > bound or (inclusive and value == bound):
            level = band
    return level


def apply_load_rules(wind_level: Level, load_lb: float) -> Level:
    for band, load_over, result in LOAD_RULES:
        if wind_level == band and load_lb > load_over:
            return max(wind_level, result)
    return wind_level


@dataclass(frozen=True)
class Assessment:
    level: Level
    wind: Level            # after load rules
    rain: Level
    snow: Level
    load_escalated: bool

    @property
    def drivers(self) -> list[str]:
        """Conditions responsible for the overall level (empty when Low)."""
        if self.level == Level.LOW:
            return []
        return [name for name in ("wind", "rain", "snow")
                if getattr(self, name) == self.level]


def assess(wind_mph: float, rain_in_hr: float, snow_in_hr: float,
           load_lb: float) -> Assessment:
    raw_wind = classify_value("wind", wind_mph)
    wind = apply_load_rules(raw_wind, load_lb)
    rain = classify_value("rain", rain_in_hr)
    snow = classify_value("snow", snow_in_hr)
    return Assessment(
        level=max(wind, rain, snow),
        wind=wind,
        rain=rain,
        snow=snow,
        load_escalated=wind != raw_wind,
    )


def rules_payload() -> dict:
    return {
        "levels": [lvl.label for lvl in Level],
        "thresholds": {
            cond: [{"level": int(lvl), "min": bound, "inclusive": inc}
                   for lvl, bound, inc in bands]
            for cond, bands in THRESHOLDS.items()
        },
        "load_rules": [
            {"wind_level": int(band), "load_over_lb": over, "result": int(result)}
            for band, over, result in LOAD_RULES
        ],
    }
