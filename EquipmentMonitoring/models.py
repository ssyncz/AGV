from django.db import models


class EquipmentDiagnosisRecord(models.Model):
    """一次设备多变量传感器诊断的可追溯记录。"""

    class Source(models.TextChoices):
        DATASET = "dataset", "内置样例"
        UPLOAD = "upload", "CSV 上传"
        MANUAL = "manual", "在线输入"

    class State(models.TextChoices):
        NORMAL = "normal", "正常"
        WORN = "worn", "磨损"
        FAULT = "fault", "故障"

    equipment_code = models.CharField("设备编号", max_length=64, default="CNC-01")
    equipment = models.ForeignKey(
        "Operations.Equipment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="diagnosis_records",
        verbose_name="设备主数据",
    )
    work_order = models.ForeignKey(
        "Operations.WorkOrder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="equipment_diagnoses",
        verbose_name="关联工单",
    )
    source = models.CharField(
        "数据来源", max_length=16, choices=Source.choices, default=Source.DATASET
    )
    sample_count = models.PositiveIntegerField("样本数", default=0)
    predicted_state = models.CharField(
        "综合状态", max_length=16, choices=State.choices, default=State.NORMAL
    )
    confidence = models.FloatField("置信度", default=0)
    state_counts = models.JSONField("状态分布", default=dict, blank=True)
    rule_alerts = models.JSONField("规则告警", default=list, blank=True)
    features_summary = models.JSONField("特征统计", default=dict, blank=True)
    series = models.JSONField("传感器序列", default=list, blank=True)
    model_metrics = models.JSONField("模型指标", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["equipment_code", "created_at"]),
            models.Index(fields=["predicted_state"]),
            models.Index(fields=["work_order", "predicted_state"]),
        ]
        verbose_name = "设备诊断记录"
        verbose_name_plural = "设备诊断记录"

    def __str__(self):
        return f"{self.equipment_code} - {self.get_predicted_state_display()}"
