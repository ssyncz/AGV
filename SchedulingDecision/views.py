from datetime import datetime, time, timedelta

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from Operations.services import actor_from_request, trace_id_from_request

from .models import (
    AGV,
    DispatchRecord,
    MapEdge,
    MapNode,
    MapObstacle,
    ProductionPlan,
    ScheduleRun,
    TransportTask,
)
from .production import ProductionPlanningError, generate_production_plan
from .serializers import (
    AGVSerializer,
    DispatchRecordSerializer,
    MapEdgeSerializer,
    MapNodeSerializer,
    MapObstacleSerializer,
    ProductionPlanSerializer,
    ScheduleRunSerializer,
    TransportTaskSerializer,
)
from .services import (
    SchedulingError,
    cancel_task,
    complete_task,
    dispatch_batch,
    dispatch_single_sequence,
    plan_shortest_path,
    start_task,
)


class MapNodeViewSet(viewsets.ModelViewSet):
    queryset = MapNode.objects.all()
    serializer_class = MapNodeSerializer
    filterset_fields = ["node_type", "is_active"]


class MapEdgeViewSet(viewsets.ModelViewSet):
    queryset = MapEdge.objects.select_related("start_node", "end_node").all()
    serializer_class = MapEdgeSerializer
    filterset_fields = ["is_active", "bidirectional"]


class MapObstacleViewSet(viewsets.ModelViewSet):
    queryset = MapObstacle.objects.all()
    serializer_class = MapObstacleSerializer
    filterset_fields = ["is_active"]

class AGVViewSet(viewsets.ModelViewSet):
    serializer_class = AGVSerializer
    filterset_fields = ["status", "model_name"]

    def get_queryset(self):
        active_statuses = [TransportTask.Status.ASSIGNED, TransportTask.Status.IN_PROGRESS]
        return (
            AGV.objects.select_related("current_node")
            .annotate(
                active_task_count=Count(
                    "tasks", filter=Q(tasks__status__in=active_statuses)
                )
            )
            .order_by("code")
        )

    @action(detail=False, methods=["get"])
    def summary(self, request):
        status_counts = {
            item["status"]: item["count"]
            for item in AGV.objects.values("status").annotate(count=Count("id"))
        }
        total = AGV.objects.count()
        average = sum(AGV.objects.values_list("battery_percent", flat=True)) / max(total, 1)
        return Response({
            "total": total,
            "status_counts": status_counts,
            "average_battery": round(average, 2),
        })


