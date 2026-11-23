from __future__ import annotations

import re
import uuid
from datetime import datetime

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone

from SchedulingDecision.models import TransportTask

from .models import Customer, Order, OrderEvent, phone_validator


class OrderError(Exception):
    """订单业务规则错误。"""


class OrderWorkflowError(OrderError):
    """订单当前状态不允许执行该操作。"""


EVENT_CONTENT = {
    TransportTask.Status.PENDING: (
        OrderEvent.EventType.CREATED,
        "订单已创建",
        "订单已提交，等待安排运输。",
    ),
    TransportTask.Status.ASSIGNED: (
        OrderEvent.EventType.SCHEDULED,
        "运输任务已分配",
        "调度系统已完成车辆与路线分配。",
    ),
    TransportTask.Status.IN_PROGRESS: (
        OrderEvent.EventType.STARTED,
        "运输已开始",
        "AGV 已开始执行本次运输任务。",
    ),
    TransportTask.Status.COMPLETED: (
        OrderEvent.EventType.COMPLETED,
        "运输已完成",
        "货物已送达目的工作站。",
    ),
    TransportTask.Status.FAILED: (
        OrderEvent.EventType.FAILED,
        "运输出现异常",
        "运输任务执行失败，请联系工作人员处理。",
    ),
    TransportTask.Status.CANCELLED: (
        OrderEvent.EventType.CANCELLED,
        "订单已取消",
        "订单及其运输任务已取消。",
    ),
}


def normalize_phone(value: str) -> str:
    phone = re.sub(r"[\s-]+", "", str(value or ""))
    try:
        phone_validator(phone)
    except DjangoValidationError as exc:
        raise OrderError(exc.messages[0]) from exc
    return phone


def _new_order_no() -> str:
    today = timezone.localdate().strftime("%Y%m%d")
    return f"ORD-{today}-{uuid.uuid4().hex[:6].upper()}"


def add_order_event(
    order: Order,
    *,
    event_type: str,
    from_status: str = "",
    to_status: str = "",
    title: str,
    description: str = "",
    occurred_at: datetime | None = None,
) -> OrderEvent:
    event = OrderEvent(
        order=order,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        title=title,
        description=description,
    )
    if occurred_at is not None:
        event.occurred_at = occurred_at
    event.save()
    return event


@transaction.atomic
def create_order(
    *,
    customer_name: str,
    customer_phone: str,
    cargo_name: str,
    cargo_weight: float,
    pickup_node,
    dropoff_node,
    priority: int = TransportTask.Priority.NORMAL,
    notes: str = "",
) -> Order:
    """原子创建客户、订单、运输任务以及第一条时间轴事件。"""
    phone = normalize_phone(customer_phone)
    if pickup_node.pk == dropoff_node.pk:
        raise OrderError("取货点和放货点不能相同。")
    if not pickup_node.is_active or not dropoff_node.is_active:
        raise OrderError("取货点和放货点必须处于启用状态。")
    if float(cargo_weight) < 0.1:
        raise OrderError("货物重量必须大于等于 0.1 kg。")
    if priority not in TransportTask.Priority.values:
        raise OrderError("订单优先级不合法。")

    customer, _ = Customer.objects.get_or_create(
        phone=phone,
        defaults={"name": customer_name.strip()},
    )
    order_no = _new_order_no()
    while Order.objects.filter(order_no=order_no).exists():
        order_no = _new_order_no()

    order = Order.objects.create(
        order_no=order_no,
        customer=customer,
        cargo_name=cargo_name.strip(),
        cargo_weight=cargo_weight,
        pickup_node=pickup_node,
        dropoff_node=dropoff_node,
        priority=priority,
        notes=notes.strip(),
        status=TransportTask.Status.PENDING,
    )
    task = TransportTask.objects.create(
        task_no=f"TASK-{order_no}",
        order=order,
        pickup_node=pickup_node,
        dropoff_node=dropoff_node,
        cargo_name=order.cargo_name,
        cargo_weight=order.cargo_weight,
        priority=order.priority,
        status=TransportTask.Status.PENDING,
        notes=order.notes,
    )
    add_order_event(
        order,
        event_type=OrderEvent.EventType.CREATED,
        to_status=TransportTask.Status.PENDING,
        title="订单已创建",
        description="订单已提交，等待安排运输。",
    )
    return order


def sync_order_status_from_task(
    task: TransportTask,
    *,
    description: str = "",
    occurred_at: datetime | None = None,
) -> Order | None:
    """把任务状态投影到订单；没有关联订单的历史任务直接忽略。"""
    if not task.order_id:
        return None

    order = Order.objects.select_for_update().get(pk=task.order_id)
    if order.status == task.status:
        return order

    from_status = order.status
    event_type, title, default_description = EVENT_CONTENT[task.status]
    order.status = task.status
    order.save(update_fields=["status", "updated_at"])
    add_order_event(
        order,
        event_type=event_type,
        from_status=from_status,
        to_status=task.status,
        title=title,
        description=description or default_description,
        occurred_at=occurred_at,
    )
    return order


@transaction.atomic
def update_pending_order(order_id: int, **changes) -> Order:
    """同步修改待调度订单及其唯一运输任务。"""
    # 调度链路先锁任务再锁订单；这里保持相同顺序，避免并发调度时死锁。
    task = (
        TransportTask.objects.select_for_update()
        .filter(order_id=order_id)
        .first()
    )
    if task is None:
        raise OrderWorkflowError("订单缺少关联运输任务，无法修改。")
    order = Order.objects.select_for_update().get(pk=order_id)
    if order.status != TransportTask.Status.PENDING:
        raise OrderWorkflowError("只有待调度订单可以修改。")

    allowed_fields = {
        "cargo_name",
        "cargo_weight",
        "pickup_node",
        "dropoff_node",
        "priority",
        "notes",
    }
    for field, value in changes.items():
        if field in allowed_fields:
            setattr(order, field, value)
            setattr(task, field, value)
    order.save()
    task.save()
    return order


@transaction.atomic
def cancel_order(order_id: int) -> Order:
    """取消待调度或已分配订单，并复用调度层的车辆状态回收逻辑。"""
    order = Order.objects.get(pk=order_id)
    if order.status not in {
        TransportTask.Status.PENDING,
        TransportTask.Status.ASSIGNED,
    }:
        raise OrderWorkflowError("只有待调度或已分配订单可以取消。")

    task_id = (
        TransportTask.objects.filter(order_id=order_id)
        .values_list("id", flat=True)
        .first()
    )
    if task_id is None:
        raise OrderWorkflowError("订单缺少关联运输任务，无法取消。")

    from SchedulingDecision.services import SchedulingError, cancel_task

    try:
        cancel_task(task_id)
    except TransportTask.DoesNotExist as exc:
        raise OrderWorkflowError("订单关联运输任务不存在，无法取消。") from exc
    except SchedulingError as exc:
        raise OrderWorkflowError(str(exc)) from exc
    order.refresh_from_db()
    return order
