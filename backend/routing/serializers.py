import math
from datetime import datetime, timedelta, timezone

from rest_framework import serializers

MAX_LOAD_LB = 48_000          # ~80,000 lb gross minus a typical tractor-trailer
DEPARTURE_GRACE = timedelta(minutes=30)
MAX_DEPARTURE_AHEAD = timedelta(days=7)


class PlaceSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=200)
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)


class PlanInputSerializer(serializers.Serializer):
    origin = PlaceSerializer()
    destination = PlaceSerializer()
    departure = serializers.DateTimeField()
    load_lb = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LB)
    interval_mi = serializers.ChoiceField(choices=[10, 25, 50], default=25)
    hos = serializers.BooleanField(default=True)

    def validate_departure(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise serializers.ValidationError("Departure must include a UTC offset.")
        now = datetime.now(timezone.utc)
        if value < now - DEPARTURE_GRACE:
            raise serializers.ValidationError("Departure is in the past.")
        if value > now + MAX_DEPARTURE_AHEAD:
            raise serializers.ValidationError(
                "Departure must be within 7 days — weather forecasts don't reach further.")
        return value

    def validate(self, attrs):
        o, d = attrs["origin"], attrs["destination"]
        # NaN passes min/max checks (every comparison with NaN is False)
        if not all(math.isfinite(v) for v in (attrs["load_lb"], o["lat"], o["lon"], d["lat"], d["lon"])):
            raise serializers.ValidationError("Load and coordinates must be finite numbers.")
        if abs(o["lat"] - d["lat"]) < 1e-3 and abs(o["lon"] - d["lon"]) < 1e-3:
            raise serializers.ValidationError("Origin and destination are the same place.")
        return attrs
