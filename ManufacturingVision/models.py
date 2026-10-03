from django.db import models


class VisionRecord(models.Model):
    """一次视觉检测（裂纹检测 / 工件识别）的可追溯记录。"""

    class TaskType(models.TextChoices):
        CRACK = "crack", "裂纹检测"
        WORKPIECE = "workpiece", "工件识别"

    class Source(models.TextChoices):
        UPLOAD = "upload", "本地上传"
        DATASET = "dataset", "内置数据集"

    task_type = models.CharField("检测任务", max_length=20, choices=TaskType.choices)
    source = models.CharField(
        "图片来源", max_length=20, choices=Source.choices, default=Source.UPLOAD
    )
    input_name = models.CharField("输入名称", max_length=255, blank=True)
    input_image = models.FileField("输入图片", upload_to="vision/inputs/%Y%m%d/", blank=True)
    result_image = models.FileField("结果图片", upload_to="vision/results/%Y%m%d/", blank=True)
    verdict = models.CharField("判定结果", max_length=32, blank=True)
    object_count = models.PositiveIntegerField("目标数量", default=0)
    elapsed_ms = models.FloatField("耗时(毫秒)", default=0)
    detected_objects = models.JSONField("检测目标", default=list, blank=True)
    parameters = models.JSONField("算法参数", default=dict, blank=True)
    metrics = models.JSONField("扩展指标", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["task_type", "created_at"]),
            models.Index(fields=["verdict"]),
        ]
        verbose_name = "视觉检测记录"
        verbose_name_plural = "视觉检测记录"

    def __str__(self):
        return f"{self.get_task_type_display()} - {self.verdict or '未判定'}"

    def delete(self, *args, **kwargs):
        """删除记录时同步清理已落盘的输入图与结果图。"""
        for field in (self.input_image, self.result_image):
            if field:
                field.delete(save=False)
        return super().delete(*args, **kwargs)
