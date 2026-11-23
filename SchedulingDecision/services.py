from __future__ import annotations

import copy
import heapq
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from .models import (
    AGV,
    DispatchRecord,
    MapEdge,
    MapNode,
    ProductionPlan,
    ScheduleRun,
    TransportTask,
)

# 单机多任务顺序优化的精确 DP 只在小规模下启用（指数复杂度）。
# 主链路（多 AGV 调度）用的是「最优插入 + VND」，不依赖这里；
# 把 DP 视作可选的精确性对照实验，改小/关闭不影响主流程。
EXACT_DP_MAX_TASKS = 10


MIN_BATTERY_PERCENT = 15.0
SAFETY_GAP_SECONDS = 2.0
LOADING_SECONDS = 6.0
UNLOADING_SECONDS = 6.0
BATTERY_DROP_PER_METER = 0.06
DEFAULT_AGV_WEIGHT = 30.0
DEFAULT_WAIT_WEIGHT = 0.20
DEFAULT_DISTANCE_WEIGHT = 0.005
DEFAULT_PRIORITY_WEIGHT = 0.02
DEFAULT_TARDINESS_WEIGHT = 5.0


class SchedulingError(Exception):
    """调度请求无法完成时抛出。"""


def _sync_order_from_task(task: TransportTask, description: str = "") -> None:
    """订单是可选关联，历史任务没有订单时保持原调度行为。"""
    if not task.order_id:
        return
    from Orders.services import sync_order_status_from_task

    sync_order_status_from_task(task, description=description)


@dataclass
class PathResult:
    nodes: list[int]
    distance: float


@dataclass
class TaskPlan:
    task_id: int
    task_no: str
    agv_id: int
    agv_code: str
    sequence_number: int
    start_time: datetime
    end_time: datetime
    route: dict
    distance: float
    wait_seconds: float
    release_wait_seconds: float
    duration_seconds: float
    release_time: datetime | None
    due_time: datetime | None
    tardiness_seconds: float
    is_late: bool


@dataclass
class ScheduleEvaluation:
    feasible: bool
    objective: float = 0.0
    makespan_seconds: float = 0.0
    total_completion_seconds: float = 0.0
    total_distance: float = 0.0
    total_wait_seconds: float = 0.0
    total_release_wait_seconds: float = 0.0
    total_tardiness_seconds: float = 0.0
    late_task_count: int = 0
    on_time_rate: float = 100.0
    used_agvs: int = 0
    assignments: dict[int, int] = field(default_factory=dict)
    orders: dict[int, list[int]] = field(default_factory=dict)
    plans: dict[int, TaskPlan] = field(default_factory=dict)
    agv_summary: dict[int, dict] = field(default_factory=dict)
    message: str = ""

def build_graph() -> dict[int, list[tuple[int, float, float]]]:
    """构建仓库地图邻接表：node -> [(neighbor, distance, speed_limit)]."""
    adjacency: dict[int, list[tuple[int, float, float]]] = {}
    for node in MapNode.objects.filter(is_active=True):
        adjacency[node.id] = []

    edges = MapEdge.objects.filter(
        is_active=True,
        start_node__is_active=True,
        end_node__is_active=True,
    ).select_related("start_node", "end_node")
    for edge in edges:
        adjacency.setdefault(edge.start_node_id, []).append(
            (edge.end_node_id, edge.distance, edge.speed_limit)
        )
        if edge.bidirectional:
            adjacency.setdefault(edge.end_node_id, []).append(
                (edge.start_node_id, edge.distance, edge.speed_limit)
            )
    return adjacency


class GraphRouter:
    """带最短路径缓存的 Dijkstra 路由器。"""

    def __init__(self, graph: dict[int, list[tuple[int, float, float]]]):
        self.graph = graph
        self.cache: dict[tuple[int, int], PathResult] = {}

    def path(self, start: int, end: int) -> PathResult:
        key = (start, end)
        if key not in self.cache:
            self.cache[key] = self._dijkstra(start, end)
        return self.cache[key]

    def _dijkstra(self, start: int, end: int) -> PathResult:
        if start == end:
            return PathResult([start], 0.0)
        if start not in self.graph or end not in self.graph:
            raise SchedulingError(f"地图节点 {start} 或 {end} 不可达。")

        distances = {start: 0.0}
        previous: dict[int, int] = {}
        queue = [(0.0, start)]
        visited = set()

        while queue:
            current_distance, current = heapq.heappop(queue)
            if current in visited:
                continue
            visited.add(current)
            if current == end:
                break
            for neighbor, edge_distance, _speed_limit in self.graph.get(current, []):
                next_distance = current_distance + edge_distance
                if next_distance < distances.get(neighbor, float("inf")):
                    distances[neighbor] = next_distance
                    previous[neighbor] = current
                    heapq.heappush(queue, (next_distance, neighbor))

        if end not in distances:
            raise SchedulingError("起点和终点之间没有可用路径。")

        nodes = [end]
        while nodes[-1] != start:
            nodes.append(previous[nodes[-1]])
        nodes.reverse()
        return PathResult(nodes, round(distances[end], 3))


def shortest_path(graph, start: int, end: int) -> PathResult:
    """兼容旧调用的最短路径函数。"""
    return GraphRouter(graph).path(start, end)


def _join_paths(first: PathResult, second: PathResult) -> PathResult:
    if first.nodes and second.nodes and first.nodes[-1] == second.nodes[0]:
        nodes = first.nodes + second.nodes[1:]
    else:
        nodes = first.nodes + second.nodes
    return PathResult(nodes, round(first.distance + second.distance, 3))


def _segment_distance(graph, start: int, end: int) -> float:
    candidates = [item[1] for item in graph.get(start, []) if item[0] == end]
    return min(candidates) if candidates else 0.1

def _resolve_node_wait(
    reservations: dict[int, list[dict]],
    node_id: int,
    arrival: datetime,
    agv_id: int,
    task_id: int,
) -> float:
    proposed_start = arrival
    proposed_end = arrival + timedelta(seconds=SAFETY_GAP_SECONDS)
    for interval in sorted(reservations.get(node_id, []), key=lambda item: item["start"]):
        if interval["agv_id"] == agv_id and interval["task_id"] == task_id:
            continue
        overlaps = proposed_start <= interval["end"] and proposed_end >= interval["start"]
        if overlaps:
            proposed_start = max(
                proposed_start, interval["end"] + timedelta(seconds=SAFETY_GAP_SECONDS)
            )
            proposed_end = proposed_start + timedelta(seconds=SAFETY_GAP_SECONDS)
    return max(0.0, (proposed_start - arrival).total_seconds())


def _reserve_node(
    reservations: dict[int, list[dict]],
    node_id: int,
    start: datetime,
    end: datetime,
    agv_id: int,
    task_id: int,
) -> None:
    reservations.setdefault(node_id, []).append(
        {"start": start, "end": end, "agv_id": agv_id, "task_id": task_id}
    )


