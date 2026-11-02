from rest_framework import serializers

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


class SiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = ["id", "code", "name", "location", "is_active", "created_at"]
        read_only_fields = ["created_at"]


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "id", "code", "name", "specification", "unit", "is_active", "created_at",
        ]
        read_only_fields = ["created_at"]


class EquipmentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    site_detail = SiteSerializer(source="site", read_only=True)

    class Meta:
        model = Equipment
        fields = [
            "id", "code", "name", "equipment_type", "site", "site_detail",
            "status", "status_display", "last_seen_at", "metadata",
            "created_at", "updated_at",
        ]
        read_only_fields = ["last_seen_at", "created_at", "updated_at"]


class WorkCalendarSerializer(serializers.ModelSerializer):
    site_detail = SiteSerializer(source="site", read_only=True)

    class Meta:
        model = WorkCalendar
        fields = [
            "id", "site", "site_detail", "name", "weekdays", "shift_start",
            "shift_end", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class OperationStepSerializer(serializers.ModelSerializer):
    work_order_no = serializers.CharField(source="work_order.order_no", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    step_type_display = serializers.CharField(source="get_step_type_display", read_only=True)
    equipment_detail = EquipmentSerializer(source="equipment", read_only=True)

    class Meta:
        model = OperationStep
        fields = [
            "id", "work_order", "work_order_no", "sequence_number", "code", "name",
            "step_type", "step_type_display", "equipment", "equipment_detail",
            "standard_duration_minutes", "planned_start", "planned_end",
            "actual_start", "actual_end", "status", "status_display",
            "quality_gate", "notes", "created_at", "updated_at",
        ]
        read_only_fields = fields


class WorkOrderSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    quality_status_display = serializers.CharField(
        source="get_quality_status_display", read_only=True
    )
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    site_detail = SiteSerializer(source="site", read_only=True)
    product_detail = ProductSerializer(source="product", read_only=True)
    task_count = serializers.IntegerField(read_only=True)
    completed_task_count = serializers.IntegerField(read_only=True)
    open_alert_count = serializers.IntegerField(read_only=True)
    production_plans = serializers.SerializerMethodField()
    operation_steps = OperationStepSerializer(many=True, read_only=True)

    class Meta:
        model = WorkOrder
        fields = [
            "id", "order_no", "title", "site", "site_detail", "product",
            "product_detail", "quantity", "priority", "priority_display",
            "status", "status_display", "quality_status", "quality_status_display",
            "planned_start", "due_at", "block_reason", "notes", "released_at",
            "started_at", "completed_at", "task_count", "completed_task_count",
            "open_alert_count", "production_plans", "created_at", "updated_at",
            "operation_steps",
        ]
        read_only_fields = [
            "status", "quality_status", "block_reason", "released_at", "started_at",
            "completed_at", "task_count", "completed_task_count", "open_alert_count",
            "production_plans", "operation_steps", "created_at", "updated_at",
        ]
        extra_kwargs = {
            "order_no": {"required": False, "allow_blank": True},
            "site": {"required": False, "allow_null": True},
            "product": {"required": False, "allow_null": True},
        }

    def get_production_plans(self, obj):
        return [
            {
                "id": plan.id,
                "plan_no": plan.plan_no,
                "status": plan.status,
                "status_display": plan.get_status_display(),
                "planning_start": plan.planning_start,
                "planning_end": plan.planning_end,
            }
            for plan in obj.production_plans.all()
        ]


class AlertSerializer(serializers.ModelSerializer):
    source_type_display = serializers.CharField(
        source="get_source_type_display", read_only=True
    )
    severity_display = serializers.CharField(source="get_severity_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    work_order_no = serializers.CharField(source="work_order.order_no", read_only=True)
    equipment_code = serializers.CharField(source="equipment.code", read_only=True)

    class Meta:
        model = Alert
        fields = [
            "id", "fingerprint", "source_type", "source_type_display", "severity",
            "severity_display", "status", "status_display", "title", "message",
            "work_order", "work_order_no", "equipment", "equipment_code", "details",
            "acknowledged_by", "acknowledged_at", "resolved_by", "resolved_at",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


class OperationEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = OperationEvent
        fields = [
            "id", "work_order", "aggregate_type", "aggregate_id", "event_type",
            "summary", "from_status", "to_status", "actor", "trace_id", "payload",
            "created_at",
        ]
        read_only_fields = fields


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = [
            "id", "actor", "action", "object_type", "object_id", "before", "after",
            "reason", "trace_id", "created_at",
        ]
        read_only_fields = fields


class ExecutionEventSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    work_order_no = serializers.CharField(source="work_order.order_no", read_only=True)
    operation_step_name = serializers.CharField(
        source="operation_step.name", read_only=True
    )

    class Meta:
        model = ExecutionEvent
        fields = [
            "id", "external_id", "source", "event_type", "object_id",
            "work_order", "work_order_no", "operation_step",
            "operation_step_name", "payload", "status", "status_display",
            "result", "error", "created_at", "processed_at",
        ]
        read_only_fields = fields
