from django.core.validators import MinValueValidator, RegexValidator
from django.db import models

from SchedulingDecision.models import MapNode, TransportTask


phone_validator = RegexValidator(
    regex=r"^1[3-9]\d{9}$",
    message="请输入有效的中国大陆 11 位手机号。",
)


class Customer(models.Model):
    """下单客户，手机号作为演示系统中的稳定身份。"""

    name = models.CharField("客户姓名", max_length=64)
    phone = models.CharField(
        "手机号",
        max_length=11,
        unique=True,
        validators=[phone_validator],
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "客户"
        verbose_name_plural = "客户"

    def __str__(self):
        return f"{self.name} ({self.phone})"


class Order(models.Model):
    """客户订单。执行状态由一对一 TransportTask 驱动。"""

    order_no = models.CharField("订单编号", max_length=32, unique=True)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="客户",
    )
    cargo_name = models.CharField("货物名称", max_length=64)
    cargo_weight = models.FloatField(
        "货物重量(kg)",
        validators=[MinValueValidator(0.1)],
    )
    pickup_node = models.ForeignKey(
        MapNode,
        on_delete=models.PROTECT,
        related_name="order_pickups",
        verbose_name="取货点",
    )
    dropoff_node = models.ForeignKey(
        MapNode,
        on_delete=models.PROTECT,
        related_name="order_dropoffs",
        verbose_name="放货点",
    )
    priority = models.PositiveSmallIntegerField(
        "优先级",
        choices=TransportTask.Priority.choices,
        default=TransportTask.Priority.NORMAL,
    )
    notes = models.CharField("备注", max_length=255, blank=True)
    status = models.CharField(
        "订单状态",
        max_length=20,
        choices=TransportTask.Status.choices,
        default=TransportTask.Status.PENDING,
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["customer", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(pickup_node=models.F("dropoff_node")),
                name="order_distinct_pickup_dropoff",
            )
        ]
        verbose_name = "订单"
        verbose_name_plural = "订单"

    def __str__(self):
        return f"{self.order_no} ({self.cargo_name})"


class OrderEvent(models.Model):
    """订单业务时间轴；仅在实际状态变化时追加。"""

    class EventType(models.TextChoices):
        CREATED = "created", "订单创建"
        SCHEDULED = "scheduled", "完成调度"
        STARTED = "started", "开始运输"
        COMPLETED = "completed", "运输完成"
        FAILED = "failed", "运输异常"
        CANCELLED = "cancelled", "订单取消"

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="events",
        verbose_name="订单",
    )
    event_type = models.CharField(
        "事件类型",
        max_length=20,
        choices=EventType.choices,
    )
    from_status = models.CharField("原状态", max_length=20, blank=True)
    to_status = models.CharField("新状态", max_length=20, blank=True)
    title = models.CharField("事件标题", max_length=64)
    description = models.CharField("事件说明", max_length=255, blank=True)
    occurred_at = models.DateTimeField("发生时间", auto_now_add=True)

    class Meta:
        ordering = ["occurred_at", "id"]
        indexes = [models.Index(fields=["order", "occurred_at"])]
        verbose_name = "订单事件"
        verbose_name_plural = "订单事件"

    def __str__(self):
        return f"{self.order.order_no} - {self.title}"
