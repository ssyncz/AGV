import uuid
from datetime import time

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Site(models.Model):
    """工厂/车间/仓库等业务站点主数据。"""

    code = models.CharField("站点编码", max_length=32, unique=True)
    name = models.CharField("站点名称", max_length=64)
    location = models.CharField("位置", max_length=128, blank=True)
    is_active = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "业务站点"
        verbose_name_plural = "业务站点"

    def __str__(self):
        return f"{self.code} - {self.name}"


class Product(models.Model):
    """生产物料/产品主数据。"""

    code = models.CharField("产品编码", max_length=32, unique=True)
    name = models.CharField("产品名称", max_length=64)
    specification = models.CharField("规格型号", max_length=128, blank=True)
    unit = models.CharField("单位", max_length=16, default="件")
    is_active = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "产品"
        verbose_name_plural = "产品"

    def __str__(self):
        return f"{self.code} - {self.name}"


class Equipment(models.Model):
    """生产设备主数据，设备诊断记录统一关联到这里。"""

    class Status(models.TextChoices):
        NORMAL = "normal", "正常"
        WARNING = "warning", "预警"
        FAULT = "fault", "故障"
        MAINTENANCE = "maintenance", "维护中"
        OFFLINE = "offline", "离线"

    code = models.CharField("设备编号", max_length=64, unique=True)
    name = models.CharField("设备名称", max_length=64, blank=True)
    equipment_type = models.CharField("设备类型", max_length=64, blank=True)
    site = models.ForeignKey(
        Site,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="equipment",
        verbose_name="所属站点",
    )
    status = models.CharField(
        "运行状态", max_length=16, choices=Status.choices, default=Status.NORMAL
    )
    last_seen_at = models.DateTimeField("最后诊断时间", null=True, blank=True)
    metadata = models.JSONField("扩展属性", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["code"]
        indexes = [models.Index(fields=["status", "site"])]
        verbose_name = "设备"
        verbose_name_plural = "设备"

    def __str__(self):
        return f"{self.code} - {self.name or self.equipment_type or '设备'}"


class WorkCalendar(models.Model):
    """站点班次日历，用于工序计划时间的资源可用窗口。"""

    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="work_calendars",
        verbose_name="所属站点",
    )
    name = models.CharField("日历名称", max_length=64)
    weekdays = models.JSONField("工作日", default=list, blank=True)
    shift_start = models.TimeField("班次开始", default=time(8, 0))
    shift_end = models.TimeField("班次结束", default=time(18, 0))
    is_active = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["site__code", "name"]
        verbose_name = "班次日历"
        verbose_name_plural = "班次日历"

    def save(self, *args, **kwargs):
        if not self.weekdays:
            self.weekdays = [1, 2, 3, 4, 5]
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.site.code} - {self.name}"


class WorkOrder(models.Model):
    """制造工单，是运输、质检、设备异常和预测计划的统一业务主线。"""

    class Priority(models.IntegerChoices):
        LOW = 1, "低"
        NORMAL = 2, "普通"
        HIGH = 3, "高"
        URGENT = 4, "紧急"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        RELEASED = "released", "已下达"
        IN_PROGRESS = "in_progress", "执行中"
        QUALITY_CHECK = "quality_check", "待质检"
        COMPLETED = "completed", "已完成"
        BLOCKED = "blocked", "已阻塞"
        CANCELLED = "cancelled", "已取消"

    class QualityStatus(models.TextChoices):
        PENDING = "pending", "待检"
        PASS = "pass", "合格"
        FAIL = "fail", "不合格"
        WAIVED = "waived", "让步放行"

    order_no = models.CharField("工单编号", max_length=40, unique=True, blank=True)
    title = models.CharField("工单名称", max_length=128)
    site = models.ForeignKey(
        Site,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_orders",
        verbose_name="所属站点",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_orders",
        verbose_name="产品",
    )
    quantity = models.DecimalField(
        "计划数量", max_digits=12, decimal_places=2, default=1,
        validators=[MinValueValidator(0)],
    )
    priority = models.PositiveSmallIntegerField(
        "优先级", choices=Priority.choices, default=Priority.NORMAL
    )
    status = models.CharField(
        "工单状态", max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    quality_status = models.CharField(
        "质检状态", max_length=16, choices=QualityStatus.choices,
        default=QualityStatus.PENDING,
    )
    planned_start = models.DateField("计划开始日期", null=True, blank=True)
    due_at = models.DateTimeField("要求完成时间", null=True, blank=True)
    block_reason = models.CharField("阻塞原因", max_length=255, blank=True)
    notes = models.TextField("备注", blank=True)
    released_at = models.DateTimeField("下达时间", null=True, blank=True)
    started_at = models.DateTimeField("开始时间", null=True, blank=True)
    completed_at = models.DateTimeField("完成时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "due_at"]),
            models.Index(fields=["quality_status", "created_at"]),
            models.Index(fields=["site", "status"]),
        ]
        verbose_name = "生产工单"
        verbose_name_plural = "生产工单"

    def save(self, *args, **kwargs):
        if not self.order_no:
            self.order_no = (
                f"WO-{timezone.localdate():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
            )
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order_no} - {self.title}"


