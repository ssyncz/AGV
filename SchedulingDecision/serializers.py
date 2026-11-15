from time import time

from rest_framework import serializers

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


class MapNodeSerializer(serializers.ModelSerializer):
    node_type_display = serializers.CharField(source="get_node_type_display", read_only=True)

    class Meta:
        model = MapNode
        fields = [
            "id", "code", "name", "node_type", "node_type_display", "x", "y",
            "is_active", "created_at",
        ]
        read_only_fields = ["created_at"]


class MapObstacleSerializer(serializers.ModelSerializer):
    class Meta:
        model = MapObstacle
        fields = ["id", "code", "name", "x", "y", "width", "height", "is_active", "created_at"]
        read_only_fields = ["created_at"]

class MapEdgeSerializer(serializers.ModelSerializer):
    start_node_detail = MapNodeSerializer(source="start_node", read_only=True)
    end_node_detail = MapNodeSerializer(source="end_node", read_only=True)

    class Meta:
        model = MapEdge
        fields = [
            "id", "start_node", "start_node_detail", "end_node", "end_node_detail",
            "distance", "speed_limit", "bidirectional", "is_active", "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        start = attrs.get("start_node", getattr(self.instance, "start_node", None))
        end = attrs.get("end_node", getattr(self.instance, "end_node", None))
        if start and end and start == end:
            raise serializers.ValidationError("道路起点和终点不能相同。")
        return attrs


class AGVSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    current_node_detail = MapNodeSerializer(source="current_node", read_only=True)
    active_task_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = AGV
        fields = [
            "id", "code", "name", "model_name", "status", "status_display",
            "current_node", "current_node_detail", "battery_percent",
            "payload_capacity", "speed", "active_task_count",
            "last_heartbeat", "created_at",
        ]
        read_only_fields = ["last_heartbeat", "created_at"]


class TransportTaskSerializer(serializers.ModelSerializer):
    biz_type_display = serializers.CharField(source="get_biz_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    pickup_node_detail = MapNodeSerializer(source="pickup_node", read_only=True)
    dropoff_node_detail = MapNodeSerializer(source="dropoff_node", read_only=True)
    assigned_agv_detail = AGVSerializer(source="assigned_agv", read_only=True)
    production_plan_no = serializers.CharField(source="production_plan.plan_no", read_only=True)
    work_order_no = serializers.CharField(source="work_order.order_no", read_only=True)
    operation_step_name = serializers.CharField(
        source="operation_step.name", read_only=True
    )
    schedule_run_batch_id = serializers.CharField(
        source="schedule_run.batch_id", read_only=True, allow_null=True
    )
    schedule_run_algorithm = serializers.CharField(
        source="schedule_run.get_algorithm_display", read_only=True
    )
    schedule_run_created_at = serializers.DateTimeField(
        source="schedule_run.created_at", read_only=True
    )
    schedule_run_task_count = serializers.IntegerField(
        source="schedule_run.task_count", read_only=True
    )
    schedule_run_agv_count = serializers.IntegerField(
        source="schedule_run.agv_count", read_only=True
    )
    schedule_run_makespan_seconds = serializers.FloatField(
        source="schedule_run.makespan_seconds", read_only=True
    )
    schedule_run_on_time_rate = serializers.FloatField(
        source="schedule_run.on_time_rate", read_only=True
    )

    class Meta:
        model = TransportTask
        fields = [
            "id", "task_no", "biz_type", "biz_type_display", "pickup_node", "pickup_node_detail", "dropoff_node",
            "dropoff_node_detail", "cargo_name", "cargo_weight", "priority",
            "priority_display", "status", "status_display", "assigned_agv",
            "assigned_agv_detail", "schedule_run", "production_plan", "production_plan_no",
            "work_order", "work_order_no",
            "operation_step", "operation_step_name",
            "schedule_run_batch_id", "schedule_run_algorithm",
            "schedule_run_created_at", "schedule_run_task_count",
            "schedule_run_agv_count", "schedule_run_makespan_seconds",
            "schedule_run_on_time_rate",
            "forecast_order_count", "demand_date", "release_at", "due_at",
            "sequence_number", "dispatch_order", "planned_wait_seconds", "optimization_details", "route", "total_distance", "estimated_duration",
            "scheduled_start", "scheduled_end", "started_at", "completed_at",
            "notes", "created_at", "updated_at",
        ]
        read_only_fields = [
            "status", "assigned_agv", "schedule_run", "production_plan",
            "forecast_order_count", "demand_date", "sequence_number", "dispatch_order", "planned_wait_seconds", "optimization_details", "route", "total_distance", "estimated_duration",
            "scheduled_start", "scheduled_end", "started_at", "completed_at",
            "created_at", "updated_at",
        ]
        extra_kwargs = {"task_no": {"required": False, "allow_blank": True}}

    def validate(self, attrs):
        pickup = attrs.get("pickup_node", getattr(self.instance, "pickup_node", None))
        dropoff = attrs.get("dropoff_node", getattr(self.instance, "dropoff_node", None))
        if pickup and dropoff and pickup == dropoff:
            raise serializers.ValidationError("取货点和放货点不能相同。")
        release_at = attrs.get("release_at", getattr(self.instance, "release_at", None))
        due_at = attrs.get("due_at", getattr(self.instance, "due_at", None))
        if release_at and due_at and release_at >= due_at:
            raise serializers.ValidationError("要求完成时间必须晚于最早释放时间。")
        return attrs

    def create(self, validated_data):
        if not validated_data.get("task_no"):
            validated_data["task_no"] = f"TASK-{int(time() * 1000)}"
        return super().create(validated_data)


class DispatchRecordSerializer(serializers.ModelSerializer):
    algorithm_display = serializers.CharField(source="get_algorithm_display", read_only=True)
    task_no = serializers.CharField(source="task.task_no", read_only=True)
    agv_code = serializers.CharField(source="agv.code", read_only=True, allow_null=True)

    class Meta:
        model = DispatchRecord
        fields = [
            "id", "task", "task_no", "agv", "agv_code", "algorithm",
            "algorithm_display", "success", "message", "route", "distance",
            "estimated_duration", "created_at",
        ]


class ScheduleRunSerializer(serializers.ModelSerializer):
    algorithm_display = serializers.CharField(source="get_algorithm_display", read_only=True)

    class Meta:
        model = ScheduleRun
        fields = [
            "id", "batch_id", "algorithm", "algorithm_display", "objective_name",
            "production_plan",
            "task_count", "agv_count", "makespan_seconds", "total_distance",
            "total_wait_seconds", "total_tardiness_seconds", "late_task_count",
            "on_time_rate", "iteration_count", "baseline_makespan_seconds",
            "improvement_percent", "assignments", "metrics", "created_at",
        ]


class ProductionPlanSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    forecast_run_id = serializers.IntegerField(read_only=True)
    forecast_selected_model = serializers.CharField(
        source="forecast_run.selected_model", read_only=True
    )
    forecast_horizon = serializers.IntegerField(source="forecast_run.horizon", read_only=True)
    work_order_no = serializers.CharField(source="work_order.order_no", read_only=True)
    planned_task_count = serializers.IntegerField(read_only=True)
    pending_task_count = serializers.IntegerField(read_only=True)
    completed_task_count = serializers.IntegerField(read_only=True)
    route_count = serializers.SerializerMethodField()

    class Meta:
        model = ProductionPlan
        fields = [
            "id", "plan_no", "name", "forecast_run", "forecast_run_id",
            "forecast_selected_model", "forecast_horizon", "status", "status_display",
            "work_order", "work_order_no",
            "planning_start", "planning_end", "tasks_per_order",
            "demand_buffer_percent", "release_lead_hours", "due_hour",
            "forecast_order_total", "task_count", "planned_task_count",
            "pending_task_count", "completed_task_count", "route_count", "assumptions",
            "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_route_count(self, obj):
        return int((obj.assumptions or {}).get("route_count", 0))
