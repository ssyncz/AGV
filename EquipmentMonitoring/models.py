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


class Tool(models.Model):
    """刀具档案：换刀决策的实体基础（磨损率、累计切削时长、剩余寿命）。"""

    class Status(models.TextChoices):
        IN_USE = "in_use", "在机"
        PENDING_CHANGE = "pending_change", "待换"
        CHANGED = "changed", "已换下"
        RETIRED = "retired", "已报废"

    code = models.CharField("刀具编号", max_length=32, unique=True)
    name = models.CharField("刀具名称", max_length=64, blank=True)
    equipment = models.ForeignKey(
        "Operations.Equipment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tools",
        verbose_name="装夹设备",
    )
    wear_ratio = models.FloatField("磨损率", default=0.0, help_text="0~1，来自刀具磨损监测")
    threshold = models.FloatField("换刀磨损阈值", default=0.78)
    life_minutes = models.FloatField("额定寿命（分钟）", default=240.0)
    used_minutes = models.FloatField("累计切削（分钟）", default=0.0)
    status = models.CharField(
        "状态", max_length=16, choices=Status.choices, default=Status.IN_USE
    )
    changed_at = models.DateTimeField("上次换刀时间", null=True, blank=True)
    notes = models.TextField("备注", blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "刀具"
        verbose_name_plural = "刀具"

    @property
    def remaining_minutes(self) -> float:
        return max(self.life_minutes - self.used_minutes, 0.0)

    @property
    def wear_alert(self) -> bool:
        return self.wear_ratio >= self.threshold

    def __str__(self):
        return f"{self.code}（{self.get_status_display()}）"


class ToolChangeRecord(models.Model):
    """一次换刀：旧刀换下、新刀装上，记录磨损与物流任务号。"""

    class Status(models.TextChoices):
        PENDING = "pending", "待换刀"
        DONE = "done", "已完成"

    equipment = models.ForeignKey(
        "Operations.Equipment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tool_changes",
        verbose_name="换刀设备",
    )
    old_tool = models.ForeignKey(
        Tool,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="changes_out",
        verbose_name="换下旧刀",
    )
    new_tool = models.ForeignKey(
        Tool,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="changes_in",
        verbose_name="装上新刀",
    )
    old_wear = models.FloatField("旧刀磨损率", default=0.0)
    old_used_minutes = models.FloatField("旧刀累计切削（分钟）", default=0.0)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.PENDING)
    operator = models.CharField("操作人", max_length=64, blank=True)
    change_task_no = models.CharField("换刀配送任务号", max_length=64, blank=True)
    return_task_no = models.CharField("旧刀回收任务号", max_length=64, blank=True)
    note = models.TextField("备注", blank=True)
    created_at = models.DateTimeField("发起时间", auto_now_add=True)
    completed_at = models.DateTimeField("完成时间", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "换刀记录"
        verbose_name_plural = "换刀记录"

    def __str__(self):
        return f"{self.old_tool_id} → {self.new_tool_id}（{self.get_status_display()}）"
