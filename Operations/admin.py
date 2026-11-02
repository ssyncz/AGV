from django.contrib import admin

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


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "location", "is_active")
    search_fields = ("code", "name")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "specification", "unit", "is_active")
    search_fields = ("code", "name", "specification")


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "equipment_type", "site", "status", "last_seen_at")
    list_filter = ("status", "site", "equipment_type")
    search_fields = ("code", "name")


@admin.register(WorkCalendar)
class WorkCalendarAdmin(admin.ModelAdmin):
    list_display = ("site", "name", "weekdays", "shift_start", "shift_end", "is_active")
    list_filter = ("site", "is_active")
    search_fields = ("name", "site__code")


@admin.register(OperationStep)
class OperationStepAdmin(admin.ModelAdmin):
    list_display = (
        "work_order", "sequence_number", "code", "name", "step_type",
        "status", "quality_gate", "planned_start", "planned_end",
    )
    list_filter = ("step_type", "status", "quality_gate")
    search_fields = ("work_order__order_no", "code", "name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_no", "title", "site", "product", "status", "quality_status",
        "priority", "due_at", "created_at",
    )
    list_filter = ("status", "quality_status", "priority", "site")
    search_fields = ("order_no", "title", "product__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = (
        "id", "severity", "source_type", "status", "title", "work_order", "created_at",
    )
    list_filter = ("severity", "source_type", "status")
    search_fields = ("title", "message", "work_order__order_no")
    readonly_fields = ("created_at", "updated_at")


@admin.register(OperationEvent)
class OperationEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "work_order", "summary", "actor", "created_at")
    list_filter = ("event_type", "aggregate_type")
    search_fields = ("summary", "work_order__order_no")
    readonly_fields = [field.name for field in OperationEvent._meta.fields]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("actor", "action", "object_type", "object_id", "created_at")
    list_filter = ("action", "object_type")
    search_fields = ("actor", "object_id", "trace_id")
    readonly_fields = [field.name for field in AuditLog._meta.fields]


@admin.register(ExecutionEvent)
class ExecutionEventAdmin(admin.ModelAdmin):
    list_display = (
        "external_id", "source", "event_type", "status", "work_order",
        "operation_step", "created_at", "processed_at",
    )
    list_filter = ("source", "event_type", "status")
    search_fields = ("external_id", "object_id", "error")
    readonly_fields = [field.name for field in ExecutionEvent._meta.fields]
