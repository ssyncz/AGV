from __future__ import annotations

import math
import uuid
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from DemandForecast.models import DemandForecastRun

from .models import MapNode, ProductionPlan, TransportTask


MAX_TASKS_PER_PLAN = 2000


class ProductionPlanningError(ValueError):
    """预测转生产计划时的输入或业务约束错误。"""


def _number(payload: dict, key: str, default: float) -> float:
    raw = payload.get(key, default)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ProductionPlanningError(f"{key} 必须是数字。") from exc
    if not math.isfinite(value):
        raise ProductionPlanningError(f"{key} 必须是有限数字。")
    return value


def _integer(payload: dict, key: str, default: int) -> int:
    value = _number(payload, key, default)
    if not value.is_integer():
        raise ProductionPlanningError(f"{key} 必须是整数。")
    return int(value)


def _parse_date(raw, key: str) -> date:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError) as exc:
        raise ProductionPlanningError(f"{key} 必须是 YYYY-MM-DD 日期。") from exc


def _local_datetime(day: date, hour: int) -> datetime:
    return timezone.make_aware(
        datetime.combine(day, time(hour=hour)), timezone.get_current_timezone()
    )


def _forecast_period_days(items: list[dict]) -> int:
    dates = []
    for item in items:
        try:
            dates.append(date.fromisoformat(str(item.get("date"))))
        except (TypeError, ValueError):
            continue
    if len(dates) < 2:
        return 1
    intervals = sorted((right - left).days for left, right in zip(dates, dates[1:]))
    return max(1, intervals[len(intervals) // 2])


def _normalize_routes(raw_routes, payload: dict) -> list[dict]:
    routes = raw_routes if isinstance(raw_routes, list) else []
    if not routes:
        pickup_id = payload.get("pickup_node_id")
        dropoff_id = payload.get("dropoff_node_id")
        if pickup_id and dropoff_id:
            routes = [
                {
                    "pickup_node_id": pickup_id,
                    "dropoff_node_id": dropoff_id,
                    "cargo_name": payload.get("cargo_name") or "预测订单货物",
                    "cargo_weight": payload.get("cargo_weight", 30),
                    "priority": payload.get("priority", 2),
                    "share": 1,
                }
            ]
        else:
            pickups = list(
                MapNode.objects.filter(is_active=True, node_type=MapNode.NodeType.PICKUP)
                .order_by("code")[:5]
            )
            dropoffs = list(
                MapNode.objects.filter(is_active=True, node_type=MapNode.NodeType.DROPOFF)
                .order_by("code")[:5]
            )
            if not pickups or not dropoffs:
                raise ProductionPlanningError(
                    "未提供取放货节点，且地图中没有可用的取货点/放货点。"
                )
            pair_count = min(len(pickups), len(dropoffs))
            routes = [
                {
                    "pickup_node_id": pickups[index].id,
                    "dropoff_node_id": dropoffs[index].id,
                    "cargo_name": payload.get("cargo_name") or "预测订单货物",
                    "cargo_weight": payload.get("cargo_weight", 30),
                    "priority": payload.get("priority", 2),
                    "share": 1,
                }
                for index in range(pair_count)
            ]

    normalized = []
    node_ids = set()
    for index, route in enumerate(routes):
        if not isinstance(route, dict):
            raise ProductionPlanningError(f"routes[{index}] 必须是对象。")
        try:
            pickup_id = int(route.get("pickup_node_id"))
            dropoff_id = int(route.get("dropoff_node_id"))
        except (TypeError, ValueError) as exc:
            raise ProductionPlanningError(
                f"routes[{index}] 的取货点/放货点必须是整数 ID。"
            ) from exc
        if pickup_id == dropoff_id:
            raise ProductionPlanningError("取货点和放货点不能相同。")
        try:
            weight = float(route.get("cargo_weight", payload.get("cargo_weight", 30)))
            priority = int(route.get("priority", payload.get("priority", 2)))
            share = float(route.get("share", 1))
        except (TypeError, ValueError) as exc:
            raise ProductionPlanningError(
                f"routes[{index}] 的重量、优先级或 share 格式错误。"
            ) from exc
        if weight <= 0:
            raise ProductionPlanningError("货物重量必须大于 0。")
        if priority not in {1, 2, 3, 4}:
            raise ProductionPlanningError("优先级必须是 1、2、3 或 4。")
        if share <= 0 or not math.isfinite(share):
            raise ProductionPlanningError("routes 的 share 必须大于 0。")
        normalized.append(
            {
                "pickup_node_id": pickup_id,
                "dropoff_node_id": dropoff_id,
                "cargo_name": str(
                    route.get("cargo_name") or payload.get("cargo_name") or "预测订单货物"
                )[:64],
                "cargo_weight": weight,
                "priority": priority,
                "share": share,
            }
        )
        node_ids.update((pickup_id, dropoff_id))

    nodes = MapNode.objects.in_bulk(node_ids)
    missing = sorted(node_ids - set(nodes))
    if missing:
        raise ProductionPlanningError(f"地图节点不存在：{missing}")
    inactive = [node.code for node in nodes.values() if not node.is_active]
    if inactive:
        raise ProductionPlanningError(f"地图节点已停用：{', '.join(inactive)}")

    total_share = sum(item["share"] for item in normalized)
    cursor = 0.0
    for item in normalized:
        item["share"] = item["share"] / total_share
        cursor += item["share"]
        item["cumulative_share"] = cursor
    return normalized


def _pick_route(routes: list[dict], index: int) -> dict:
    # 黄金比例低差异序列按份额选择路径，既避免同站点扎堆，也不需要额外状态。
    position = (index * 0.6180339887498949) % 1.0
    for route in routes:
        if position <= route["cumulative_share"] + 1e-9:
            return route
    return routes[-1]


def generate_production_plan(
    payload: dict,
    *,
    actor: str = "system",
    trace_id: str = "",
) -> ProductionPlan:
    """把一条预测记录转换为可调度的生产计划与运输任务。

    预测序列会按原间隔映射到 planning_start_date 起的连续计划期，避免历史演示数据
    直接生成已经过期的生产交期。订单量按累计取整分配，避免逐日四舍五入造成总量漂移。
    """
    try:
        forecast_run_id = int(payload.get("forecast_run_id"))
    except (TypeError, ValueError) as exc:
        raise ProductionPlanningError("forecast_run_id 必须是整数。") from exc

    try:
        forecast_run = DemandForecastRun.objects.get(pk=forecast_run_id)
    except DemandForecastRun.DoesNotExist as exc:
        raise ProductionPlanningError("预测记录不存在。") from exc
    forecast_items = forecast_run.forecast or []
    if not forecast_items:
        raise ProductionPlanningError("预测记录没有可用的预测序列。")

    tasks_per_order = _number(payload, "tasks_per_order", 1)
    demand_buffer_percent = _number(payload, "demand_buffer_percent", 10)
    release_lead_hours = _number(payload, "release_lead_hours", 24)
    due_hour = _integer(payload, "due_hour", 18)
    max_tasks = _integer(payload, "max_tasks", 500)
    if tasks_per_order <= 0 or tasks_per_order > 100:
        raise ProductionPlanningError("tasks_per_order 必须在 0 到 100 之间。")
    if demand_buffer_percent < 0 or demand_buffer_percent > 200:
        raise ProductionPlanningError("demand_buffer_percent 必须在 0 到 200 之间。")
    if release_lead_hours < 0 or release_lead_hours > 720:
        raise ProductionPlanningError("release_lead_hours 必须在 0 到 720 之间。")
    if due_hour < 0 or due_hour > 23:
        raise ProductionPlanningError("due_hour 必须在 0 到 23 之间。")
    if max_tasks < 1 or max_tasks > MAX_TASKS_PER_PLAN:
        raise ProductionPlanningError(
            f"max_tasks 必须在 1 到 {MAX_TASKS_PER_PLAN} 之间。"
        )

    planning_start = _parse_date(
        payload.get("planning_start_date") or (timezone.localdate() + timedelta(days=1)),
        "planning_start_date",
    )
    routes = _normalize_routes(payload.get("routes"), payload)
    period_days = _forecast_period_days(forecast_items)
    buffer_factor = 1.0 + demand_buffer_percent / 100.0

    parsed_orders = []
    for index, item in enumerate(forecast_items):
        try:
            order_count = float(item.get("order_count", 0))
        except (TypeError, ValueError) as exc:
            raise ProductionPlanningError(
                f"第 {index + 1} 期预测订单量不是有效数字。"
            ) from exc
        if not math.isfinite(order_count):
            raise ProductionPlanningError(f"第 {index + 1} 期预测订单量不是有限数字。")
        parsed_orders.append(max(0.0, order_count))

    raw_total = sum(parsed_orders)
    effective_total = raw_total * buffer_factor

    allocations = []
    cumulative_tasks = 0
    cumulative_orders = 0.0
    for index, order_count in enumerate(parsed_orders):
        cumulative_orders += order_count * buffer_factor
        target_tasks = int(math.floor(cumulative_orders * tasks_per_order + 0.5))
        task_count = max(0, target_tasks - cumulative_tasks)
        cumulative_tasks += task_count
        demand_day = planning_start + timedelta(days=index * period_days)
        allocations.append(
            {
                "demand_day": demand_day,
                "order_count": order_count,
                "effective_order_count": order_count * buffer_factor,
                "task_count": task_count,
            }
        )

    planned_tasks = sum(item["task_count"] for item in allocations)
    if planned_tasks > max_tasks:
        raise ProductionPlanningError(
            f"按当前参数会生成 {planned_tasks} 个任务，超过 max_tasks={max_tasks}。"
            "请提高 max_tasks 或降低 tasks_per_order。"
        )
    if planned_tasks == 0:
        raise ProductionPlanningError("预测总量过小，按当前任务换算比例没有生成任务。")

    planning_end = allocations[-1]["demand_day"]
    plan_no = f"PP-{timezone.localdate():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"
    name = str(payload.get("name") or f"需求预测计划 {forecast_run_id}")[:128]

    with transaction.atomic():
        plan = ProductionPlan.objects.create(
            plan_no=plan_no,
            name=name,
            forecast_run=forecast_run,
            planning_start=planning_start,
            planning_end=planning_end,
            tasks_per_order=tasks_per_order,
            demand_buffer_percent=demand_buffer_percent,
            release_lead_hours=release_lead_hours,
            due_hour=due_hour,
            forecast_order_total=round(raw_total, 3),
            task_count=planned_tasks,
            assumptions={
                "task_conversion": "cumulative_rounding",
                "tasks_per_order": tasks_per_order,
                "demand_buffer_percent": demand_buffer_percent,
                "release_lead_hours": release_lead_hours,
                "due_hour": due_hour,
                "source_forecast_start": forecast_items[0].get("date"),
                "source_forecast_end": forecast_items[-1].get("date"),
                "source_period_days": period_days,
                "mapped_planning_start": planning_start.isoformat(),
                "route_count": len(routes),
                "effective_order_total": round(effective_total, 3),
                "note": "预测序列按原周期间隔映射到计划开始日期，交期为计划日当天 due_hour。",
            },
        )

        from Operations.services import create_work_order_from_plan

        work_order = create_work_order_from_plan(
            plan, payload, actor=actor, trace_id=trace_id
        )
        plan.work_order = work_order
        plan.save(update_fields=["work_order", "updated_at"])
        from Operations.models import OperationStep

        logistics_step = work_order.operation_steps.filter(
            step_type=OperationStep.StepType.LOGISTICS
        ).order_by("sequence_number").first()

        tasks = []
        sequence = 0
        for allocation in allocations:
            count = allocation["task_count"]
            if not count:
                continue
            due_at = _local_datetime(allocation["demand_day"], due_hour)
            release_at = due_at - timedelta(hours=release_lead_hours)
            per_task_orders = allocation["effective_order_count"] / count
            for _ in range(count):
                route = _pick_route(routes, sequence)
                sequence += 1
                tasks.append(
                    TransportTask(
                        task_no=f"{plan_no}-{sequence:04d}",
                        work_order=work_order,
                        operation_step=logistics_step,
                        production_plan=plan,
                        forecast_order_count=round(per_task_orders, 4),
                        demand_date=allocation["demand_day"],
                        release_at=release_at,
                        due_at=due_at,
                        pickup_node_id=route["pickup_node_id"],
                        dropoff_node_id=route["dropoff_node_id"],
                        cargo_name=route["cargo_name"],
                        cargo_weight=route["cargo_weight"],
                        priority=route["priority"],
                        status=TransportTask.Status.PENDING,
                    )
                )
        TransportTask.objects.bulk_create(tasks, batch_size=200)
    return plan