def _plan_task_route(
    agv: AGV,
    task: TransportTask,
    router: GraphRouter,
    base_time: datetime,
    reservations: dict[int, list[dict]],
    start_node_id: int | None = None,
) -> tuple[dict, datetime, dict[int, list[dict]], float, float]:
    """规划单任务路线，并返回路线、完成时间、预约表、距离和等待时间。"""
    start_node = start_node_id if start_node_id is not None else agv.current_node_id
    to_pickup = router.path(start_node, task.pickup_node_id)
    to_dropoff = router.path(task.pickup_node_id, task.dropoff_node_id)
    path = _join_paths(to_pickup, to_dropoff)
    speed = max(agv.speed, 0.1)
    cursor = base_time
    current_node = path.nodes[0]
    timeline = []
    waits = []
    legs = []
    updated_reservations = copy.deepcopy(reservations)

    start_wait = _resolve_node_wait(
        updated_reservations, current_node, cursor, agv.id, task.id
    )
    if start_wait > 0:
        waits.append({
            "node_id": current_node,
            "seconds": round(start_wait, 2),
            "reason": "始发避碰等待",
        })
        cursor += timedelta(seconds=start_wait)
    _reserve_node(
        updated_reservations,
        current_node,
        cursor,
        cursor + timedelta(seconds=SAFETY_GAP_SECONDS),
        agv.id,
        task.id,
    )
    timeline.append({
        "node_id": current_node,
        "arrival_seconds": 0.0,
        "departure_seconds": round(start_wait + SAFETY_GAP_SECONDS, 2),
        "wait_seconds": round(start_wait, 2),
    })

    elapsed = start_wait + SAFETY_GAP_SECONDS
    for next_node in path.nodes[1:]:
        edge_distance = _segment_distance(router.graph, current_node, next_node)
        edge_seconds = edge_distance / speed
        arrival = cursor + timedelta(seconds=edge_seconds)
        wait_seconds = _resolve_node_wait(
            updated_reservations, next_node, arrival, agv.id, task.id
        )
        if wait_seconds > 0:
            waits.append({
                "node_id": next_node,
                "seconds": round(wait_seconds, 2),
                "reason": "避碰等待",
            })
            arrival += timedelta(seconds=wait_seconds)
            elapsed += wait_seconds

        service_seconds = 0.0
        if next_node == task.pickup_node_id and next_node != task.dropoff_node_id:
            service_seconds = LOADING_SECONDS
        if next_node == task.dropoff_node_id:
            service_seconds = max(service_seconds, UNLOADING_SECONDS)

        departure = arrival + timedelta(seconds=service_seconds + SAFETY_GAP_SECONDS)
        _reserve_node(
            updated_reservations, next_node, arrival, departure, agv.id, task.id
        )
        elapsed += edge_seconds + service_seconds
        timeline.append({
            "node_id": next_node,
            "arrival_seconds": round(elapsed, 2),
            "departure_seconds": round(elapsed + SAFETY_GAP_SECONDS, 2),
            "wait_seconds": round(wait_seconds, 2),
        })
        legs.append({
            "from_node": current_node,
            "to_node": next_node,
            "distance": round(edge_distance, 3),
            "seconds": round(edge_seconds + wait_seconds, 2),
        })
        cursor = departure
        current_node = next_node

    route = {
        "nodes": path.nodes,
        "legs": legs,
        "timeline": timeline,
        "waits": waits,
        "pickup_node": task.pickup_node_id,
        "dropoff_node": task.dropoff_node_id,
        "start_node": start_node,
    }
    return route, cursor, updated_reservations, path.distance, sum(
        item["seconds"] for item in waits
    )

def _is_agv_compatible(agv: AGV, task: TransportTask) -> bool:
    return (
        agv.status == AGV.Status.IDLE
        and agv.battery_percent >= MIN_BATTERY_PERCENT
        and agv.payload_capacity >= task.cargo_weight
    )


