from rest_framework import serializers

from .models import EquipmentDiagnosisRecord, Tool, ToolChangeRecord


class ToolSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    equipment_code = serializers.CharField(source="equipment.code", read_only=True, allow_null=True)
    remaining_minutes = serializers.FloatField(read_only=True)
    wear_alert = serializers.BooleanField(read_only=True)

    class Meta:
        model = Tool
        fields = [
            "id", "code", "name", "equipment", "equipment_code",
            "wear_ratio", "threshold", "life_minutes", "used_minutes",
            "remaining_minutes", "wear_alert", "status", "status_display",
            "changed_at", "notes", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class EquipmentDiagnosisRecordSerializer(serializers.ModelSerializer):
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    state_display = serializers.CharField(source="get_predicted_state_display", read_only=True)
    work_order_no = serializers.CharField(source="work_order.order_no", read_only=True)
    equipment_status = serializers.CharField(
        source="equipment.status", read_only=True, allow_null=True
    )

    class Meta:
        model = EquipmentDiagnosisRecord
        fields = [
            "id",
            "equipment_code",
            "equipment",
            "equipment_status",
            "work_order",
            "work_order_no",
            "source",
            "source_display",
            "sample_count",
            "predicted_state",
            "state_display",
            "confidence",
            "state_counts",
            "rule_alerts",
            "features_summary",
            "series",
            "model_metrics",
            "created_at",
        ]
        read_only_fields = fields


class EquipmentDiagnosisRecordListSerializer(EquipmentDiagnosisRecordSerializer):
    """列表用：不返回完整采样序列。

    EquipmentDiagnosisRecord.series 可能包含上万行采样点，列表接口按页返回时会把响应
    撑到上百 MB；列表只需要样本数、状态和告警这些汇总字段，明细走详情接口。
    """

    class Meta(EquipmentDiagnosisRecordSerializer.Meta):
        fields = [
            field
            for field in EquipmentDiagnosisRecordSerializer.Meta.fields
            if field != "series"
        ]
        read_only_fields = fields


class ToolChangeRecordSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    equipment_code = serializers.CharField(source="equipment.code", read_only=True, allow_null=True)
    old_tool_code = serializers.CharField(source="old_tool.code", read_only=True, allow_null=True)
    new_tool_code = serializers.CharField(source="new_tool.code", read_only=True, allow_null=True)

    class Meta:
        model = ToolChangeRecord
        fields = [
            "id", "equipment", "equipment_code", "old_tool", "old_tool_code",
            "new_tool", "new_tool_code", "old_wear", "old_used_minutes",
            "status", "status_display", "operator", "change_task_no",
            "return_task_no", "note", "created_at", "completed_at",
        ]
        read_only_fields = fields
