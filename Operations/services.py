from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from .models import (
    Alert,
    AuditLog,
    Equipment,
    ExecutionEvent,
    OperationStep,
    OperationEvent,
    Product,
    Site,
    WorkCalendar,
    WorkOrder,
)


DEFAULT_SITE_CODE = "SITE-01"
DEFAULT_PRODUCT_CODE = "PROD-01"


class OperationError(ValueError):
    """业务状态机或跨模块联动错误。"""


def actor_from_request(request) -> str:
    if request is None:
        return "system"
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user.get_username()
    return str(getattr(request, "headers", {}).get("X-Operator") or "system")[:80]


def trace_id_from_request(request) -> str:
    if request is None:
        return uuid.uuid4().hex
    return str(getattr(request, "request_id", "") or uuid.uuid4().hex)[:64]


def ensure_default_site() -> Site:
    site, _ = Site.objects.get_or_create(
        code=DEFAULT_SITE_CODE,
        defaults={"name": "默认制造站点", "location": "未配置"},
    )
    return site


def ensure_default_product() -> Product:
    product, _ = Product.objects.get_or_create(
        code=DEFAULT_PRODUCT_CODE,
        defaults={"name": "默认产品", "specification": "未配置"},
    )
    return product


def ensure_equipment(code: str, site: Site | None = None) -> Equipment:
    equipment, _ = Equipment.objects.get_or_create(
        code=code,
        defaults={"name": code, "site": site or ensure_default_site()},
    )
    if site is not None and equipment.site_id != site.id:
        equipment.site = site
        equipment.save(update_fields=["site", "updated_at"])
    return equipment


DEFAULT_OPERATION_DEFINITIONS = [
    (10, "OP-010", "物料配送", OperationStep.StepType.LOGISTICS, 60, False),
    (20, "OP-020", "生产加工", OperationStep.StepType.PRODUCTION, 120, False),
    (30, "OP-030", "质量检验", OperationStep.StepType.QUALITY, 30, True),
    (40, "OP-040", "完工入库", OperationStep.StepType.WAREHOUSE, 30, False),
]


def _calendar_for_site(site: Site | None) -> WorkCalendar | None:
    if site is None:
        site = ensure_default_site()
    return WorkCalendar.objects.filter(site=site, is_active=True).order_by("id").first()


def _next_shift_start(moment: datetime, calendar: WorkCalendar | None) -> datetime:
    local = timezone.localtime(moment)
    weekdays = set(calendar.weekdays or [1, 2, 3, 4, 5]) if calendar else {1, 2, 3, 4, 5}
    shift_start = calendar.shift_start if calendar else time(8, 0)
    shift_end = calendar.shift_end if calendar else time(18, 0)
    for offset in range(15):
        day = local.date() + timedelta(days=offset)
        if day.isoweekday() not in weekdays:
            continue
        candidate = timezone.make_aware(datetime.combine(day, shift_start))
        end = timezone.make_aware(datetime.combine(day, shift_end))
        if offset == 0 and local <= end:
            return max(local, candidate)
        if offset > 0:
            return candidate
    return moment