class OperationStep(models.Model):
    """生产工单下的工序，运输任务只是工序之间的一种执行载体。"""

    class StepType(models.TextChoices):
        LOGISTICS = "logistics", "物流配送"
        PRODUCTION = "production", "生产加工"
        QUALITY = "quality", "质量检验"
        WAREHOUSE = "warehouse", "完工入库"
        CUSTOM = "custom", "自定义工序"

    class Status(models.TextChoices):
        PENDING = "pending", "未就绪"
        READY = "ready", "可开始"
        IN_PROGRESS = "in_progress", "执行中"
        QUALITY_CHECK = "quality_check", "待质检"
        COMPLETED = "completed", "已完成"
        BLOCKED = "blocked", "已阻塞"
        CANCELLED = "cancelled", "已取消"

    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.CASCADE,
        related_name="operation_steps",
        verbose_name="生产工单",
    )
    sequence_number = models.PositiveIntegerField("工序顺序")
    code = models.CharField("工序编码", max_length=32, blank=True)
    name = models.CharField("工序名称", max_length=64)
    step_type = models.CharField(
        "工序类型", max_length=20, choices=StepType.choices, default=StepType.PRODUCTION
    )
    equipment = models.ForeignKey(
        Equipment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operation_steps",
        verbose_name="执行设备",
    )
    standard_duration_minutes = models.PositiveIntegerField("标准工时(分钟)", default=60)
    planned_start = models.DateTimeField("计划开始", null=True, blank=True)
    planned_end = models.DateTimeField("计划完成", null=True, blank=True)
    actual_start = models.DateTimeField("实际开始", null=True, blank=True)
    actual_end = models.DateTimeField("实际完成", null=True, blank=True)
    status = models.CharField(
        "工序状态", max_length=20, choices=Status.choices, default=Status.PENDING
    )
    quality_gate = models.BooleanField("质量门禁", default=False)
    notes = models.CharField("备注", max_length=255, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["work_order", "sequence_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["work_order", "sequence_number"],
                name="uniq_work_order_operation_sequence",
            )
        ]
        indexes = [
            models.Index(fields=["work_order", "status"]),
            models.Index(fields=["step_type", "status"]),
        ]
        verbose_name = "生产工序"
        verbose_name_plural = "生产工序"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"OP-{self.sequence_number:03d}"
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.work_order.order_no} - {self.sequence_number:03d} {self.name}"


class Alert(models.Model):
    """跨模块统一异常中心，承接设备、质量、AGV、交期等告警。"""

    class SourceType(models.TextChoices):
        EQUIPMENT = "equipment", "设备"
        QUALITY = "quality", "质量"
        AGV = "agv", "AGV"
        DEADLINE = "deadline", "交期"
        SYSTEM = "system", "系统"

    class Severity(models.TextChoices):
        INFO = "info", "提示"
        WARNING = "warning", "警告"
        CRITICAL = "critical", "严重"

    class Status(models.TextChoices):
        OPEN = "open", "待处理"
        ACKNOWLEDGED = "acknowledged", "已确认"
        RESOLVED = "resolved", "已解决"

    fingerprint = models.CharField("去重指纹", max_length=160, blank=True, db_index=True)
    source_type = models.CharField(
        "告警来源", max_length=16, choices=SourceType.choices
    )
    severity = models.CharField(
        "严重程度", max_length=16, choices=Severity.choices,
        default=Severity.WARNING,
    )
    status = models.CharField(
        "处理状态", max_length=20, choices=Status.choices, default=Status.OPEN
    )
    title = models.CharField("告警标题", max_length=160)
    message = models.TextField("告警内容")
    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alerts",
        verbose_name="关联工单",
    )
    equipment = models.ForeignKey(
        Equipment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alerts",
        verbose_name="关联设备",
    )
    details = models.JSONField("扩展信息", default=dict, blank=True)
    acknowledged_by = models.CharField("确认人", max_length=80, blank=True)
    acknowledged_at = models.DateTimeField("确认时间", null=True, blank=True)
    resolved_by = models.CharField("解决人", max_length=80, blank=True)
    resolved_at = models.DateTimeField("解决时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "severity", "created_at"]),
            models.Index(fields=["source_type", "status"]),
            models.Index(fields=["work_order", "status"]),
        ]
        verbose_name = "运营告警"
        verbose_name_plural = "运营告警"

    def __str__(self):
        return f"[{self.get_severity_display()}] {self.title}"