class TransportTaskViewSet(viewsets.ModelViewSet):
    serializer_class = TransportTaskSerializer
    filterset_fields = ["status", "priority", "assigned_agv", "schedule_run"]
    search_fields = ["task_no", "cargo_name"]

    def get_queryset(self):
        return TransportTask.objects.select_related(
            "pickup_node", "dropoff_node", "assigned_agv",
            "assigned_agv__current_node", "schedule_run", "order",
            "work_order", "operation_step", "production_plan",
        ).all()

    def _run_action(self, request, service):
        try:
            task = service(self.get_object().id)
        except SchedulingError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(TransportTaskSerializer(task, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        return self._run_action(request, start_task)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return self._run_action(request, complete_task)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._run_action(request, cancel_task)


class DispatchRecordViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DispatchRecordSerializer
    filterset_fields = ["algorithm", "success", "agv"]

    def get_queryset(self):
        return DispatchRecord.objects.select_related("task", "agv").all()


class ScheduleRunViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ScheduleRunSerializer
    filterset_fields = ["algorithm"]
    ordering_fields = ["created_at", "makespan_seconds", "improvement_percent"]

    def get_queryset(self):
        return ScheduleRun.objects.all()


class ProductionPlanViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProductionPlan.objects.select_related("forecast_run", "work_order").annotate(
        planned_task_count=Count(
            "tasks",
            filter=Q(
                tasks__status__in=[
                    TransportTask.Status.PENDING,
                    TransportTask.Status.ASSIGNED,
                    TransportTask.Status.IN_PROGRESS,
                ]
            ),
        ),
        completed_task_count=Count(
            "tasks",
            filter=Q(tasks__status=TransportTask.Status.COMPLETED),
        ),
        pending_task_count=Count(
            "tasks",
            filter=Q(tasks__status=TransportTask.Status.PENDING),
        ),
    ).order_by("-created_at")
    serializer_class = ProductionPlanSerializer
    filterset_fields = ["status", "forecast_run"]
    ordering_fields = ["created_at", "planning_start", "task_count"]

    @action(detail=False, methods=["post"])
    def generate(self, request):
        try:
            plan = generate_production_plan(
                request.data,
                actor=actor_from_request(request),
                trace_id=trace_id_from_request(request),
            )
        except ProductionPlanningError as exc:
            return Response({"detail": str(exc)}, status=400)
        plan = self.get_queryset().get(pk=plan.pk)
        return Response(
            {
                "plan": ProductionPlanSerializer(plan).data,
                "message": (
                    f"已根据预测生成 {plan.task_count} 个运输任务，"
                    f"计划期 {plan.planning_start} 至 {plan.planning_end}。"
                ),
            },
            status=201,
        )

    @action(detail=True, methods=["post"])
    def schedule(self, request, pk=None):
        plan = self.get_object()
        pending_tasks = list(
            plan.tasks.filter(status=TransportTask.Status.PENDING)
            .order_by("due_at", "priority", "created_at", "id")
            .values_list("id", flat=True)
        )
        pending_count = len(pending_tasks)
        if not pending_count:
            return Response({"detail": "该生产计划没有待调度任务。"}, status=400)
        weights = request.data.get("weights")
        if not isinstance(weights, dict):
            weights = None
        strict_deadlines = bool(request.data.get("strict_deadlines", True))
        try:
            requested_batch_size = int(request.data.get("batch_size", 10))
        except (TypeError, ValueError):
            return Response({"detail": "batch_size 必须为整数。"}, status=400)
        if requested_batch_size < 1:
            return Response({"detail": "batch_size 必须大于 0。"}, status=400)

        result = None
        last_error = None
        if strict_deadlines:
            attempted_sizes = [pending_count]
        else:
            attempted_sizes = list(
                range(min(pending_count, requested_batch_size), 0, -1)
            )
        for batch_size in attempted_sizes:
            try:
                result = dispatch_batch(
                    task_ids=pending_tasks[:batch_size],
                    limit=batch_size,
                    weights=weights,
                    production_plan_id=plan.id,
                    strict_deadlines=strict_deadlines,
                )
                break
            except SchedulingError as exc:
                last_error = exc
        if result is None:
            return Response(
                {"detail": str(last_error or "当前约束下没有可分配方案。")},
                status=400,
            )

        plan = self.get_queryset().get(pk=plan.pk)
        remaining_task_count = plan.tasks.filter(
            status=TransportTask.Status.PENDING
        ).count()
        message = result["message"]
        if remaining_task_count:
            message = (
                f"{message}；本次按当前空闲车辆和电量排程 "
                f"{len(result['tasks'])} 个任务，仍有 {remaining_task_count} 个任务待调度。"
                "请完成当前批次、释放车辆或充电后继续排程。"
            )
        return Response({
            "message": message,
            "algorithm": result["algorithm"],
            "plan": ProductionPlanSerializer(plan).data,
            "run": ScheduleRunSerializer(result["run"]).data,
            "tasks": TransportTaskSerializer(
                result["tasks"], many=True, context={"request": request}
            ).data,
            "evaluation": result["evaluation"],
            "baseline": result["baseline"],
            "scheduled_task_count": len(result["tasks"]),
            "remaining_task_count": remaining_task_count,
        })

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        plan = self.get_object()
        active = plan.tasks.filter(
            status__in=[
                TransportTask.Status.ASSIGNED,
                TransportTask.Status.IN_PROGRESS,
            ]
        )
        if active.exists():
            return Response(
                {"detail": "计划已有已分配或执行中的任务，请先处理这些任务。"}, status=400
            )
        plan.tasks.filter(status=TransportTask.Status.PENDING).update(
            status=TransportTask.Status.CANCELLED
        )
        plan.status = ProductionPlan.Status.CANCELLED
        plan.save(update_fields=["status", "updated_at"])
        return Response(ProductionPlanSerializer(plan).data)

class DashboardOverviewView(APIView):
    def get(self, request):
        from Orders.models import Order
        now = timezone.now()
        agv_total = AGV.objects.count()
        status_counts = {
            item["status"]: item["count"]
            for item in AGV.objects.values("status").annotate(count=Count("id"))
        }
        task_counts = {
            item["status"]: item["count"]
            for item in TransportTask.objects.values("status").annotate(count=Count("id"))
        }
        active_statuses = [TransportTask.Status.ASSIGNED, TransportTask.Status.IN_PROGRESS]
        occupied = status_counts.get(AGV.Status.BUSY, 0)
        average_battery = sum(
            AGV.objects.values_list("battery_percent", flat=True)
        ) / max(agv_total, 1)
        order_status_counts = {
            item["status"]: item["count"]
            for item in Order.objects.values("status").annotate(count=Count("id"))
        }
        today = timezone.localdate()
        today_start = timezone.make_aware(datetime.combine(today, time.min))
        tomorrow_start = today_start + timedelta(days=1)
        open_statuses = [
            TransportTask.Status.PENDING,
            TransportTask.Status.ASSIGNED,
            TransportTask.Status.IN_PROGRESS,
        ]
        return Response({
            "agv_total": agv_total,
            "agv_status_counts": status_counts,
            "task_counts": task_counts,
            "pending_tasks": task_counts.get(TransportTask.Status.PENDING, 0),
            "active_tasks": TransportTask.objects.filter(status__in=active_statuses).count(),
            "completed_tasks": task_counts.get(TransportTask.Status.COMPLETED, 0),
            "due_soon_tasks": TransportTask.objects.filter(
                status__in=open_statuses,
                due_at__gte=now,
                due_at__lte=now + timedelta(hours=24),
            ).count(),
            "overdue_tasks": TransportTask.objects.filter(
                status__in=open_statuses,
                due_at__lt=now,
            ).count(),
            "active_production_plans": ProductionPlan.objects.filter(
                status__in=[ProductionPlan.Status.PLANNED, ProductionPlan.Status.SCHEDULED]
            ).count(),
            "fleet_utilization": round(occupied / max(agv_total, 1) * 100, 2),
            "average_battery": round(average_battery, 2),
            "order_total": Order.objects.count(),
            "order_status_counts": order_status_counts,
            "today_order_count": Order.objects.filter(
                created_at__gte=today_start,
                created_at__lt=tomorrow_start,
            ).count(),
            "latest_schedule_runs": ScheduleRunSerializer(
                ScheduleRun.objects.all()[:5], many=True
            ).data,
            "recent_dispatches": DispatchRecordSerializer(
                DispatchRecord.objects.select_related("task", "agv")[:8], many=True
            ).data,
        })


class MapDataView(APIView):
    def get(self, request):
        active_tasks = TransportTask.objects.filter(
            status__in=[TransportTask.Status.ASSIGNED, TransportTask.Status.IN_PROGRESS]
        ).select_related(
            "assigned_agv", "pickup_node", "dropoff_node", "work_order", "production_plan",
            "schedule_run",
        ).order_by("scheduled_start", "dispatch_order", "sequence_number", "id")
        routes = [
            {
                "task_id": task.id,
                "task_no": task.task_no,
                "work_order_id": task.work_order_id,
                "work_order_no": task.work_order.order_no if task.work_order else None,
                "production_plan_id": task.production_plan_id,
                "production_plan_no": task.production_plan.plan_no if task.production_plan else None,
                "agv_id": task.assigned_agv_id,
                "agv_code": task.assigned_agv.code if task.assigned_agv else None,
                "status": task.status,
                "priority": task.priority,
                "sequence_number": task.sequence_number,
                "dispatch_order": task.dispatch_order,
                "schedule_run_id": task.schedule_run_id,
                "schedule_run_algorithm": (
                    task.schedule_run.get_algorithm_display() if task.schedule_run else None
                ),
                "route": task.route,
                "pickup_node": task.pickup_node_id,
                "dropoff_node": task.dropoff_node_id,
                "total_distance": task.total_distance,
                "estimated_duration": task.estimated_duration,
                "scheduled_start": task.scheduled_start,
                "scheduled_end": task.scheduled_end,
            }
            for task in active_tasks
        ]
        return Response({
            "nodes": MapNodeSerializer(MapNode.objects.all(), many=True).data,
            "edges": MapEdgeSerializer(
                MapEdge.objects.select_related("start_node", "end_node"), many=True
            ).data,
            "obstacles": MapObstacleSerializer(
                MapObstacle.objects.filter(is_active=True), many=True
            ).data,
            "agvs": AGVSerializer(AGV.objects.select_related("current_node"), many=True).data,
            "active_routes": routes,
        })

class PathPlanningView(APIView):
    def post(self, request):
        start_node_id = request.data.get("start_node_id")
        end_node_id = request.data.get("end_node_id")
        if not start_node_id or not end_node_id:
            return Response({"detail": "start_node_id 和 end_node_id 为必填项。"}, status=400)
        try:
            result = plan_shortest_path(
                int(start_node_id),
                int(end_node_id),
                int(request.data["agv_id"]) if request.data.get("agv_id") else None,
            )
        except (TypeError, ValueError):
            return Response({"detail": "节点或 AGV 参数格式错误。"}, status=400)
        except SchedulingError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(result)

class SingleScheduleView(APIView):
    def post(self, request):
        raw_ids = request.data.get("task_ids")
        if raw_ids is None and request.data.get("task_id") is not None:
            raw_ids = [request.data.get("task_id")]
        if not isinstance(raw_ids, list) or not raw_ids:
            return Response({"detail": "task_ids 必须是非空数组。"}, status=400)
        try:
            task_ids = [int(task_id) for task_id in raw_ids]
            result = dispatch_single_sequence(
                task_ids,
                request.data.get("agv_id"),
                strict_deadlines=bool(request.data.get("strict_deadlines", False)),
            )
        except (TypeError, ValueError):
            return Response({"detail": "task_ids 必须由整数组成。"}, status=400)
        except SchedulingError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({
            "message": result["message"],
            "algorithm": result["algorithm"],
            "run": ScheduleRunSerializer(result["run"]).data,
            "tasks": TransportTaskSerializer(
                result["tasks"], many=True, context={"request": request}
            ).data,
            "evaluation": result["evaluation"],
            "baseline": result["baseline"],
        })


class BatchScheduleView(APIView):
    def post(self, request):
        task_ids = request.data.get("task_ids")
        if task_ids is not None and not isinstance(task_ids, list):
            return Response({"detail": "task_ids 必须是数组。"}, status=400)
        try:
            result = dispatch_batch(
                task_ids,
                int(request.data.get("limit", 30)),
                request.data.get("weights") if isinstance(request.data.get("weights"), dict) else None,
                (
                    int(request.data.get("production_plan_id"))
                    if request.data.get("production_plan_id")
                    else None
                ),
                bool(request.data.get("strict_deadlines", False)),
            )
        except (TypeError, ValueError):
            return Response({"detail": "limit 必须为整数。"}, status=400)
        except SchedulingError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({
            "message": result["message"],
            "algorithm": result["algorithm"],
            "run": ScheduleRunSerializer(result["run"]).data,
            "tasks": TransportTaskSerializer(
                result["tasks"], many=True, context={"request": request}
            ).data,
            "evaluation": result["evaluation"],
            "baseline": result["baseline"],
        })