def _add_working_minutes(
    start: datetime, minutes: int, calendar: WorkCalendar | None
) -> datetime:
    remaining = max(0, int(minutes))
    cursor = _next_shift_start(start, calendar)
    weekdays = set(calendar.weekdays or [1, 2, 3, 4, 5]) if calendar else {1, 2, 3, 4, 5}
    shift_start = calendar.shift_start if calendar else time(8, 0)
    shift_end = calendar.shift_end if calendar else time(18, 0)
    for _ in range(30):
        local = timezone.localtime(cursor)
        if local.isoweekday() not in weekdays:
            cursor = _next_shift_start(cursor + timedelta(days=1), calendar)
            continue
        end = timezone.make_aware(datetime.combine(local.date(), shift_end))
        available = max(0, int((end - local).total_seconds() // 60))
        if remaining <= available:
            return cursor + timedelta(minutes=remaining)
        remaining -= available
        cursor = _next_shift_start(end + timedelta(days=1), calendar)
    return cursor + timedelta(minutes=remaining)


def create_default_operation_steps(work_order: WorkOrder) -> list[OperationStep]:
    existing = list(work_order.operation_steps.order_by("sequence_number"))
    if existing:
        return existing
    calendar = _calendar_for_site(work_order.site)
    if work_order.planned_start:
        shift_start = calendar.shift_start if calendar else time(8, 0)
        cursor = timezone.make_aware(
            datetime.combine(work_order.planned_start, shift_start)
        )
    else:
        cursor = timezone.now().replace(second=0, microsecond=0)
    cursor = _next_shift_start(cursor, calendar)
    steps = []
    for index, (sequence, code, name, step_type, minutes, quality_gate) in enumerate(
        DEFAULT_OPERATION_DEFINITIONS
    ):
        planned_end = _add_working_minutes(cursor, minutes, calendar)
        status = (
            OperationStep.Status.READY
            if index == 0 and work_order.status == WorkOrder.Status.RELEASED
            else OperationStep.Status.PENDING
        )
        steps.append(
            OperationStep(
                work_order=work_order,
                sequence_number=sequence,
                code=code,
                name=name,
                step_type=step_type,
                standard_duration_minutes=minutes,
                planned_start=cursor,
                planned_end=planned_end,
                status=status,
                quality_gate=quality_gate,
            )
        )
        cursor = planned_end
    return OperationStep.objects.bulk_create(steps)


def _next_pending_operation(work_order: WorkOrder, sequence_number: int):
    return (
        work_order.operation_steps.filter(
            sequence_number__gt=sequence_number,
            status=OperationStep.Status.PENDING,
        )
        .order_by("sequence_number")
        .first()
    )


def _refresh_operation_readiness(work_order: WorkOrder) -> None:
    first_unfinished = (
        work_order.operation_steps.exclude(
            status__in=[OperationStep.Status.COMPLETED, OperationStep.Status.CANCELLED]
        )
        .order_by("sequence_number")
        .first()
    )
    if first_unfinished and first_unfinished.status == OperationStep.Status.PENDING:
        first_unfinished.status = OperationStep.Status.READY
        first_unfinished.save(update_fields=["status", "updated_at"])


def start_operation_step(
    step_id: int, *, actor: str = "system", trace_id: str = ""
) -> OperationStep:
    with transaction.atomic():
        step = (
            OperationStep.objects.select_for_update()
            .select_related("work_order")
            .get(pk=step_id)
        )
        work_order = WorkOrder.objects.select_for_update().get(pk=step.work_order_id)
        if work_order.status in {WorkOrder.Status.COMPLETED, WorkOrder.Status.CANCELLED}:
            raise OperationError("已完成或已取消工单不能开始工序。")
        if step.status != OperationStep.Status.READY:
            raise OperationError("只有已就绪工序可以开始。")
        previous = work_order.operation_steps.filter(
            sequence_number__lt=step.sequence_number
        ).exclude(status=OperationStep.Status.COMPLETED)
        if previous.exists():
            raise OperationError("存在未完成的前序工序，请按工序顺序执行。")
        old_status = work_order.status
        step.status = OperationStep.Status.IN_PROGRESS
        step.actual_start = timezone.now()
        step.save(update_fields=["status", "actual_start", "updated_at"])
        if work_order.status in {WorkOrder.Status.DRAFT, WorkOrder.Status.RELEASED}:
            work_order.status = WorkOrder.Status.IN_PROGRESS
            if not work_order.started_at:
                work_order.started_at = timezone.now()
            work_order.save(update_fields=["status", "started_at", "updated_at"])
        record_event(
            work_order=work_order,
            event_type="operation.started",
            summary=f"工序 {step.sequence_number:03d} {step.name} 开始",
            from_status=old_status,
            to_status=work_order.status,
            actor=actor,
            trace_id=trace_id,
            aggregate_type="operation_step",
            aggregate_id=step.id,
        )
        record_audit(
            actor=actor,
            action="operation_start",
            object_type="operation_step",
            object_id=step.id,
            before={"status": OperationStep.Status.READY},
            after={"status": step.status},
            trace_id=trace_id,
        )
        return step


def complete_operation_step(
    step_id: int, *, actor: str = "system", trace_id: str = "", reason: str = ""
) -> OperationStep:
    with transaction.atomic():
        step = (
            OperationStep.objects.select_for_update()
            .select_related("work_order")
            .get(pk=step_id)
        )
        work_order = WorkOrder.objects.select_for_update().get(pk=step.work_order_id)
        if step.status != OperationStep.Status.IN_PROGRESS:
            raise OperationError("只有执行中的工序可以完成。")
        from SchedulingDecision.models import TransportTask

        if step.transport_tasks.filter(
            status__in=[
                TransportTask.Status.PENDING,
                TransportTask.Status.ASSIGNED,
                TransportTask.Status.IN_PROGRESS,
            ]
        ).exists():
            raise OperationError("该工序仍有未完成的运输任务，不能完成。")
        if step.quality_gate and work_order.quality_status not in {
            WorkOrder.QualityStatus.PASS,
            WorkOrder.QualityStatus.WAIVED,
        }:
            raise OperationError("质量门禁工序尚未通过质检，不能完成。")
        old_status = work_order.status
        step.status = OperationStep.Status.COMPLETED
        step.actual_end = timezone.now()
        step.save(update_fields=["status", "actual_end", "updated_at"])
        next_step = _next_pending_operation(work_order, step.sequence_number)
        if next_step:
            next_step.status = OperationStep.Status.READY
            next_step.save(update_fields=["status", "updated_at"])
        elif not work_order.operation_steps.exclude(
            status__in=[OperationStep.Status.COMPLETED, OperationStep.Status.CANCELLED]
        ).exists():
            if work_order.status not in {WorkOrder.Status.COMPLETED, WorkOrder.Status.CANCELLED}:
                work_order.status = WorkOrder.Status.QUALITY_CHECK
                work_order.save(update_fields=["status", "updated_at"])
        record_event(
            work_order=work_order,
            event_type="operation.completed",
            summary=f"工序 {step.sequence_number:03d} {step.name} 完成",
            from_status=old_status,
            to_status=work_order.status,
            actor=actor,
            trace_id=trace_id,
            aggregate_type="operation_step",
            aggregate_id=step.id,
            payload={"reason": reason},
        )
        record_audit(
            actor=actor,
            action="operation_complete",
            object_type="operation_step",
            object_id=step.id,
            before={"status": OperationStep.Status.IN_PROGRESS},
            after={"status": step.status},
            reason=reason,
            trace_id=trace_id,
        )
        return step


def block_operation_step(step: OperationStep, reason: str) -> None:
    if step.status not in {
        OperationStep.Status.PENDING,
        OperationStep.Status.READY,
        OperationStep.Status.IN_PROGRESS,
        OperationStep.Status.QUALITY_CHECK,
    }:
        return
    step.status = OperationStep.Status.BLOCKED
    step.notes = reason[:255]
    step.save(update_fields=["status", "notes", "updated_at"])


def _status_payload(work_order: WorkOrder) -> dict:
    return {
        "status": work_order.status,
        "quality_status": work_order.quality_status,
        "block_reason": work_order.block_reason,
    }


def record_event(
    *,
    work_order: WorkOrder | None,
    event_type: str,
    summary: str,
    aggregate_type: str = "work_order",
    aggregate_id: int | None = None,
    from_status: str = "",
    to_status: str = "",
    actor: str = "system",
    trace_id: str = "",
    payload: dict | None = None,
) -> OperationEvent:
    return OperationEvent.objects.create(
        work_order=work_order,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id or (work_order.id if work_order else None),
        event_type=event_type,
        summary=summary,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        trace_id=trace_id,
        payload=payload or {},
    )


def record_audit(
    *,
    actor: str,
    action: str,
    object_type: str,
    object_id,
    before: dict | None = None,
    after: dict | None = None,
    reason: str = "",
    trace_id: str = "",
) -> AuditLog:
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        before=before or {},
        after=after or {},
        reason=reason,
        trace_id=trace_id,
    )


def create_work_order(
    payload: dict,
    *,
    actor: str = "system",
    trace_id: str = "",
) -> WorkOrder:
    title = str(payload.get("title") or "").strip()
    if not title:
        raise OperationError("工单名称不能为空。")
    site = ensure_default_site()
    product = ensure_default_product()
    if payload.get("site_id"):
        site = Site.objects.filter(pk=payload["site_id"]).first()
        if site is None:
            raise OperationError("业务站点不存在。")
    if payload.get("product_id"):
        product = Product.objects.filter(pk=payload["product_id"]).first()
        if product is None:
            raise OperationError("产品不存在。")

    due_at = payload.get("due_at") or None
    if isinstance(due_at, str):
        try:
            due_at = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise OperationError("due_at 必须是 ISO 8601 时间。") from exc
    if due_at and timezone.is_naive(due_at):
        due_at = timezone.make_aware(due_at)
    planned_start = payload.get("planned_start") or None
    if isinstance(planned_start, str) and planned_start:
        try:
            planned_start = date.fromisoformat(planned_start)
        except ValueError as exc:
            raise OperationError("planned_start 必须是 YYYY-MM-DD 日期。") from exc

    work_order = WorkOrder.objects.create(
        order_no=str(payload.get("order_no") or "").strip(),
        title=title,
        site=site,
        product=product,
        quantity=payload.get("quantity", 1),
        priority=int(payload.get("priority") or WorkOrder.Priority.NORMAL),
        planned_start=planned_start,
        due_at=due_at,
        notes=str(payload.get("notes") or ""),
    )
    create_default_operation_steps(work_order)
    record_event(
        work_order=work_order,
        event_type="work_order.created",
        summary=f"创建工单 {work_order.order_no}",
        actor=actor,
        trace_id=trace_id,
        payload={"title": work_order.title},
    )
    record_audit(
        actor=actor,
        action="create",
        object_type="work_order",
        object_id=work_order.id,
        after=_status_payload(work_order),
        trace_id=trace_id,
    )
    return work_order


def create_work_order_from_plan(
    plan,
    payload: dict | None = None,
    *,
    actor: str = "system",
    trace_id: str = "",
) -> WorkOrder:
    """预测计划落库时同步创建已下达工单。"""

    payload = payload or {}
    site = ensure_default_site()
    product = ensure_default_product()
    due_at = timezone.make_aware(
        datetime.combine(plan.planning_end, time(hour=int(getattr(plan, "due_hour", 18))))
    )
    work_order = WorkOrder.objects.create(
        title=f"{plan.name} · 执行工单",
        site=site,
        product=product,
        quantity=plan.forecast_order_total or plan.task_count,
        priority=int(payload.get("priority") or WorkOrder.Priority.NORMAL),
        status=WorkOrder.Status.RELEASED,
        planned_start=plan.planning_start,
        due_at=due_at,
        released_at=timezone.now(),
        notes=f"由生产计划 {plan.plan_no} 自动生成。",
    )
    create_default_operation_steps(work_order)
    record_event(
        work_order=work_order,
        event_type="work_order.created",
        summary=f"由生产计划 {plan.plan_no} 生成工单",
        actor=actor,
        trace_id=trace_id,
        payload={"plan_id": plan.id, "plan_no": plan.plan_no},
    )
    record_event(
        work_order=work_order,
        event_type="work_order.released",
        summary="计划同步下达工单",
        from_status=WorkOrder.Status.DRAFT,
        to_status=WorkOrder.Status.RELEASED,
        actor=actor,
        trace_id=trace_id,
    )
    return work_order


def _event_for_transition(
    work_order: WorkOrder,
    *,
    event_type: str,
    summary: str,
    old_status: str,
    actor: str,
    trace_id: str,
) -> None:
    record_event(
        work_order=work_order,
        event_type=event_type,
        summary=summary,
        from_status=old_status,
        to_status=work_order.status,
        actor=actor,
        trace_id=trace_id,
    )


def transition_work_order(
    work_order_id: int,
    action: str,
    *,
    actor: str = "system",
    trace_id: str = "",
    reason: str = "",
) -> WorkOrder:
    with transaction.atomic():
        work_order = WorkOrder.objects.select_for_update().get(pk=work_order_id)
        old_status = work_order.status
        now = timezone.now()
        update_fields = ["status", "updated_at"]

        if action == "release":
            if work_order.status != WorkOrder.Status.DRAFT:
                raise OperationError("只有草稿工单可以下达。")
            work_order.status = WorkOrder.Status.RELEASED
            work_order.released_at = now
            update_fields.append("released_at")
            first_step = work_order.operation_steps.order_by("sequence_number").first()
            if first_step and first_step.status == OperationStep.Status.PENDING:
                first_step.status = OperationStep.Status.READY
                first_step.save(update_fields=["status", "updated_at"])
            event_type, summary = "work_order.released", "工单已下达"
        elif action == "start":
            if work_order.status != WorkOrder.Status.RELEASED:
                raise OperationError("只有已下达工单可以开始执行。")
            work_order.status = WorkOrder.Status.IN_PROGRESS
            work_order.started_at = now
            update_fields.append("started_at")
            event_type, summary = "work_order.started", "工单开始执行"
        elif action == "quality-check":
            if work_order.status not in {WorkOrder.Status.IN_PROGRESS, WorkOrder.Status.QUALITY_CHECK}:
                raise OperationError("只有执行中的工单可以进入质检。")
            from SchedulingDecision.models import TransportTask

            if work_order.transport_tasks.filter(
                status__in=[
                    TransportTask.Status.PENDING,
                    TransportTask.Status.ASSIGNED,
                    TransportTask.Status.IN_PROGRESS,
                ]
            ).exists():
                raise OperationError("仍有未完成的运输任务，不能提交质检。")
            quality_step = work_order.operation_steps.filter(
                step_type=OperationStep.StepType.QUALITY
            ).order_by("sequence_number").first()
            if quality_step:
                earlier_incomplete = work_order.operation_steps.filter(
                    sequence_number__lt=quality_step.sequence_number
                ).exclude(status=OperationStep.Status.COMPLETED)
                if earlier_incomplete.exists():
                    raise OperationError("前序生产工序尚未完成，不能开始质检。")
                if quality_step.status == OperationStep.Status.PENDING:
                    quality_step.status = OperationStep.Status.READY
                if quality_step.status not in {
                    OperationStep.Status.READY,
                    OperationStep.Status.IN_PROGRESS,
                }:
                    raise OperationError("当前质检工序状态不允许提交质检。")
                quality_step.status = OperationStep.Status.IN_PROGRESS
                quality_step.actual_start = quality_step.actual_start or now
                quality_step.save(
                    update_fields=["status", "actual_start", "updated_at"]
                )
            work_order.status = WorkOrder.Status.QUALITY_CHECK
            event_type, summary = "work_order.quality_check", "工单已提交质检"
        elif action == "complete":
            if work_order.status not in {
                WorkOrder.Status.IN_PROGRESS,
                WorkOrder.Status.QUALITY_CHECK,
            }:
                raise OperationError("只有执行中或待质检工单可以完成。")
            if work_order.quality_status not in {
                WorkOrder.QualityStatus.PASS,
                WorkOrder.QualityStatus.WAIVED,
            }:
                raise OperationError("工单尚未通过质检，不能完成。")
            from SchedulingDecision.models import TransportTask

            if work_order.transport_tasks.filter(
                status__in=[
                    TransportTask.Status.PENDING,
                    TransportTask.Status.ASSIGNED,
                    TransportTask.Status.IN_PROGRESS,
                ]
            ).exists():
                raise OperationError("仍有未完成的运输任务，不能完成工单。")
            if work_order.operation_steps.exclude(
                status__in=[OperationStep.Status.COMPLETED, OperationStep.Status.CANCELLED]
            ).exists():
                raise OperationError("仍有未完成的生产工序，不能完成工单。")
            work_order.status = WorkOrder.Status.COMPLETED
            work_order.completed_at = now
            update_fields.append("completed_at")
            event_type, summary = "work_order.completed", "工单已完成"
        elif action == "block":
            if work_order.status in {WorkOrder.Status.COMPLETED, WorkOrder.Status.CANCELLED}:
                raise OperationError("已完成或已取消工单不能阻塞。")
            if not reason.strip():
                raise OperationError("阻塞工单必须填写原因。")
            work_order.status = WorkOrder.Status.BLOCKED
            work_order.block_reason = reason.strip()[:255]
            update_fields.append("block_reason")
            active_step = work_order.operation_steps.filter(
                status__in=[OperationStep.Status.IN_PROGRESS, OperationStep.Status.READY]
            ).order_by("sequence_number").first()
            if active_step:
                block_operation_step(active_step, reason.strip())
            event_type, summary = "work_order.blocked", f"工单被阻塞：{reason.strip()}"
        elif action == "resume":
            if work_order.status != WorkOrder.Status.BLOCKED:
                raise OperationError("只有阻塞中的工单可以恢复。")
            if work_order.quality_status == WorkOrder.QualityStatus.FAIL:
                raise OperationError("质检不合格工单必须先完成复检。")
            blocked_step = work_order.operation_steps.filter(
                status=OperationStep.Status.BLOCKED
            ).order_by("sequence_number").first()
            if blocked_step:
                blocked_step.status = OperationStep.Status.READY
                blocked_step.save(update_fields=["status", "updated_at"])
            work_order.status = WorkOrder.Status.IN_PROGRESS
            work_order.block_reason = ""
            update_fields.append("block_reason")
            event_type, summary = "work_order.resumed", "工单已恢复执行"
        elif action == "cancel":
            if work_order.status == WorkOrder.Status.COMPLETED:
                raise OperationError("已完成工单不能取消。")
            from SchedulingDecision.models import TransportTask

            if work_order.transport_tasks.filter(
                status__in=[
                    TransportTask.Status.ASSIGNED,
                    TransportTask.Status.IN_PROGRESS,
                ]
            ).exists():
                raise OperationError("工单存在已分配或执行中的运输任务，不能取消。")
            work_order.transport_tasks.filter(
                status=TransportTask.Status.PENDING
            ).update(status=TransportTask.Status.CANCELLED)
            work_order.operation_steps.exclude(
                status__in=[OperationStep.Status.COMPLETED, OperationStep.Status.CANCELLED]
            ).update(status=OperationStep.Status.CANCELLED)
            work_order.status = WorkOrder.Status.CANCELLED
            event_type, summary = "work_order.cancelled", "工单已取消"
        else:
            raise OperationError(f"不支持的工单动作：{action}")

        work_order.save(update_fields=sorted(set(update_fields)))
        _event_for_transition(
            work_order,
            event_type=event_type,
            summary=summary,
            old_status=old_status,
            actor=actor,
            trace_id=trace_id,
        )
        record_audit(
            actor=actor,
            action=action,
            object_type="work_order",
            object_id=work_order.id,
            before={"status": old_status},
            after=_status_payload(work_order),
            reason=reason,
            trace_id=trace_id,
        )
        return work_order


def record_quality_result(
    work_order_id: int,
    vision_record,
    quality_result: str,
    *,
    reason: str = "",
    actor: str = "system",
    trace_id: str = "",
) -> WorkOrder:
    if quality_result not in {WorkOrder.QualityStatus.PASS, WorkOrder.QualityStatus.FAIL}:
        raise OperationError("quality_result 必须是 pass 或 fail。")
    with transaction.atomic():
        work_order = WorkOrder.objects.select_for_update().get(pk=work_order_id)
        old_status = work_order.status
        work_order.quality_status = quality_result
        update_fields = ["quality_status", "updated_at"]

        from ManufacturingVision.models import VisionRecord

        VisionRecord.objects.filter(pk=vision_record.pk).update(
            work_order=work_order, quality_result=quality_result
        )
        quality_step = work_order.operation_steps.filter(
            step_type=OperationStep.StepType.QUALITY
        ).order_by("sequence_number").first()

        if quality_result == WorkOrder.QualityStatus.FAIL:
            message = reason or f"视觉检测判定不合格（记录 #{vision_record.id}）"
            if work_order.status not in {WorkOrder.Status.COMPLETED, WorkOrder.Status.CANCELLED}:
                work_order.status = WorkOrder.Status.BLOCKED
                work_order.block_reason = f"视觉质检失败：{message}"[:255]
                update_fields.extend(["status", "block_reason"])
            Alert.objects.update_or_create(
                fingerprint=f"quality:{work_order.id}:{vision_record.id}",
                defaults={
                    "source_type": Alert.SourceType.QUALITY,
                    "severity": Alert.Severity.CRITICAL,
                    "status": Alert.Status.OPEN,
                    "title": f"{work_order.order_no} 质检不合格",
                    "message": message,
                    "work_order": work_order,
                    "details": {
                        "vision_record_id": vision_record.id,
                        "task_type": vision_record.task_type,
                        "verdict": vision_record.verdict,
                    },
                },
            )
            if quality_step and quality_step.status != OperationStep.Status.COMPLETED:
                quality_step.status = OperationStep.Status.BLOCKED
                quality_step.actual_start = quality_step.actual_start or timezone.now()
                quality_step.save(
                    update_fields=["status", "actual_start", "updated_at"]
                )
            event_type, summary = "quality.failed", f"视觉质检失败：{message}"
        else:
            Alert.objects.filter(
                work_order=work_order,
                source_type=Alert.SourceType.QUALITY,
                status__in=[Alert.Status.OPEN, Alert.Status.ACKNOWLEDGED],
            ).update(status=Alert.Status.RESOLVED, resolved_at=timezone.now())
            if quality_step and quality_step.status != OperationStep.Status.COMPLETED:
                quality_step.status = OperationStep.Status.COMPLETED
                quality_step.actual_start = quality_step.actual_start or timezone.now()
                quality_step.actual_end = timezone.now()
                quality_step.save(
                    update_fields=["status", "actual_start", "actual_end", "updated_at"]
                )
                next_step = _next_pending_operation(
                    work_order, quality_step.sequence_number
                )
                if next_step:
                    next_step.status = OperationStep.Status.READY
                    next_step.save(update_fields=["status", "updated_at"])
            if (
                work_order.status == WorkOrder.Status.BLOCKED
                and work_order.block_reason.startswith("视觉质检失败")
            ):
                work_order.status = (
                    WorkOrder.Status.QUALITY_CHECK
                    if not work_order.operation_steps.exclude(
                        status__in=[
                            OperationStep.Status.COMPLETED,
                            OperationStep.Status.CANCELLED,
                        ]
                    ).exists()
                    else WorkOrder.Status.IN_PROGRESS
                )
                work_order.block_reason = ""
                update_fields.extend(["status", "block_reason"])
            event_type, summary = "quality.passed", "视觉质检通过"

        work_order.save(update_fields=sorted(set(update_fields)))
        _event_for_transition(
            work_order,
            event_type=event_type,
            summary=summary,
            old_status=old_status,
            actor=actor,
            trace_id=trace_id,
        )
        record_audit(
            actor=actor,
            action="quality_result",
            object_type="work_order",
            object_id=work_order.id,
            before={"status": old_status},
            after=_status_payload(work_order),
            reason=reason,
            trace_id=trace_id,
        )
        return work_order


def record_equipment_result(
    diagnosis_record,
    *,
    actor: str = "system",
    trace_id: str = "",
) -> Equipment:
    equipment = diagnosis_record.equipment
    if equipment is None:
        raise OperationError("设备诊断记录缺少设备主数据。")
    state = diagnosis_record.predicted_state
    if state == "fault":
        equipment.status = Equipment.Status.FAULT
    elif state == "worn":
        equipment.status = Equipment.Status.WARNING
    else:
        equipment.status = Equipment.Status.NORMAL
    equipment.last_seen_at = timezone.now()
    equipment.save(update_fields=["status", "last_seen_at", "updated_at"])

    work_order = diagnosis_record.work_order
    if state in {"fault", "worn"}:
        severity = (
            Alert.Severity.CRITICAL if state == "fault" else Alert.Severity.WARNING
        )
        alert_texts = []
        for item in diagnosis_record.rule_alerts or []:
            if isinstance(item, dict):
                text = item.get("message") or item.get("label") or item.get("detail")
                if text:
                    alert_texts.append(str(text))
            elif item:
                alert_texts.append(str(item))
        alert, _ = Alert.objects.update_or_create(
            fingerprint=f"equipment:{equipment.id}:{state}",
            defaults={
                "source_type": Alert.SourceType.EQUIPMENT,
                "severity": severity,
                "status": Alert.Status.OPEN,
                "title": f"设备 {equipment.code} {diagnosis_record.get_predicted_state_display()}",
                "message": "；".join(alert_texts)
                or f"模型判定设备状态为 {diagnosis_record.get_predicted_state_display()}。",
                "equipment": equipment,
                "work_order": work_order,
                "details": {
                    "diagnosis_record_id": diagnosis_record.id,
                    "confidence": diagnosis_record.confidence,
                    "predicted_state": state,
                },
            },
        )
        if work_order and work_order.status not in {
            WorkOrder.Status.COMPLETED,
            WorkOrder.Status.CANCELLED,
        }:
            active_step = work_order.operation_steps.filter(
                status__in=[
                    OperationStep.Status.IN_PROGRESS,
                    OperationStep.Status.READY,
                ]
            ).order_by("sequence_number").first()
            if active_step:
                block_operation_step(
                    active_step,
                    f"设备异常：{equipment.code} {diagnosis_record.get_predicted_state_display()}",
                )
            work_order.status = WorkOrder.Status.BLOCKED
            work_order.block_reason = f"设备异常：{equipment.code} {diagnosis_record.get_predicted_state_display()}"[:255]
            work_order.save(update_fields=["status", "block_reason", "updated_at"])
            record_event(
                work_order=work_order,
                event_type="equipment.blocked",
                summary=work_order.block_reason,
                to_status=work_order.status,
                actor=actor,
                trace_id=trace_id,
                aggregate_type="equipment_diagnosis",
                aggregate_id=diagnosis_record.id,
                payload={"alert_id": alert.id, "equipment": equipment.code},
            )
    else:
        Alert.objects.filter(
            equipment=equipment,
            source_type=Alert.SourceType.EQUIPMENT,
            status__in=[Alert.Status.OPEN, Alert.Status.ACKNOWLEDGED],
        ).update(status=Alert.Status.RESOLVED, resolved_at=timezone.now())
        if work_order:
            record_event(
                work_order=work_order,
                event_type="equipment.normal",
                summary=f"设备 {equipment.code} 恢复正常",
                actor=actor,
                trace_id=trace_id,
                aggregate_type="equipment_diagnosis",
                aggregate_id=diagnosis_record.id,
            )
    return equipment


def record_task_event(
    task,
    event_type: str,
    summary: str,
    *,
    actor: str = "system",
    trace_id: str = "",
) -> None:
    if not getattr(task, "work_order_id", None):
        return
    work_order = task.work_order
    record_event(
        work_order=work_order,
        event_type=event_type,
        summary=summary,
        actor=actor,
        trace_id=trace_id,
        aggregate_type="transport_task",
        aggregate_id=task.id,
        payload={"task_no": task.task_no, "status": task.status},
    )


def sync_work_order_after_task_start(task, *, actor: str = "system", trace_id: str = "") -> None:
    if not task.work_order_id:
        return
    work_order = task.work_order
    if task.operation_step_id:
        operation_step = task.operation_step
        if operation_step.status in {
            OperationStep.Status.PENDING,
            OperationStep.Status.READY,
        }:
            operation_step.status = OperationStep.Status.IN_PROGRESS
            operation_step.actual_start = operation_step.actual_start or timezone.now()
            operation_step.save(
                update_fields=["status", "actual_start", "updated_at"]
            )
            record_event(
                work_order=work_order,
                event_type="operation.started",
                summary=f"运输任务开始，工序 {operation_step.sequence_number:03d} {operation_step.name} 进入执行中",
                actor=actor,
                trace_id=trace_id,
                aggregate_type="operation_step",
                aggregate_id=operation_step.id,
            )
    if work_order.status == WorkOrder.Status.RELEASED:
        old_status = work_order.status
        work_order.status = WorkOrder.Status.IN_PROGRESS
        if not work_order.started_at:
            work_order.started_at = timezone.now()
        work_order.save(update_fields=["status", "started_at", "updated_at"])
        _event_for_transition(
            work_order,
            event_type="work_order.started",
            summary="首个运输任务开始，工单进入执行中",
            old_status=old_status,
            actor=actor,
            trace_id=trace_id,
        )
    record_task_event(task, "task.started", f"运输任务 {task.task_no} 开始", actor=actor, trace_id=trace_id)


def sync_work_order_after_task_complete(task, *, actor: str = "system", trace_id: str = "") -> None:
    if not task.work_order_id:
        return
    from SchedulingDecision.models import TransportTask

    work_order = task.work_order
    record_task_event(task, "task.completed", f"运输任务 {task.task_no} 完成", actor=actor, trace_id=trace_id)
    if task.operation_step_id:
        operation_step = task.operation_step
        step_active = work_order.transport_tasks.filter(
            operation_step=operation_step,
            status__in=[
                TransportTask.Status.PENDING,
                TransportTask.Status.ASSIGNED,
                TransportTask.Status.IN_PROGRESS,
            ],
        ).exists()
        if not step_active and operation_step.status != OperationStep.Status.COMPLETED:
            operation_step.status = OperationStep.Status.COMPLETED
            operation_step.actual_end = timezone.now()
            operation_step.save(
                update_fields=["status", "actual_end", "updated_at"]
            )
            next_step = _next_pending_operation(
                work_order, operation_step.sequence_number
            )
            if next_step:
                next_step.status = OperationStep.Status.READY
                next_step.save(update_fields=["status", "updated_at"])
            record_event(
                work_order=work_order,
                event_type="operation.completed",
                summary=f"全部运输任务完成，工序 {operation_step.sequence_number:03d} {operation_step.name} 完成",
                actor=actor,
                trace_id=trace_id,
                aggregate_type="operation_step",
                aggregate_id=operation_step.id,
            )
        return
    has_active = work_order.transport_tasks.filter(
        status__in=[
            TransportTask.Status.PENDING,
            TransportTask.Status.ASSIGNED,
            TransportTask.Status.IN_PROGRESS,
        ]
    ).exists()
    if not has_active and work_order.status in {
        WorkOrder.Status.RELEASED,
        WorkOrder.Status.IN_PROGRESS,
    }:
        old_status = work_order.status
        work_order.status = WorkOrder.Status.QUALITY_CHECK
        work_order.save(update_fields=["status", "updated_at"])
        _event_for_transition(
            work_order,
            event_type="work_order.quality_check",
            summary="全部运输任务完成，等待质量确认",
            old_status=old_status,
            actor=actor,
            trace_id=trace_id,
        )


def create_transport_task(
    work_order_id: int,
    payload: dict,
    *,
    actor: str = "system",
    trace_id: str = "",
):
    from SchedulingDecision.models import MapNode, TransportTask

    with transaction.atomic():
        work_order = WorkOrder.objects.select_for_update().get(pk=work_order_id)
        if work_order.status in {WorkOrder.Status.COMPLETED, WorkOrder.Status.CANCELLED}:
            raise OperationError("已完成或已取消工单不能新增运输任务。")
        try:
            pickup = MapNode.objects.get(pk=payload.get("pickup_node_id"))
            dropoff = MapNode.objects.get(pk=payload.get("dropoff_node_id"))
        except (MapNode.DoesNotExist, TypeError, ValueError) as exc:
            raise OperationError("取货点或放货点不存在。") from exc
        if pickup.id == dropoff.id:
            raise OperationError("取货点和放货点不能相同。")
        weight = payload.get("cargo_weight", 1)
        try:
            weight = float(weight)
        except (TypeError, ValueError) as exc:
            raise OperationError("货物重量必须是数字。") from exc
        if weight <= 0:
            raise OperationError("货物重量必须大于 0。")
        plan = work_order.production_plans.order_by("-created_at").first()
        steps = create_default_operation_steps(work_order)
        logistics_step = next(
            (step for step in steps if step.step_type == OperationStep.StepType.LOGISTICS),
            None,
        )
        if logistics_step and logistics_step.status == OperationStep.Status.PENDING:
            logistics_step.status = OperationStep.Status.READY
            logistics_step.save(update_fields=["status", "updated_at"])
        task = TransportTask.objects.create(
            task_no=f"{work_order.order_no}-{uuid.uuid4().hex[:6].upper()}",
            work_order=work_order,
            production_plan=plan,
            operation_step=logistics_step,
            pickup_node=pickup,
            dropoff_node=dropoff,
            cargo_name=str(payload.get("cargo_name") or work_order.title)[:64],
            cargo_weight=weight,
            priority=int(payload.get("priority") or work_order.priority),
        )
        record_task_event(
            task,
            "task.created",
            f"工单新增运输任务 {task.task_no}",
            actor=actor,
            trace_id=trace_id,
        )
        return task


def ingest_execution_event(
    payload: dict,
    *,
    actor: str = "external",
    trace_id: str = "",
) -> tuple[ExecutionEvent, bool]:
    external_id = str(payload.get("external_id") or "").strip()
    event_type = str(payload.get("event_type") or "").strip()
    if not external_id:
        raise OperationError("external_id 不能为空。")
    if not event_type:
        raise OperationError("event_type 不能为空。")
    event, created = ExecutionEvent.objects.get_or_create(
        external_id=external_id,
        defaults={
            "source": str(payload.get("source") or "external")[:64],
            "event_type": event_type,
            "object_id": str(payload.get("object_id") or "")[:64],
            "payload": payload,
            "status": ExecutionEvent.Status.RECEIVED,
        },
    )
    if not created:
        return event, True

    try:
        object_id = int(payload.get("object_id"))
        if event_type == "transport_task.started":
            from SchedulingDecision.models import TransportTask
            from SchedulingDecision.services import start_task

            task = TransportTask.objects.get(pk=object_id)
            event.work_order_id = task.work_order_id
            event.operation_step_id = task.operation_step_id
            task = start_task(object_id)
            event.result = {"task_id": task.id, "status": task.status}
        elif event_type == "transport_task.completed":
            from SchedulingDecision.models import TransportTask
            from SchedulingDecision.services import complete_task

            task = TransportTask.objects.get(pk=object_id)
            event.work_order_id = task.work_order_id
            event.operation_step_id = task.operation_step_id
            task = complete_task(object_id)
            event.result = {"task_id": task.id, "status": task.status}
        elif event_type == "operation_step.started":
            step = OperationStep.objects.get(pk=object_id)
            event.work_order_id = step.work_order_id
            event.operation_step_id = step.id
            step = start_operation_step(object_id, actor=actor, trace_id=trace_id)
            event.result = {"operation_step_id": step.id, "status": step.status}
        elif event_type == "operation_step.completed":
            step = OperationStep.objects.get(pk=object_id)
            event.work_order_id = step.work_order_id
            event.operation_step_id = step.id
            step = complete_operation_step(
                object_id,
                actor=actor,
                trace_id=trace_id,
                reason=str(payload.get("reason") or ""),
            )
            event.result = {"operation_step_id": step.id, "status": step.status}
        else:
            raise OperationError(f"不支持的执行事件类型：{event_type}")
        event.status = ExecutionEvent.Status.PROCESSED
        event.processed_at = timezone.now()
    except Exception as exc:  # noqa: BLE001
        event.status = ExecutionEvent.Status.FAILED
        event.error = str(exc)
        event.processed_at = timezone.now()
    event.save()
    return event, False
