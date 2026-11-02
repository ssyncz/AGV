from django.contrib import admin

from .models import EquipmentDiagnosisRecord


@admin.register(EquipmentDiagnosisRecord)
class EquipmentDiagnosisRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "equipment_code",
        "equipment",
        "work_order",
        "source",
        "sample_count",
        "predicted_state",
        "confidence",
        "created_at",
    )
    list_filter = ("source", "predicted_state", "equipment_code")
    search_fields = ("equipment_code", "work_order__order_no")