def evaluate_solution(
    tasks: dict[int, TransportTask],
    agvs: list[AGV],
    orders: dict[int, list[int]],
    router: GraphRouter,
    now: datetime,
    weights: dict[str, float] | None = None,
    allow_partial: bool = False,
) -> ScheduleEvaluation:
    """完整评估任务分配、执行顺序、电池约束和多车时间窗冲突。"""
    weights = weights or {}
    agv_weight = weights.get("agv_weight", DEFAULT_AGV_WEIGHT)
    wait_weight = weights.get("wait_weight", DEFAULT_WAIT_WEIGHT)
    distance_weight = weights.get("distance_weight", DEFAULT_DISTANCE_WEIGHT)
    priority_weight = weights.get("priority_weight", DEFAULT_PRIORITY_WEIGHT)
    tardiness_weight = weights.get("tardiness_weight", DEFAULT_TARDINESS_WEIGHT)
    enforce_deadlines = bool(weights.get("enforce_deadlines", False))

    agv_map = {agv.id: agv for agv in agvs}
    reservations: dict[int, list[dict]] = {}
    plans: dict[int, TaskPlan] = {}
    agv_summary: dict[int, dict] = {}
    assignments: dict[int, int] = {}
    flattened = []

    for agv_id in sorted(orders):
        sequence = orders.get(agv_id, [])
        if not sequence:
            continue
        agv = agv_map.get(agv_id)
        if agv is None:
            return ScheduleEvaluation(False, message=f"AGV {agv_id} 不存在。")

        current_node = agv.current_node_id
        cursor = now
        agv_distance = 0.0
        agv_wait = 0.0
        agv_release_wait = 0.0
        agv_plans: list[int] = []
        battery_remaining = agv.battery_percent

        for sequence_index, task_id in enumerate(sequence, start=1):
            task = tasks.get(task_id)
            if task is None:
                return ScheduleEvaluation(False, message=f"任务 {task_id} 不存在。")
            if not _is_agv_compatible(agv, task):
                return ScheduleEvaluation(
                    False, message=f"{agv.code} 状态、电量或载重不满足 {task.task_no}。"
                )
            release_time = task.release_at
            planned_start = max(cursor, release_time) if release_time else cursor
            release_wait = max(0.0, (planned_start - cursor).total_seconds())
            try:
                route, finish, reservations, distance, wait_seconds = _plan_task_route(
                    agv, task, router, planned_start, reservations, current_node
                )
            except SchedulingError as exc:
                return ScheduleEvaluation(False, message=str(exc))

            battery_remaining -= distance * BATTERY_DROP_PER_METER
            if battery_remaining < MIN_BATTERY_PERCENT:
                return ScheduleEvaluation(
                    False, message=f"{agv.code} 执行该任务序列后电量不足。"
                )

            tardiness = (
                max(0.0, (finish - task.due_at).total_seconds())
                if task.due_at
                else 0.0
            )
            plans[task_id] = TaskPlan(
                task_id=task.id,
                task_no=task.task_no,
                agv_id=agv.id,
                agv_code=agv.code,
                sequence_number=sequence_index,
                start_time=planned_start,
                end_time=finish,
                route=route,
                distance=round(distance, 3),
                wait_seconds=round(wait_seconds, 3),
                release_wait_seconds=round(release_wait, 3),
                duration_seconds=round((finish - planned_start).total_seconds(), 3),
                release_time=release_time,
                due_time=task.due_at,
                tardiness_seconds=round(tardiness, 3),
                is_late=tardiness > 0,
            )
            assignments[task_id] = agv.id
            flattened.append(task_id)
            agv_plans.append(task_id)
            agv_distance += distance
            agv_wait += wait_seconds
            agv_release_wait += release_wait
            current_node = task.dropoff_node_id
            cursor = finish

        agv_summary[agv.id] = {
            "agv_id": agv.id,
            "agv_code": agv.code,
            "task_ids": agv_plans,
            "start_time": now,
            "end_time": cursor,
            "distance": round(agv_distance, 3),
            "wait_seconds": round(agv_wait, 3),
            "release_wait_seconds": round(agv_release_wait, 3),
            "battery_remaining": round(battery_remaining, 2),
        }

    if len(flattened) != len(set(flattened)):
        return ScheduleEvaluation(False, message="存在重复分配的任务。")
    if not allow_partial and set(flattened) != set(tasks):
        return ScheduleEvaluation(False, message="存在未分配任务。")

    finish_times = [plan.end_time for plan in plans.values()]
    makespan = max((item - now).total_seconds() for item in finish_times)
    total_completion = sum((plan.end_time - now).total_seconds() for plan in plans.values())
    total_distance = sum(plan.distance for plan in plans.values())
    total_wait = sum(plan.wait_seconds for plan in plans.values())
    total_release_wait = sum(plan.release_wait_seconds for plan in plans.values())
    total_tardiness = sum(plan.tardiness_seconds for plan in plans.values())
    late_task_count = sum(1 for plan in plans.values() if plan.is_late)
    on_time_rate = (
        round((len(plans) - late_task_count) / len(plans) * 100, 2) if plans else 100.0
    )
    used_agvs = len(agv_summary)
    weighted_completion = sum(
        (plan.end_time - now).total_seconds() * tasks[task_id].priority
        for task_id, plan in plans.items()
    )
    objective = (
        makespan
        + agv_weight * used_agvs
        + wait_weight * total_wait
        + distance_weight * total_distance
        + priority_weight * weighted_completion
        + tardiness_weight * total_tardiness
    )
    if enforce_deadlines and late_task_count and not allow_partial:
        late_tasks = [plan.task_no for plan in plans.values() if plan.is_late]
        preview = ", ".join(late_tasks[:5])
        suffix = "..." if len(late_tasks) > 5 else ""
        return ScheduleEvaluation(
            False,
            message=f"硬交期约束不满足，{late_task_count} 个任务将拖期：{preview}{suffix}",
        )
    return ScheduleEvaluation(
        feasible=True,
        objective=round(objective, 4),
        makespan_seconds=round(makespan, 3),
        total_completion_seconds=round(total_completion, 3),
        total_distance=round(total_distance, 3),
        total_wait_seconds=round(total_wait, 3),
        total_release_wait_seconds=round(total_release_wait, 3),
        total_tardiness_seconds=round(total_tardiness, 3),
        late_task_count=late_task_count,
        on_time_rate=on_time_rate,
        used_agvs=used_agvs,
        assignments=assignments,
        orders={agv_id: list(order) for agv_id, order in orders.items() if order},
        plans=plans,
        agv_summary=agv_summary,
    )

def _first_task_distance(router: GraphRouter, start_node: int, task: TransportTask) -> float:
    return (
        router.path(start_node, task.pickup_node_id).distance
        + router.path(task.pickup_node_id, task.dropoff_node_id).distance
    )


def _transition_distance(router: GraphRouter, first: TransportTask, second: TransportTask) -> float:
    return (
        router.path(first.dropoff_node_id, second.pickup_node_id).distance
        + router.path(second.pickup_node_id, second.dropoff_node_id).distance
    )


def _sequence_distance(
    router: GraphRouter, agv: AGV, tasks: list[TransportTask], order: list[int]
) -> float:
    if not order:
        return 0.0
    task_map = {task.id: task for task in tasks}
    total = _first_task_distance(router, agv.current_node_id, task_map[order[0]])
    for left, right in zip(order, order[1:]):
        total += _transition_distance(router, task_map[left], task_map[right])
    return total


def _two_opt_single_order(
    router: GraphRouter, agv: AGV, tasks: list[TransportTask], order: list[int]
) -> list[int]:
    improved = True
    best_order = list(order)
    while improved:
        improved = False
        for start in range(1, len(best_order) - 1):
            for end in range(start + 1, len(best_order)):
                candidate = (
                    best_order[:start]
                    + list(reversed(best_order[start:end + 1]))
                    + best_order[end + 1:]
                )
                if _sequence_distance(router, agv, tasks, candidate) + 1e-9 < _sequence_distance(
                    router, agv, tasks, best_order
                ):
                    best_order = candidate
                    improved = True
    return best_order

def optimize_single_order(
    agv: AGV, tasks: list[TransportTask], router: GraphRouter
) -> list[int]:
    """单台多任务顺序优化：小规模精确 DP（可选），大规模最近邻 + 2-opt。

    DP 只在 ``len(tasks) <= EXACT_DP_MAX_TASKS`` 时作为“精确性对照”启用，
    超出则走启发式；主链路（多 AGV 调度）用的是最优插入 + VND，与此无关。
    """
    if len(tasks) <= 1:
        return [task.id for task in tasks]
    task_map = {task.id: task for task in tasks}
    task_ids = [task.id for task in tasks]

    if len(tasks) <= EXACT_DP_MAX_TASKS:
        dp: dict[tuple[int, int], tuple[float, tuple[int, ...]]] = {}
        for index, task in enumerate(tasks):
            distance = _first_task_distance(router, agv.current_node_id, task)
            dp[(1 << index, index)] = (distance, (index,))

        for mask in range(1, 1 << len(tasks)):
            for last_index in range(len(tasks)):
                state = (mask, last_index)
                if state not in dp or not (mask & (1 << last_index)):
                    continue
                current_cost, current_path = dp[state]
                for next_index, next_task in enumerate(tasks):
                    if mask & (1 << next_index):
                        continue
                    next_mask = mask | (1 << next_index)
                    next_cost = current_cost + _transition_distance(
                        router, tasks[last_index], next_task
                    )
                    next_state = (next_mask, next_index)
                    existing = dp.get(next_state)
                    if existing is None or next_cost < existing[0] - 1e-9:
                        dp[next_state] = (next_cost, current_path + (next_index,))

        full_mask = (1 << len(tasks)) - 1
        _, best_indices = min(
            (dp[(full_mask, index)] for index in range(len(tasks))),
            key=lambda item: item[0],
        )
        return [task_ids[index] for index in best_indices]

    remaining = list(task_ids)
    order = []
    current_node = agv.current_node_id
    while remaining:
        selected = min(
            remaining,
            key=lambda task_id: _first_task_distance(
                router, current_node, task_map[task_id]
            ),
        )
        order.append(selected)
        current_node = task_map[selected].dropoff_node_id
        remaining.remove(selected)
    return _two_opt_single_order(router, agv, tasks, order)

