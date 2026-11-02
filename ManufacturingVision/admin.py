from django.contrib import admin

from .models import VisionRecord


@admin.register(VisionRecord)
class VisionRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id", "task_type", "source", "input_name", "verdict",
        "work_order", "quality_result", "object_count", "elapsed_ms", "created_at",
    )
    list_filter = ("task_type", "source", "verdict", "quality_result")
    search_fields = ("input_name", "verdict", "work_order__order_no")
    readonly_fields = ("created_at", "elapsed_ms")
    date_hierarchy = "created_at"
