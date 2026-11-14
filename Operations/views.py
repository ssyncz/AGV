from __future__ import annotations

from datetime import timedelta

from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from SchedulingDecision.models import AGV, DispatchRecord, ScheduleRun, TransportTask

from .models import (
    Alert,
    AuditLog,
    Equipment,
    ExecutionEvent,
    OperationEvent,
    OperationStep,
    Product,
    Site,
    WorkCalendar,
    WorkOrder,
)
from .serializers import (
    AlertSerializer,
    AuditLogSerializer,
    EquipmentSerializer,
    ExecutionEventSerializer,
    OperationEventSerializer,
    OperationStepSerializer,
    ProductSerializer,
    SiteSerializer,
    WorkCalendarSerializer,
    WorkOrderSerializer,
)
from .services import (
    OperationError,
    actor_from_request,
    create_transport_task,
    create_work_order,
    complete_operation_step,
    ensure_default_product,
    ensure_default_site,
    ingest_execution_event,
    record_audit,
    record_event,
    start_operation_step,
    trace_id_from_request,
    transition_work_order,
)


def _error(message: str, code: int = status.HTTP_400_BAD_REQUEST):
    return Response({"detail": message}, status=code)


class SiteViewSet(viewsets.ModelViewSet):
    queryset = Site.objects.all()
    serializer_class = SiteSerializer


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer


class EquipmentViewSet(viewsets.ModelViewSet):
    queryset = Equipment.objects.select_related("site").all()
    serializer_class = EquipmentSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        value = self.request.query_params.get("status")
        if value:
            queryset = queryset.filter(status=value)
        return queryset


class WorkCalendarViewSet(viewsets.ModelViewSet):
    queryset = WorkCalendar.objects.select_related("site").all()
    serializer_class = WorkCalendarSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        site = self.request.query_params.get("site")
        if site:
            queryset = queryset.filter(site_id=site)
        return queryset


class OperationStepViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = OperationStep.objects.select_related(
        "work_order", "equipment"
    ).all()
    serializer_class = OperationStepSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        for field in ("work_order", "status", "step_type"):
            value = self.request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{field: value})
        return queryset

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        try:
            step = start_operation_step(
                self.get_object().id,
                actor=actor_from_request(request),
                trace_id=trace_id_from_request(request),
            )
        except OperationError as exc:
            return _error(str(exc))
        return Response(OperationStepSerializer(step).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        try:
            step = complete_operation_step(
                self.get_object().id,
                actor=actor_from_request(request),
                trace_id=trace_id_from_request(request),
                reason=str(request.data.get("reason") or ""),
            )
        except OperationError as exc:
            return _error(str(exc))
        return Response(OperationStepSerializer(step).data)


def _work_order_queryset():
    return (
        WorkOrder.objects.select_related("site", "product")
        .prefetch_related("production_plans", "operation_steps__equipment")
        .annotate(
            # 工单运输进度只统计“普通运输”，换刀/回收任务不计入主线进度
            task_count=Count(
                "transport_tasks",
                filter=Q(transport_tasks__biz_type="transport"),
                distinct=True,
            ),
            completed_task_count=Count(
                "transport_tasks",
                filter=Q(
                    transport_tasks__status=TransportTask.Status.COMPLETED,
                    transport_tasks__biz_type="transport",
                ),
                distinct=True,
            ),
            open_alert_count=Count(
                "alerts",
                filter=Q(
                    alerts__status__in=[Alert.Status.OPEN, Alert.Status.ACKNOWLEDGED]
                ),
                distinct=True,
            ),
        )
        .order_by("-created_at")
    )


class WorkOrderViewSet(viewsets.ModelViewSet):
    serializer_class = WorkOrderSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = _work_order_queryset()
        for field in ("status", "quality_status", "site", "product", "priority"):
            value = self.request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{field: value})
        keyword = str(self.request.query_params.get("q") or "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(order_no__icontains=keyword)
                | Q(title__icontains=keyword)
                | Q(product__name__icontains=keyword)
            )
        return queryset

    def create(self, request, *args, **kwargs):
        try:
            work_order = create_work_order(
                request.data,
                actor=actor_from_request(request),
                trace_id=trace_id_from_request(request),
            )
        except (OperationError, TypeError, ValueError) as exc:
            return _error(str(exc))
        work_order = self.get_queryset().get(pk=work_order.pk)
        return Response(
            WorkOrderSerializer(work_order, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    def _transition(self, request, action_name: str):
        reason = str(request.data.get("reason") or "")
        try:
            work_order = transition_work_order(
                self.get_object().id,
                action_name,
                actor=actor_from_request(request),
                trace_id=trace_id_from_request(request),
                reason=reason,
            )
        except OperationError as exc:
            return _error(str(exc))
        work_order = self.get_queryset().get(pk=work_order.pk)
        return Response(WorkOrderSerializer(work_order, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        return self._transition(request, "release")

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        return self._transition(request, "start")

    @action(detail=True, methods=["post"], url_path="quality-check")
    def quality_check(self, request, pk=None):
        return self._transition(request, "quality-check")

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return self._transition(request, "complete")

    @action(detail=True, methods=["post"])
    def block(self, request, pk=None):
        return self._transition(request, "block")

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        return self._transition(request, "resume")

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._transition(request, "cancel")

    @action(detail=True, methods=["post"], url_path="transport-tasks")
    def transport_tasks(self, request, pk=None):
        try:
            task = create_transport_task(
                self.get_object().id,
                request.data,
                actor=actor_from_request(request),
                trace_id=trace_id_from_request(request),
            )
        except OperationError as exc:
            return _error(str(exc))
        from SchedulingDecision.serializers import TransportTaskSerializer

        return Response(
            TransportTaskSerializer(task, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        work_order = self.get_object()
        from EquipmentMonitoring.serializers import EquipmentDiagnosisRecordListSerializer
        from ManufacturingVision.serializers import VisionRecordSerializer
        from SchedulingDecision.serializers import ScheduleRunSerializer, TransportTaskSerializer

        tasks = list(
            work_order.transport_tasks.select_related(
                "pickup_node", "dropoff_node", "assigned_agv", "production_plan",
                "operation_step", "schedule_run",
            )
            .annotate(
                _display_order=Case(
                    When(dispatch_order__gt=0, then="dispatch_order"),
                    default=Value(999999),
                    output_field=IntegerField(),
                )
            )
            .order_by("_display_order", "created_at")
        )
        schedule_runs = ScheduleRun.objects.filter(
            id__in={task.schedule_run_id for task in tasks if task.schedule_run_id}
        ).order_by("created_at")
        schedule_run_payload = []
        for run in schedule_runs:
            run_tasks = [task for task in tasks if task.schedule_run_id == run.id]
            schedule_run_payload.append(
                {
                    **ScheduleRunSerializer(run).data,
                    "tasks": TransportTaskSerializer(
                        run_tasks, many=True, context={"request": request}
                    ).data,
                    "dispatch_order_start": min(
                        (task.dispatch_order for task in run_tasks if task.dispatch_order),
                        default=0,
                    ),
                    "dispatch_order_end": max(
                        (task.dispatch_order for task in run_tasks if task.dispatch_order),
                        default=0,
                    ),
                }
            )
        vision_records = work_order.vision_records.select_related("work_order").order_by(
            "-created_at"
        )
        equipment_records = work_order.equipment_diagnoses.select_related(
            "equipment", "work_order"
        ).order_by("-created_at")
        alerts = work_order.alerts.select_related("equipment", "work_order").order_by(
            "-created_at"
        )
        events = work_order.events.order_by("-created_at")[:100]
        return Response(
            {
                "work_order": WorkOrderSerializer(work_order, context={"request": request}).data,
                "events": OperationEventSerializer(events, many=True).data,
                "operation_steps": OperationStepSerializer(
                    work_order.operation_steps.select_related("equipment").order_by(
                        "sequence_number"
                    ),
                    many=True,
                ).data,
                "transport_tasks": TransportTaskSerializer(
                    tasks, many=True, context={"request": request}
                ).data,
                "schedule_runs": schedule_run_payload,
                "unscheduled_tasks": TransportTaskSerializer(
                    [task for task in tasks if task.schedule_run_id is None],
                    many=True,
                    context={"request": request},
                ).data,
                "vision_records": VisionRecordSerializer(vision_records, many=True).data,
                "equipment_diagnoses": EquipmentDiagnosisRecordListSerializer(
                    equipment_records, many=True
                ).data,
                "alerts": AlertSerializer(alerts, many=True).data,
            }
        )


class AlertViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Alert.objects.select_related("work_order", "equipment").all()
    serializer_class = AlertSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        for field in ("status", "severity", "source_type"):
            value = self.request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{field: value})
        return queryset

    def _update_status(self, request, target: str):
        alert = self.get_object()
        actor = actor_from_request(request)
        now = timezone.now()
        if target == Alert.Status.ACKNOWLEDGED:
            if alert.status != Alert.Status.OPEN:
                return _error("只有待处理告警可以确认。")
            alert.status = Alert.Status.ACKNOWLEDGED
            alert.acknowledged_by = actor
            alert.acknowledged_at = now
            alert.save(
                update_fields=[
                    "status", "acknowledged_by", "acknowledged_at", "updated_at",
                ]
            )
            event_type, summary = "alert.acknowledged", f"告警已确认：{alert.title}"
        else:
            if alert.status == Alert.Status.RESOLVED:
                return _error("告警已经解决。")
            alert.status = Alert.Status.RESOLVED
            alert.resolved_by = actor
            alert.resolved_at = now
            alert.save(
                update_fields=["status", "resolved_by", "resolved_at", "updated_at"]
            )
            event_type, summary = "alert.resolved", f"告警已解决：{alert.title}"
        if alert.work_order_id:
            record_event(
                work_order=alert.work_order,
                event_type=event_type,
                summary=summary,
                actor=actor,
                trace_id=trace_id_from_request(request),
                aggregate_type="alert",
                aggregate_id=alert.id,
            )
        record_audit(
            actor=actor,
            action=event_type,
            object_type="alert",
            object_id=alert.id,
            after={"status": alert.status},
            trace_id=trace_id_from_request(request),
        )
        return Response(AlertSerializer(alert).data)

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        return self._update_status(request, Alert.Status.ACKNOWLEDGED)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        return self._update_status(request, Alert.Status.RESOLVED)


class OperationEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = OperationEvent.objects.select_related("work_order").all()
    serializer_class = OperationEventSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        work_order = self.request.query_params.get("work_order")
        if work_order:
            queryset = queryset.filter(work_order_id=work_order)
        return queryset


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer


class MasterDataView(APIView):
    """主数据聚合接口，同时确保演示环境有默认站点和产品。"""

    def get(self, request):
        ensure_default_site()
        ensure_default_product()
        return Response(
            {
                "sites": SiteSerializer(Site.objects.all(), many=True).data,
                "products": ProductSerializer(Product.objects.all(), many=True).data,
                "equipment": EquipmentSerializer(
                    Equipment.objects.select_related("site"), many=True
                ).data,
                "work_calendars": WorkCalendarSerializer(
                    WorkCalendar.objects.select_related("site"), many=True
                ).data,
            }
        )


class ExecutionEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ExecutionEvent.objects.select_related(
        "work_order", "operation_step"
    ).all()
    serializer_class = ExecutionEventSerializer


class ExecutionEventIngestView(APIView):
    def post(self, request):
        try:
            event, duplicate = ingest_execution_event(
                request.data,
                actor=actor_from_request(request),
                trace_id=trace_id_from_request(request),
            )
        except OperationError as exc:
            return _error(str(exc))
        response_status = (
            status.HTTP_200_OK
            if duplicate or event.status == ExecutionEvent.Status.PROCESSED
            else status.HTTP_400_BAD_REQUEST
        )
        return Response(
            {
                "duplicate": duplicate,
                "event": ExecutionEventSerializer(event).data,
            },
            status=response_status,
        )


class CommandCenterView(APIView):
    """运营驾驶舱聚合接口：KPI、异常、工单与最近事件。"""

    def get(self, request):
        now = timezone.now()
        open_alerts = Alert.objects.filter(
            status__in=[Alert.Status.OPEN, Alert.Status.ACKNOWLEDGED]
        )
        work_orders = _work_order_queryset()
        recent_work_orders = work_orders.order_by("-created_at")[:8]
        recent_alerts = open_alerts.select_related("work_order", "equipment")[:8]
        recent_events = OperationEvent.objects.select_related("work_order")[:12]
        equipment_counts = {
            item["status"]: item["count"]
            for item in Equipment.objects.values("status").annotate(count=Count("id"))
        }
        task_counts = {
            item["status"]: item["count"]
            for item in TransportTask.objects.values("status").annotate(count=Count("id"))
        }
        overdue_tasks = TransportTask.objects.filter(
            status__in=[
                TransportTask.Status.PENDING,
                TransportTask.Status.ASSIGNED,
                TransportTask.Status.IN_PROGRESS,
            ],
            due_at__lt=now,
        ).count()
        return Response(
            {
                "kpis": {
                    "work_order_total": work_orders.count(),
                    "active_work_orders": work_orders.filter(
                        status__in=[
                            WorkOrder.Status.RELEASED,
                            WorkOrder.Status.IN_PROGRESS,
                            WorkOrder.Status.QUALITY_CHECK,
                        ]
                    ).count(),
                    "blocked_work_orders": work_orders.filter(
                        status=WorkOrder.Status.BLOCKED
                    ).count(),
                    "completed_work_orders": work_orders.filter(
                        status=WorkOrder.Status.COMPLETED
                    ).count(),
                    "open_alerts": open_alerts.count(),
                    "critical_alerts": open_alerts.filter(
                        severity=Alert.Severity.CRITICAL
                    ).count(),
                    "quality_failed": work_orders.filter(
                        quality_status=WorkOrder.QualityStatus.FAIL
                    ).count(),
                    "equipment_faults": equipment_counts.get(Equipment.Status.FAULT, 0),
                    "equipment_warnings": equipment_counts.get(Equipment.Status.WARNING, 0),
                    "overdue_tasks": overdue_tasks,
                    "pending_tasks": task_counts.get(TransportTask.Status.PENDING, 0),
                    "active_tasks": task_counts.get(TransportTask.Status.ASSIGNED, 0)
                    + task_counts.get(TransportTask.Status.IN_PROGRESS, 0),
                    "active_operation_steps": OperationStep.objects.filter(
                        status__in=[
                            OperationStep.Status.READY,
                            OperationStep.Status.IN_PROGRESS,
                            OperationStep.Status.QUALITY_CHECK,
                        ]
                    ).count(),
                    "agv_total": AGV.objects.count(),
                    "agv_available": AGV.objects.filter(status=AGV.Status.IDLE).count(),
                },
                "alerts": AlertSerializer(recent_alerts, many=True).data,
                "work_orders": WorkOrderSerializer(
                    recent_work_orders, many=True, context={"request": request}
                ).data,
                "events": OperationEventSerializer(recent_events, many=True).data,
                "equipment_counts": equipment_counts,
                "task_counts": task_counts,
                "recent_dispatches": [
                    {
                        "id": item.id,
                        "task_no": item.task.task_no,
                        "agv_code": item.agv.code if item.agv else None,
                        "algorithm_display": item.get_algorithm_display(),
                        "success": item.success,
                        "created_at": item.created_at,
                    }
                    for item in DispatchRecord.objects.select_related("task", "agv")[:8]
                ],
            }
        )
