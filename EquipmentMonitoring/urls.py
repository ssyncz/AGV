from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views_algo import (AlgoStatusView, AnomalyDetectView, DatasetCompareView, DetectorCompareView,
                         DiagnosePlusView, FeatureExtractView)
from .views import (
    EquipmentDatasetView,
    EquipmentDiagnoseView,
    EquipmentModelView,
    EquipmentOverviewView,
    EquipmentRecordViewSet,
    EquipmentSampleView,
    ToolChangeRecordViewSet,
    ToolViewSet,
)


router = DefaultRouter()
router.register("records", EquipmentRecordViewSet, basename="equipment-record")
router.register("tools", ToolViewSet, basename="equipment-tool")
router.register("tool-changes", ToolChangeRecordViewSet, basename="equipment-tool-change")

urlpatterns = [
    path("", include(router.urls)),
    path("overview/", EquipmentOverviewView.as_view(), name="equipment-overview"),
    path("datasets/", EquipmentDatasetView.as_view(), name="equipment-datasets"),
    path("sample/", EquipmentSampleView.as_view(), name="equipment-sample"),
    path("model/", EquipmentModelView.as_view(), name="equipment-model"),
    path("diagnose/", EquipmentDiagnoseView.as_view(), name="equipment-diagnose"),
    path("algo/status/", AlgoStatusView.as_view(), name="equipment-algo-status"),
    path("algo/detect/", AnomalyDetectView.as_view(), name="equipment-algo-detect"),
    path("algo/features/", FeatureExtractView.as_view(), name="equipment-algo-features"),
    path("algo/compare/", DetectorCompareView.as_view(), name="equipment-algo-compare"),
    path("algo/diagnose/", DiagnosePlusView.as_view(), name="equipment-algo-diagnose"),
    path("algo/dataset-compare/", DatasetCompareView.as_view(), name="equipment-algo-dataset-compare"),
]