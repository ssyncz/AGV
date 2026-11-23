from rest_framework import serializers

from .models import VisionRecord


class VisionRecordSerializer(serializers.ModelSerializer):
    task_type_display = serializers.CharField(source="get_task_type_display", read_only=True)
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    verdict_display = serializers.SerializerMethodField()
    input_image_url = serializers.SerializerMethodField()
    result_image_url = serializers.SerializerMethodField()
    objects = serializers.JSONField(source="detected_objects", read_only=True)
    work_order_no = serializers.CharField(source="work_order.order_no", read_only=True)
    quality_result_display = serializers.CharField(
        source="get_quality_result_display", read_only=True
    )

    class Meta:
        model = VisionRecord
        fields = [
            "id", "task_type", "task_type_display", "source", "source_display",
            "work_order", "work_order_no", "quality_result", "quality_result_display",
            "input_name", "input_image_url", "result_image_url", "verdict", "verdict_display",
            "object_count", "elapsed_ms", "objects", "parameters", "metrics",
            "created_at",
        ]
        read_only_fields = fields

    def _file_url(self, obj, attribute):
        field = getattr(obj, attribute)
        return field.url if field else ""

    def get_input_image_url(self, obj):
        return self._file_url(obj, "input_image")

    def get_result_image_url(self, obj):
        return self._file_url(obj, "result_image")

    def get_verdict_display(self, obj):
        if obj.task_type == VisionRecord.TaskType.DEFECT:
            metrics = obj.metrics or {}
            if metrics.get("is_uncertain"):
                return "不属于6类缺陷或无缺陷，请人工复核"
            return metrics.get("predicted_label") or metrics.get("raw_predicted_label") or obj.verdict
        if obj.task_type == VisionRecord.TaskType.CRACK:
            return "检出裂纹" if obj.verdict == "crack" else "未见裂纹"
        if obj.task_type == VisionRecord.TaskType.WORKPIECE:
            return f"识别工件 {obj.object_count} 个"
        return obj.verdict
