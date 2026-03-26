"""URL routing for the api app."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"items", views.ItemViewSet)

urlpatterns = [
    path("health/", views.health_check, name="health"),
    path("", include(router.urls)),
]
