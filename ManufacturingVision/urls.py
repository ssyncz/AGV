from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CrackDetectView,
    VisionOverviewView,
    VisionRecordViewSet,
    VisionSampleImageView,
    VisionSampleListView,
    WorkpieceDetectView,
)

router = DefaultRouter()
router.register("records", VisionRecordViewSet, basename="vision-record")

urlpatterns = [
    path("", include(router.urls)),
    path("crack/", CrackDetectView.as_view()),
    path("detect/", WorkpieceDetectView.as_view()),
    path("samples/", VisionSampleListView.as_view()),
    path("samples/<str:group>/<str:name>/", VisionSampleImageView.as_view()),
    path("overview/", VisionOverviewView.as_view()),
]
