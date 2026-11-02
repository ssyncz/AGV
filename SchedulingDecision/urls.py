from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AGVViewSet,
    BatchScheduleView,
    DashboardOverviewView,
    DispatchRecordViewSet,
    MapDataView,
    MapEdgeViewSet,
    MapNodeViewSet,
    MapObstacleViewSet,
    PathPlanningView,
    ProductionPlanViewSet,
    ScheduleRunViewSet,
    SingleScheduleView,
    TransportTaskViewSet,
)

router = DefaultRouter()
router.register("nodes", MapNodeViewSet)
router.register("edges", MapEdgeViewSet)
router.register("obstacles", MapObstacleViewSet)
router.register("agvs", AGVViewSet, basename="agv")
router.register("tasks", TransportTaskViewSet, basename="task")
router.register("dispatches", DispatchRecordViewSet, basename="dispatch")
router.register("schedule-runs", ScheduleRunViewSet, basename="schedule-run")
router.register("production-plans", ProductionPlanViewSet, basename="production-plan")

urlpatterns = [
    path("", include(router.urls)),
    path("overview/", DashboardOverviewView.as_view()),
    path("map/", MapDataView.as_view()),
    path("path-planning/", PathPlanningView.as_view()),
    path("schedules/single/", SingleScheduleView.as_view()),
    path("schedules/batch/", BatchScheduleView.as_view()),
]