def _ordered_tasks(tasks: Iterable[TransportTask]) -> list[TransportTask]:
    """优先处理交期更早的任务，其次按业务优先级和创建时间排序。"""
    return sorted(
        tasks,
        key=lambda item: (
            item.due_at is None,
            item.due_at or item.created_at,
            -item.priority,
            item.created_at,
            item.id,
        ),
    )


def build_baseline_solution(
    tasks: list[TransportTask],
    agvs: list[AGV],
    router: GraphRouter,
    now: datetime,
    weights: dict[str, float] | None = None,
) -> ScheduleEvaluation:
    """基准算法：按优先级顺序选择“最早完成”的 AGV 并追加任务。"""
    orders = {agv.id: [] for agv in agvs}
    task_map = {task.id: task for task in tasks}
    for task in _ordered_tasks(tasks):
        best = None
        for agv in agvs:
            if agv.payload_capacity < task.cargo_weight:
                continue
            candidate = {agv_id: list(order) for agv_id, order in orders.items()}
            candidate[agv.id].append(task.id)
            evaluation = evaluate_solution(
                task_map, agvs, candidate, router, now, weights, allow_partial=True
            )
            if not evaluation.feasible:
                continue
            finish = evaluation.plans[task.id].end_time
            score = finish.timestamp()
            if best is None or score < best["score"]:
                best = {"score": score, "orders": candidate}
        if best is None:
            return ScheduleEvaluation(False, message=f"基准算法无法分配 {task.task_no}。")
        orders = best["orders"]
    return evaluate_solution(task_map, agvs, orders, router, now, weights)

def build_insertion_solution(
    tasks: list[TransportTask],
    agvs: list[AGV],
    router: GraphRouter,
    now: datetime,
    weights: dict[str, float] | None = None,
    task_order: list[TransportTask] | None = None,
) -> ScheduleEvaluation:
    """最优插入初始化：对每个任务尝试所有 AGV、所有插入位置。"""
    orders = {agv.id: [] for agv in agvs}
    task_map = {task.id: task for task in tasks}
    current_evaluation = None

    ordered_tasks = task_order if task_order is not None else _ordered_tasks(tasks)
    for task in ordered_tasks:
        best = None
        for agv in agvs:
            if agv.payload_capacity < task.cargo_weight:
                continue
            base_order = list(orders[agv.id])
            for position in range(len(base_order) + 1):
                candidate = {agv_id: list(order) for agv_id, order in orders.items()}
                candidate[agv.id].insert(position, task.id)
                evaluation = evaluate_solution(
                task_map, agvs, candidate, router, now, weights, allow_partial=True
            )
                if not evaluation.feasible:
                    continue
                if best is None or evaluation.objective < best.objective:
                    best = evaluation

        if best is None:
            return ScheduleEvaluation(False, message=f"没有可行方案分配 {task.task_no}。")
        orders = {agv.id: list(best.orders.get(agv.id, [])) for agv in agvs}
        current_evaluation = best

    return current_evaluation or ScheduleEvaluation(False, message="没有待调度任务。")

def _build_relocate_moves(
    orders: dict[int, list[int]], task_ids: list[int], agv_ids: list[int]
) -> list[dict[int, list[int]]]:
    candidates = []
    for source_agv in agv_ids:
        source_order = orders.get(source_agv, [])
        for source_index, task_id in enumerate(source_order):
            for target_agv in agv_ids:
                if target_agv == source_agv:
                    base_target = list(source_order)
                    base_target.pop(source_index)
                else:
                    base_target = list(orders.get(target_agv, []))
                for position in range(len(base_target) + 1):
                    if target_agv == source_agv and position == source_index:
                        continue
                    candidate = {agv_id: list(orders.get(agv_id, [])) for agv_id in agv_ids}
                    if target_agv == source_agv:
                        candidate[target_agv] = list(base_target)
                        candidate[target_agv].insert(position, task_id)
                    else:
                        candidate[source_agv].remove(task_id)
                        candidate[target_agv].insert(position, task_id)
                    candidates.append(candidate)
    return candidates


def _clone_orders(orders: dict[int, list[int]], agv_ids: list[int]) -> dict[int, list[int]]:
    """复制一份方案，避免候选解修改到当前解。"""
    return {agv_id: list(orders.get(agv_id, [])) for agv_id in agv_ids}


def _build_swap_moves(
    orders: dict[int, list[int]], agv_ids: list[int]
) -> list[dict[int, list[int]]]:
    """邻域 swap：交换两个任务的位置（同一台车内交换，或跨 AGV 交换）。"""
    candidates: list[dict[int, list[int]]] = []
    for source_index, source_agv in enumerate(agv_ids):
        source_order = orders.get(source_agv, [])
        for first_position, first_task in enumerate(source_order):
            for target_agv in agv_ids[source_index:]:
                target_order = orders.get(target_agv, [])
                for second_position, second_task in enumerate(target_order):
                    if target_agv == source_agv and second_position <= first_position:
                        continue
                    candidate = _clone_orders(orders, agv_ids)
                    candidate[source_agv][first_position] = second_task
                    candidate[target_agv][second_position] = first_task
                    candidates.append(candidate)
    return candidates


def _build_or_opt_moves(
    orders: dict[int, list[int]], agv_ids: list[int], max_segment: int = 3
) -> list[dict[int, list[int]]]:
    """邻域 or-opt：把 2~max_segment 个连续任务整体搬到本车其他位置或其他 AGV。"""
    candidates: list[dict[int, list[int]]] = []
    for source_agv in agv_ids:
        source_order = list(orders.get(source_agv, []))
        for length in range(2, min(max_segment, len(source_order)) + 1):
            for start in range(len(source_order) - length + 1):
                segment = source_order[start : start + length]
                remaining = source_order[:start] + source_order[start + length :]
                for target_agv in agv_ids:
                    base = (
                        remaining
                        if target_agv == source_agv
                        else list(orders.get(target_agv, []))
                    )
                    for position in range(len(base) + 1):
                        if target_agv == source_agv and position == start:
                            continue
                        candidate = _clone_orders(orders, agv_ids)
                        candidate[source_agv] = list(remaining)
                        candidate[target_agv][position:position] = segment
                        candidates.append(candidate)
    return candidates


def _build_two_opt_moves(
    orders: dict[int, list[int]], agv_ids: list[int]
) -> list[dict[int, list[int]]]:
    """邻域 2-opt：反转同一台车内一段连续任务的顺序（消除路线交叉）。"""
    candidates: list[dict[int, list[int]]] = []
    for agv_id in agv_ids:
        order = list(orders.get(agv_id, []))
        for start in range(len(order) - 1):
            for end in range(start + 2, len(order) + 1):
                candidate = _clone_orders(orders, agv_ids)
                candidate[agv_id][start:end] = reversed(candidate[agv_id][start:end])
                candidates.append(candidate)
    return candidates


