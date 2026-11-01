from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({"status": "ok", "service": "weather-truck-routing"})


urlpatterns = [
    path("", health),
    path("api/health", health),
    path("api/", include("routing.urls")),
]
