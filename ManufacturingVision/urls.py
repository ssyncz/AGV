from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views_algo import (DefectClassifyView, AlgoStatusView as VisionAlgoStatusView, DatasetBuildView,
                         PatchcoreInferView, DeepCrackSegmentView)
from .views import (
    CrackDetectView,
    DefectDetectView,
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
    path("detect/defect/", DefectDetectView.as_view()),
    path("samples/", VisionSampleListView.as_view()),
    path("samples/<str:group>/<str:name>/", VisionSampleImageView.as_view()),
    path("overview/", VisionOverviewView.as_view()),
    path("algo/status/", VisionAlgoStatusView.as_view(), name="vision-algo-status"),
    path("algo/dataset/", DatasetBuildView.as_view(), name="vision-algo-dataset"),
    path("algo/patchcore/", PatchcoreInferView.as_view(), name="vision-algo-patchcore"),
    path("algo/deepcrack/", DeepCrackSegmentView.as_view(), name="vision-algo-deepcrack"),
    path("algo/defect/", DefectClassifyView.as_view(), name="vision-algo-defect"),
]