def improve_solution_vns(
    initial: ScheduleEvaluation,
    tasks: dict[int, TransportTask],
    agvs: list[AGV],
    router: GraphRouter,
    now: datetime,
    weights: dict[str, float] | None = None,
    max_rounds: int = 50,
    max_neighbors: int = 120,
    time_budget: float = 3.0,
) -> tuple[ScheduleEvaluation, int]:
    """变邻域下降（VND）：交替使用 relocate / swap / or-opt / 2-opt 四种邻域。

    - 任一邻域找到改进（首次改进即接受）就回到第一个邻域重新搜索；
    - 四个邻域都无法改进时结束；
    - 邻居数超过 max_neighbors 时按固定种子随机采样，保证结果可复现；
    - ``time_budget`` 为墙钟时间上限（秒）：到点立即返回当前最优解，
      保证演示与接口响应不被大规模算例拖死。
    """
    current = initial
    iterations = 0
    rng = random.Random(20260928)
    task_ids = list(tasks)
    agv_ids = [agv.id for agv in agvs]
    # 大规模算例下只对采样子集生成邻域：控制单次 move 生成的耗时，
    # 否则 100 任务 × 13 车会产生上百万候选、一次构建就可能超过时间预算。
    active_tasks = task_ids if len(task_ids) <= 40 else rng.sample(task_ids, 40)
    active_agvs = agv_ids if len(agv_ids) <= 5 else rng.sample(agv_ids, 5)
    builders = (
        lambda orders: _build_relocate_moves(orders, active_tasks, active_agvs),
        lambda orders: _build_swap_moves(orders, active_agvs),
        lambda orders: _build_or_opt_moves(orders, active_agvs),
        lambda orders: _build_two_opt_moves(orders, active_agvs),
    )

    rounds = 0
    stalled = 0
    neighborhood = 0
    deadline = time.monotonic() + max(0.0, float(time_budget))
    while rounds < max_rounds and stalled < len(builders):
        if time.monotonic() > deadline:
            break
        rounds += 1
        moves = builders[neighborhood](current.orders)
        if len(moves) > max_neighbors:
            moves = rng.sample(moves, max_neighbors)
        improved = False
        for candidate in moves:
            if time.monotonic() > deadline:
                break
            iterations += 1
            evaluation = evaluate_solution(tasks, agvs, candidate, router, now, weights)
            if evaluation.feasible and evaluation.objective < current.objective - 1e-7:
                current = evaluation
                improved = True
                break
        if improved:
            neighborhood = 0
            stalled = 0
        else:
            neighborhood = (neighborhood + 1) % len(builders)
            stalled += 1
    return current, iterations

def optimize_single_solution(
    tasks: list[TransportTask],
    agvs: list[AGV],
    router: GraphRouter,
    now: datetime,
    weights: dict[str, float] | None = None,
) -> tuple[ScheduleEvaluation, ScheduleEvaluation, int]:
    """同时选择单台 AGV 并优化该车的多任务执行顺序。"""
    task_map = {task.id: task for task in tasks}
    weights = dict(weights or {})
    weights["agv_weight"] = 0
    best = None
    best_baseline = ScheduleEvaluation(False)
    last_message = ""
    iterations = 0

    for agv in agvs:
        if any(not _is_agv_compatible(agv, task) for task in tasks):
            continue
        optimized_order = optimize_single_order(agv, tasks, router)
        evaluation = evaluate_solution(
            task_map, [agv], {agv.id: optimized_order}, router, now, weights
        )
        if not evaluation.feasible:
            last_message = evaluation.message or last_message
            continue
        selection_score = evaluation.objective + (100 - agv.battery_percent) * 0.25
        iterations += max(1, len(tasks) * len(tasks))
        if best is None or selection_score < best["score"]:
            baseline_order = [task.id for task in tasks]
            baseline = evaluate_solution(
                task_map, [agv], {agv.id: baseline_order}, router, now, weights
            )
            best = {"score": selection_score, "evaluation": evaluation}
            best_baseline = baseline

    if best is None:
        return (
            ScheduleEvaluation(False, message=last_message or "没有可行的单台 AGV 调度方案。"),
            ScheduleEvaluation(False),
            iterations,
        )
    return best["evaluation"], best_baseline, iterations


def optimize_multi_solution(
    tasks: list[TransportTask],
    agvs: list[AGV],
    router: GraphRouter,
    now: datetime,
    weights: dict[str, float] | None = None,
) -> tuple[ScheduleEvaluation, ScheduleEvaluation, int]:
    """最优插入初始化 + 变邻域下降（relocate/swap/or-opt/2-opt）的多 AGV 联合优化。"""
    task_map = {task.id: task for task in tasks}
    baseline = build_baseline_solution(tasks, agvs, router, now, weights)
    initial = build_insertion_solution(tasks, agvs, router, now, weights)
    initialization_evaluations = 0
    if len(tasks) <= 8:
        rng = random.Random(20260928)
        for _ in range(60):
            shuffled = list(tasks)
            rng.shuffle(shuffled)
            candidate = build_insertion_solution(
                tasks, agvs, router, now, weights, task_order=shuffled
            )
            initialization_evaluations += max(1, len(tasks) * len(tasks) * 2)
            if candidate.feasible and candidate.objective < initial.objective:
                initial = candidate
    if not initial.feasible:
        return ScheduleEvaluation(False, message=initial.message), baseline, 0
    optimized, iterations = improve_solution_vns(
        initial, task_map, agvs, router, now, weights
    )
    iterations += initialization_evaluations
    if baseline.feasible and baseline.objective < optimized.objective:
        return baseline, baseline, iterations
    return optimized, baseline, iterations

def _evaluation_payload(evaluation: ScheduleEvaluation) -> dict:
    if not evaluation.feasible:
        return {"feasible": False, "message": evaluation.message}
    return {
        "feasible": True,
        "objective": evaluation.objective,
        "makespan_seconds": evaluation.makespan_seconds,
        "total_completion_seconds": evaluation.total_completion_seconds,
        "total_distance": evaluation.total_distance,
        "total_wait_seconds": evaluation.total_wait_seconds,
        "total_release_wait_seconds": evaluation.total_release_wait_seconds,
        "total_tardiness_seconds": evaluation.total_tardiness_seconds,
        "late_task_count": evaluation.late_task_count,
        "on_time_rate": evaluation.on_time_rate,
        "used_agvs": evaluation.used_agvs,
        "agv_summary": [
            {
                **summary,
                "start_time": summary["start_time"].isoformat(),
                "end_time": summary["end_time"].isoformat(),
            }
            for summary in evaluation.agv_summary.values()
        ],
        "tasks": [
            {
                "task_id": plan.task_id,
                "task_no": plan.task_no,
                "agv_id": plan.agv_id,
                "agv_code": plan.agv_code,
                "sequence_number": plan.sequence_number,
                "start_time": plan.start_time.isoformat(),
                "end_time": plan.end_time.isoformat(),
                "duration_seconds": plan.duration_seconds,
                "distance": plan.distance,
                "wait_seconds": plan.wait_seconds,
                "release_wait_seconds": plan.release_wait_seconds,
                "release_time": plan.release_time.isoformat() if plan.release_time else None,
                "due_time": plan.due_time.isoformat() if plan.due_time else None,
                "tardiness_seconds": plan.tardiness_seconds,
                "is_late": plan.is_late,
            }
            for plan in evaluation.plans.values()
        ],
    }


