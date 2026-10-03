from rest_framework import serializers

from .models import VisionRecord


class VisionRecordSerializer(serializers.ModelSerializer):
    task_type_display = serializers.CharField(source="get_task_type_display", read_only=True)
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    input_image_url = serializers.SerializerMethodField()
    result_image_url = serializers.SerializerMethodField()
    objects = serializers.JSONField(source="detected_objects", read_only=True)

    class Meta:
        model = VisionRecord
        fields = [
            "id", "task_type", "task_type_display", "source", "source_display",
            "input_name", "input_image_url", "result_image_url", "verdict",
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