class OperationEvent(models.Model):
    """统一业务事件，用于工单追溯和运营驾驶舱时间线。"""

    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="events",
        verbose_name="关联工单",
    )
    aggregate_type = models.CharField("聚合类型", max_length=40, default="work_order")
    aggregate_id = models.PositiveBigIntegerField("聚合 ID", null=True, blank=True)
    event_type = models.CharField("事件类型", max_length=64)
    summary = models.CharField("事件摘要", max_length=255)
    from_status = models.CharField("原状态", max_length=32, blank=True)
    to_status = models.CharField("新状态", max_length=32, blank=True)
    actor = models.CharField("操作人", max_length=80, default="system")
    trace_id = models.CharField("追踪 ID", max_length=64, blank=True, db_index=True)
    payload = models.JSONField("事件数据", default=dict, blank=True)
    created_at = models.DateTimeField("发生时间", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["work_order", "created_at"]),
            models.Index(fields=["aggregate_type", "aggregate_id"]),
            models.Index(fields=["event_type", "created_at"]),
        ]
        verbose_name = "运营事件"
        verbose_name_plural = "运营事件"

    def __str__(self):
        return f"{self.event_type} - {self.summary}"


class AuditLog(models.Model):
    """关键业务对象的操作审计。"""

    actor = models.CharField("操作人", max_length=80, default="system")
    action = models.CharField("操作", max_length=64)
    object_type = models.CharField("对象类型", max_length=64)
    object_id = models.CharField("对象 ID", max_length=64)
    before = models.JSONField("变更前", default=dict, blank=True)
    after = models.JSONField("变更后", default=dict, blank=True)
    reason = models.CharField("原因", max_length=255, blank=True)
    trace_id = models.CharField("追踪 ID", max_length=64, blank=True, db_index=True)
    created_at = models.DateTimeField("操作时间", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["object_type", "object_id", "created_at"]),
            models.Index(fields=["actor", "created_at"]),
        ]
        verbose_name = "审计日志"
        verbose_name_plural = "审计日志"

    def __str__(self):
        return f"{self.actor} {self.action} {self.object_type}#{self.object_id}"


class ExecutionEvent(models.Model):
    """现场 RCS/MES/PLC 上报的外部执行事件，用于幂等接收和追溯。"""

    class Status(models.TextChoices):
        RECEIVED = "received", "已接收"
        PROCESSED = "processed", "已处理"
        FAILED = "failed", "处理失败"
        IGNORED = "ignored", "忽略重复"

    external_id = models.CharField("外部事件 ID", max_length=128, unique=True)
    source = models.CharField("事件来源", max_length=64, default="external")
    event_type = models.CharField("事件类型", max_length=64)
    object_id = models.CharField("对象 ID", max_length=64, blank=True)
    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="execution_events",
        verbose_name="关联工单",
    )
    operation_step = models.ForeignKey(
        OperationStep,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="execution_events",
        verbose_name="关联工序",
    )
    payload = models.JSONField("事件数据", default=dict, blank=True)
    status = models.CharField(
        "处理状态", max_length=16, choices=Status.choices, default=Status.RECEIVED
    )
    result = models.JSONField("处理结果", default=dict, blank=True)
    error = models.TextField("错误信息", blank=True)
    created_at = models.DateTimeField("接收时间", auto_now_add=True)
    processed_at = models.DateTimeField("处理时间", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event_type", "status"]),
            models.Index(fields=["source", "created_at"]),
        ]
        verbose_name = "外部执行事件"
        verbose_name_plural = "外部执行事件"

    def __str__(self):
        return f"{self.source}:{self.event_type} ({self.external_id})"