def _persist_schedule(
    evaluation: ScheduleEvaluation,
    baseline: ScheduleEvaluation,
    tasks: list[TransportTask],
    algorithm: str,
    objective_name: str,
    iteration_count: int,
    production_plan: ProductionPlan | None = None,
) -> ScheduleRun:
    improvement = 0.0
    baseline_makespan = baseline.makespan_seconds if baseline.feasible else 0.0
    if baseline.feasible and baseline.objective > 0:
        improvement = round(
            max(0.0, (baseline.objective - evaluation.objective) / baseline.objective * 100),
            2,
        )

    assignments = {
        str(summary["agv_id"]): {
            "agv_code": summary["agv_code"],
            "task_ids": summary["task_ids"],
            "end_time": summary["end_time"].isoformat(),
            "distance": summary["distance"],
            "wait_seconds": summary["wait_seconds"],
            "release_wait_seconds": summary["release_wait_seconds"],
            "battery_remaining": summary["battery_remaining"],
        }
        for summary in evaluation.agv_summary.values()
    }
    run = ScheduleRun.objects.create(
        production_plan=production_plan,
        algorithm=algorithm,
        objective_name=objective_name,
        task_count=len(tasks),
        agv_count=evaluation.used_agvs,
        makespan_seconds=evaluation.makespan_seconds,
        total_distance=evaluation.total_distance,
        total_wait_seconds=evaluation.total_wait_seconds,
        total_tardiness_seconds=evaluation.total_tardiness_seconds,
        late_task_count=evaluation.late_task_count,
        on_time_rate=evaluation.on_time_rate,
        iteration_count=iteration_count,
        baseline_makespan_seconds=baseline_makespan,
        improvement_percent=improvement,
        assignments=assignments,
        metrics={
            "objective": evaluation.objective,
            "total_completion_seconds": evaluation.total_completion_seconds,
            "total_release_wait_seconds": evaluation.total_release_wait_seconds,
            "total_tardiness_seconds": evaluation.total_tardiness_seconds,
            "late_task_count": evaluation.late_task_count,
            "on_time_rate": evaluation.on_time_rate,
            "baseline_objective": baseline.objective if baseline.feasible else None,
            "baseline_makespan_seconds": baseline_makespan if baseline.feasible else None,
            "algorithm": algorithm,
        },
    )

    active_agv_ids = set()
    from django.db.models import Max

    task_ids = [task.id for task in tasks]
    work_order_ids = {
        task.work_order_id for task in tasks if task.work_order_id is not None
    }
    plan_ids = {
        task.production_plan_id
        for task in tasks
        if task.production_plan_id is not None and task.work_order_id is None
    }
    offsets = {}
    for work_order_id in work_order_ids:
        maximum = (
            TransportTask.objects.filter(work_order_id=work_order_id)
            .exclude(id__in=task_ids)
            .aggregate(value=Max("dispatch_order"))["value"]
            or 0
        )
        offsets[("work_order", work_order_id)] = maximum
    for plan_id in plan_ids:
        maximum = (
            TransportTask.objects.filter(production_plan_id=plan_id)
            .exclude(id__in=task_ids)
            .aggregate(value=Max("dispatch_order"))["value"]
            or 0
        )
        offsets[("plan", plan_id)] = maximum

    counters = dict(offsets)
    dispatch_orders = {}
    task_map = {task.id: task for task in tasks}
    for task_id in sorted(
        evaluation.plans,
        key=lambda item: (
            evaluation.plans[item].start_time,
            evaluation.plans[item].agv_code,
            evaluation.plans[item].sequence_number,
            item,
        ),
    ):
        task = task_map[task_id]
        scope = (
            ("work_order", task.work_order_id)
            if task.work_order_id is not None
            else ("plan", task.production_plan_id)
        )
        counters[scope] = counters.get(scope, 0) + 1
        dispatch_orders[task_id] = counters[scope]
    for task in tasks:
        plan = evaluation.plans[task.id]
        task.assigned_agv_id = plan.agv_id
        task.schedule_run = run
        task.sequence_number = plan.sequence_number
        task.dispatch_order = dispatch_orders[task.id]
        task.planned_wait_seconds = plan.wait_seconds
        task.optimization_details = {
            "objective": evaluation.objective,
            "makespan_seconds": evaluation.makespan_seconds,
            "baseline_makespan_seconds": baseline_makespan,
            "improvement_percent": improvement,
            "algorithm": algorithm,
            "total_tardiness_seconds": evaluation.total_tardiness_seconds,
            "late_task_count": evaluation.late_task_count,
            "on_time_rate": evaluation.on_time_rate,
        }
        task.status = TransportTask.Status.ASSIGNED
        task.route = plan.route
        task.total_distance = plan.distance
        task.estimated_duration = plan.duration_seconds
        task.scheduled_start = plan.start_time
        task.scheduled_end = plan.end_time
        task.started_at = None
        task.completed_at = None
        task.notes = (
            f"{run.get_algorithm_display()}：{plan.agv_code} 第 {plan.sequence_number} 项"
            + (f"，避碰等待 {plan.wait_seconds:.1f}s" if plan.wait_seconds > 0 else "")
            + (f"，拖期 {plan.tardiness_seconds:.1f}s" if plan.is_late else "")
        )
        task.save(
            update_fields=[
                "assigned_agv", "schedule_run", "sequence_number", "dispatch_order", "planned_wait_seconds",
                "optimization_details", "status", "route", "total_distance",
                "estimated_duration", "scheduled_start", "scheduled_end", "started_at",
                "completed_at", "notes", "updated_at",
            ]
        )
        DispatchRecord.objects.create(
            task=task,
            agv_id=plan.agv_id,
            algorithm=(
                DispatchRecord.Algorithm.SINGLE
                if algorithm == ScheduleRun.Algorithm.SINGLE_SEQUENCE
                else DispatchRecord.Algorithm.BATCH
            ),
            success=True,
            message=task.notes,
            route=plan.route,
            distance=plan.distance,
            estimated_duration=plan.duration_seconds,
        )
        _sync_order_from_task(
            task,
            description=(
                f"已分配执行车辆，计划 "
                f"{timezone.localtime(plan.start_time):%m-%d %H:%M} 开始运输。"
            ),
        )
        active_agv_ids.add(plan.agv_id)

    AGV.objects.filter(id__in=active_agv_ids).update(status=AGV.Status.BUSY)
    if production_plan is not None:
        ProductionPlan.objects.filter(pk=production_plan.pk).update(
            status=ProductionPlan.Status.SCHEDULED
        )
    return run

