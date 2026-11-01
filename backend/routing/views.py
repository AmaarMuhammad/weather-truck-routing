import hashlib
import json
from datetime import timezone

from django.core.cache import cache
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .providers.photon import PlacesUnavailable, suggest
from .providers.tomtom import RoutingError
from .serializers import PlanInputSerializer
from .services import TripRequest, plan_trip

PLAN_CACHE_TTL_S = 600


class PlanView(APIView):
    """POST trip inputs; get 3 routes with checkpoints, risk, ETAs, the
    recommendation and the corridor heatmap."""

    def post(self, request):
        serializer = PlanInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # identical requests (same departure minute) reuse the plan
        cache_key = "plan:" + hashlib.sha256(json.dumps({
            **data,
            "departure": data["departure"].astimezone(timezone.utc).isoformat(timespec="minutes"),
        }, sort_keys=True, default=str).encode()).hexdigest()
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        try:
            plan = plan_trip(TripRequest(**data))
        except RoutingError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        # a plan with Unknown weather (e.g. rate-limited) must not stick; retry fresh
        if not plan["recommendation"]["has_unknown"]:
            cache.set(cache_key, plan, PLAN_CACHE_TTL_S)
        return Response(plan)


class PlacesView(APIView):
    def get(self, request):
        try:
            return Response({"results": suggest(request.query_params.get("q", ""))})
        except PlacesUnavailable as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
