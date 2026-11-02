from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AlertViewSet,
    AuditLogViewSet,
    CommandCenterView,
    EquipmentViewSet,
    ExecutionEventIngestView,
    ExecutionEventViewSet,
    MasterDataView,
    OperationEventViewSet,
    OperationStepViewSet,
    ProductViewSet,
    SiteViewSet,
    WorkCalendarViewSet,
    WorkOrderViewSet,
)


router = DefaultRouter()
router.register("sites", SiteViewSet)
router.register("products", ProductViewSet)
router.register("equipment", EquipmentViewSet)
router.register("work-calendars", WorkCalendarViewSet)
router.register("operation-steps", OperationStepViewSet, basename="operation-step")
router.register("work-orders", WorkOrderViewSet, basename="work-order")
router.register("alerts", AlertViewSet, basename="alert")
router.register("events", OperationEventViewSet, basename="operation-event")
router.register("audit-logs", AuditLogViewSet, basename="audit-log")
router.register("execution-events", ExecutionEventViewSet, basename="execution-event")

urlpatterns = [
    path("command-center/", CommandCenterView.as_view(), name="command-center"),
    path("master-data/", MasterDataView.as_view(), name="master-data"),
    path("execution-events/ingest/", ExecutionEventIngestView.as_view(), name="execution-event-ingest"),
    path("", include(router.urls)),
]