def dispatch_single_sequence(
    task_ids: list[int],
    agv_id: int | None = None,
    weights: dict[str, float] | None = None,
    production_plan_id: int | None = None,
    strict_deadlines: bool = False,
) -> dict:
    """单台 AGV 多任务调度：选择 AGV 并优化所有任务执行顺序。"""
    if not task_ids:
        raise SchedulingError("至少选择一个任务。")
    if len(set(task_ids)) != len(task_ids):
        raise SchedulingError("任务列表中不能包含重复任务。")
    with transaction.atomic():
        production_plan = None
        if production_plan_id is not None:
            production_plan = ProductionPlan.objects.select_for_update().filter(
                pk=production_plan_id
            ).first()
            if production_plan is None:
                raise SchedulingError("生产计划不存在。")
        tasks_by_id = {
            task.id: task
            for task in TransportTask.objects.select_for_update()
            .select_related("pickup_node", "dropoff_node")
            .filter(id__in=task_ids)
        }
        missing = [task_id for task_id in task_ids if task_id not in tasks_by_id]
        if missing:
            raise SchedulingError(f"任务不存在：{missing}")
        tasks = [tasks_by_id[task_id] for task_id in task_ids]
        invalid = [task.task_no for task in tasks if task.status != TransportTask.Status.PENDING]
        if invalid:
            raise SchedulingError(f"仅待调度任务可参与优化：{', '.join(invalid)}")
        if production_plan is not None and any(
            task.production_plan_id != production_plan.id for task in tasks
        ):
            raise SchedulingError("所选任务不属于指定生产计划。")

        agvs_query = AGV.objects.select_for_update().select_related("current_node").filter(
            status=AGV.Status.IDLE
        )
        if agv_id is not None:
            agvs_query = agvs_query.filter(id=agv_id)
        agvs = list(agvs_query.order_by("code"))
        if not agvs:
            raise SchedulingError("没有可用的空闲 AGV。")

        now = timezone.now()
        router = GraphRouter(build_graph())
        weights = dict(weights or {})
        if strict_deadlines:
            weights["enforce_deadlines"] = True
        evaluation, baseline, iterations = optimize_single_solution(
            tasks, agvs, router, now, weights
        )
        if not evaluation.feasible:
            raise SchedulingError(evaluation.message or "单台 AGV 顺序优化失败。")
        if strict_deadlines and evaluation.late_task_count:
            raise SchedulingError(
                f"硬交期约束不满足，{evaluation.late_task_count} 个任务将拖期。"
            )
        run = _persist_schedule(
            evaluation=evaluation,
            baseline=baseline,
            tasks=tasks,
            algorithm=ScheduleRun.Algorithm.SINGLE_SEQUENCE,
            objective_name="最小化完工时间、路径长度与交期拖期",
            iteration_count=iterations,
            production_plan=production_plan,
        )
        from Operations.services import record_task_event

        for task in tasks:
            record_task_event(
                task,
                "task.scheduled",
                f"运输任务 {task.task_no} 已完成调度分配",
            )
        agv_code = evaluation.plans[tasks[0].id].agv_code
        message = (
            f"单台 AGV 顺序优化完成：{agv_code} 执行 {len(tasks)} 个任务，"
            f"完工时间 {evaluation.makespan_seconds:.1f}s，"
            f"相比输入顺序改进 {run.improvement_percent:.1f}%"
        )
        return {
            "message": message,
            "algorithm": run.algorithm,
            "run": run,
            "tasks": tasks,
            "evaluation": _evaluation_payload(evaluation),
            "baseline": _evaluation_payload(baseline),
        }


def dispatch_single(task_id: int, agv_id: int | None = None) -> TransportTask:
    """兼容旧接口：单个任务的单台 AGV 调度。"""
    result = dispatch_single_sequence([task_id], agv_id)
    return result["tasks"][0]

def dispatch_batch(
    task_ids: list[int] | None = None,
    limit: int = 30,
    weights: dict[str, float] | None = None,
    production_plan_id: int | None = None,
    strict_deadlines: bool = False,
) -> dict:
    """多台 AGV 联合优化：任务分配、车辆内顺序和避碰时间窗统一求解。"""
    if task_ids and len(set(task_ids)) != len(task_ids):
        raise SchedulingError("任务列表中不能包含重复任务。")
    with transaction.atomic():
        production_plan = None
        if production_plan_id is not None:
            production_plan = ProductionPlan.objects.select_for_update().filter(
                pk=production_plan_id
            ).first()
            if production_plan is None:
                raise SchedulingError("生产计划不存在。")
        query = TransportTask.objects.select_for_update().select_related(
            "pickup_node", "dropoff_node"
        ).filter(status=TransportTask.Status.PENDING)
        if production_plan is not None:
            query = query.filter(production_plan=production_plan)
        if task_ids:
            query = query.filter(id__in=task_ids)
        tasks = list(query.order_by("-priority", "created_at")[:limit])
        if not tasks:
            raise SchedulingError("没有可参与批量调度的待处理任务。")

        agvs = list(
            AGV.objects.select_for_update()
            .select_related("current_node")
            .filter(status=AGV.Status.IDLE)
            .order_by("code")
        )
        if not agvs:
            raise SchedulingError("当前没有空闲 AGV。")

        now = timezone.now()
        router = GraphRouter(build_graph())
        weights = dict(weights or {})
        if strict_deadlines:
            weights["enforce_deadlines"] = True
        evaluation, baseline, iterations = optimize_multi_solution(
            tasks, agvs, router, now, weights
        )
        if not evaluation.feasible:
            raise SchedulingError(evaluation.message or "多台 AGV 联合优化失败。")
        if strict_deadlines and evaluation.late_task_count:
            raise SchedulingError(
                f"硬交期约束不满足，{evaluation.late_task_count} 个任务将拖期。"
            )

        run = _persist_schedule(
            evaluation=evaluation,
            baseline=baseline,
            tasks=tasks,
            algorithm=ScheduleRun.Algorithm.MULTI_VNS,
            objective_name="最小化完工时间、AGV 数量、优先级、避碰等待与交期拖期",
            iteration_count=iterations,
            production_plan=production_plan,
        )
        from Operations.services import record_task_event

        for task in tasks:
            record_task_event(
                task,
                "task.scheduled",
                f"运输任务 {task.task_no} 已纳入批量联合调度",
            )
        message = (
            f"多台 AGV 联合优化完成：{len(tasks)} 个任务，"
            f"使用 {evaluation.used_agvs} 台 AGV，"
            f"makespan {evaluation.makespan_seconds:.1f}s，"
            f"相比基准算法改进 {run.improvement_percent:.1f}%"
        )
        return {
            "message": message,
            "algorithm": run.algorithm,
            "run": run,
            "tasks": tasks,
            "evaluation": _evaluation_payload(evaluation),
            "baseline": _evaluation_payload(baseline),
        }

