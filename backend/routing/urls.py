from django.urls import path

from .views import PlacesView, PlanView

urlpatterns = [
    path("plan", PlanView.as_view(), name="plan"),
    path("places", PlacesView.as_view(), name="places"),
]
