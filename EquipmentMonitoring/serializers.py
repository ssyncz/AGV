from rest_framework import serializers

from .models import EquipmentDiagnosisRecord


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