def start_task(task_id: int) -> TransportTask:
    with transaction.atomic():
        task = (
            TransportTask.objects.select_for_update()
            .select_related("assigned_agv")
            .get(pk=task_id)
        )
        if task.status != TransportTask.Status.ASSIGNED or not task.assigned_agv:
            raise SchedulingError("只有已分配任务可以开始执行。")
        if task.schedule_run_id:
            previous_pending = TransportTask.objects.filter(
                schedule_run_id=task.schedule_run_id,
                assigned_agv_id=task.assigned_agv_id,
                sequence_number__lt=task.sequence_number,
            ).exclude(status__in=[TransportTask.Status.COMPLETED, TransportTask.Status.CANCELLED])
            if previous_pending.exists():
                raise SchedulingError("存在未完成的前序任务，请按优化顺序执行。")
        now = timezone.now()
        if task.release_at and now < task.release_at:
            raise SchedulingError(
                f"任务尚未到释放时间 {timezone.localtime(task.release_at).isoformat()}。"
            )
        task.status = TransportTask.Status.IN_PROGRESS
        task.started_at = now
        task.save(update_fields=["status", "started_at", "updated_at"])
        AGV.objects.filter(pk=task.assigned_agv_id).update(status=AGV.Status.BUSY)
        _sync_order_from_task(task, description="AGV 已按调度顺序开始运输。")
        from Operations.services import sync_work_order_after_task_start

        sync_work_order_after_task_start(task)
    return task


def complete_task(task_id: int) -> TransportTask:
    with transaction.atomic():
        task = (
            TransportTask.objects.select_for_update()
            .select_related("assigned_agv")
            .get(pk=task_id)
        )
        if task.status != TransportTask.Status.IN_PROGRESS or not task.assigned_agv:
            raise SchedulingError("只有执行中的任务可以完成。")

        agv = AGV.objects.select_for_update().get(pk=task.assigned_agv_id)
        agv.current_node = task.dropoff_node
        agv.battery_percent = max(
            0.0, agv.battery_percent - task.total_distance * BATTERY_DROP_PER_METER
        )
        has_next = TransportTask.objects.filter(
            assigned_agv=agv,
            status=TransportTask.Status.ASSIGNED,
        ).exclude(pk=task.id).exists()
        agv.status = AGV.Status.BUSY if has_next else AGV.Status.IDLE
        agv.save(
            update_fields=["current_node", "battery_percent", "status", "last_heartbeat"]
        )

        task.status = TransportTask.Status.COMPLETED
        task.completed_at = timezone.now()
        task.save(update_fields=["status", "completed_at", "updated_at"])
        _sync_order_from_task(task, description="运输任务已完成，货物已送达。")
        if task.production_plan_id:
            has_active = TransportTask.objects.filter(
                production_plan_id=task.production_plan_id,
                status__in=[
                    TransportTask.Status.PENDING,
                    TransportTask.Status.ASSIGNED,
                    TransportTask.Status.IN_PROGRESS,
                ],
            ).exists()
            if not has_active:
                ProductionPlan.objects.filter(pk=task.production_plan_id).update(
                    status=ProductionPlan.Status.COMPLETED
                )
        from Operations.services import sync_work_order_after_task_complete

        sync_work_order_after_task_complete(task)
    return task


def cancel_task(task_id: int) -> TransportTask:
    with transaction.atomic():
        task = (
            TransportTask.objects.select_for_update()
            .select_related("assigned_agv")
            .get(pk=task_id)
        )
        if task.status in [TransportTask.Status.COMPLETED, TransportTask.Status.IN_PROGRESS]:
            raise SchedulingError("已完成或执行中的任务不能取消。")
        old_agv_id = task.assigned_agv_id
        task.status = TransportTask.Status.CANCELLED
        task.save(update_fields=["status", "updated_at"])
        if old_agv_id:
            has_more = TransportTask.objects.filter(
                assigned_agv_id=old_agv_id,
                status__in=[
                    TransportTask.Status.ASSIGNED,
                    TransportTask.Status.IN_PROGRESS,
                ],
            ).exists()
            if not has_more:
                AGV.objects.filter(pk=old_agv_id).update(status=AGV.Status.IDLE)
        _sync_order_from_task(task, description="订单及其运输任务已取消。")
        from Operations.services import record_task_event

        record_task_event(
            task,
            "task.cancelled",
            f"运输任务 {task.task_no} 已取消",
        )
    return task

def plan_shortest_path(
    start_node_id: int,
    end_node_id: int,
    agv_id: int | None = None,
) -> dict:
    """根据地图障碍与道路拓扑规划一条满足约束的最短路径。"""
    nodes = MapNode.objects.in_bulk([start_node_id, end_node_id])
    if start_node_id not in nodes or end_node_id not in nodes:
        raise SchedulingError("起点或终点节点不存在。")
    if start_node_id == end_node_id:
        raise SchedulingError("起点和终点不能相同。")

    agv = AGV.objects.select_related("current_node").filter(pk=agv_id).first() if agv_id else None
    if agv_id and not agv:
        raise SchedulingError("指定 AGV 不存在。")
    speed = agv.speed if agv else 1.2
    router = GraphRouter(build_graph())
    path = router.path(start_node_id, end_node_id)
    legs = []
    timeline = []
    cursor = 0.0
    timeline.append({
        "node_id": path.nodes[0],
        "arrival_seconds": 0.0,
        "departure_seconds": 0.0,
        "wait_seconds": 0.0,
    })
    for current_node, next_node in zip(path.nodes, path.nodes[1:]):
        distance = _segment_distance(router.graph, current_node, next_node)
        seconds = distance / max(speed, 0.1)
        cursor += seconds
        legs.append({
            "from_node": current_node,
            "to_node": next_node,
            "distance": round(distance, 3),
            "seconds": round(seconds, 2),
        })
        timeline.append({
            "node_id": next_node,
            "arrival_seconds": round(cursor, 2),
            "departure_seconds": round(cursor, 2),
            "wait_seconds": 0.0,
        })

    battery_required = round(path.distance * BATTERY_DROP_PER_METER, 2)
    battery_ok = agv is None or agv.battery_percent - battery_required >= MIN_BATTERY_PERCENT
    if agv is not None and not battery_ok:
        raise SchedulingError(
            f"{agv.code} 电量不足：预计消耗 {battery_required}%，无法满足安全电量约束。"
        )
    return {
        "start_node": _node_payload(nodes[start_node_id]),
        "end_node": _node_payload(nodes[end_node_id]),
        "agv": {
            "id": agv.id,
            "code": agv.code,
            "speed": agv.speed,
            "battery_percent": agv.battery_percent,
            "battery_required": battery_required,
            "battery_ok": battery_ok,
        } if agv else None,
        "distance": path.distance,
        "estimated_duration": round(cursor, 2),
        "constraints": {
            "obstacle_avoidance": True,
            "road_topology": True,
            "battery_ok": battery_ok,
        },
        "route": {
            "nodes": path.nodes,
            "legs": legs,
            "timeline": timeline,
            "waits": [],
            "start_node": start_node_id,
            "end_node": end_node_id,
        },
    }


def _node_payload(node: MapNode) -> dict:
    return {
        "id": node.id,
        "code": node.code,
        "name": node.name,
        "node_type": node.node_type,
        "x": node.x,
        "y": node.y,
    }
