# -*- coding: utf-8 -*-
"""课程报告用调度/路径规划基准实验。

本脚本只读取项目中的算法与演示地图定义，不写业务数据库。
输出：
  docs/report/evidence/scheduling_benchmark.json
  docs/report/evidence/path_planning.csv
  docs/report/evidence/single_agv.csv
  docs/report/evidence/multi_agv.csv

运行：
  .venv/bin/python scripts/report_bench_scheduling.py
"""
from __future__ import annotations

import csv
import heapq
import itertools
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AGV.settings")
os.environ.setdefault("DB_ENGINE", "sqlite")

import django

django.setup()

from SchedulingDecision.management.commands.seed_demo import (  # noqa: E402
    CELL_SIZE,
    GRID_COLS,
    GRID_ROWS,
    OBSTACLES,
    STATIONS,
    TASK_TEMPLATES,
)
from SchedulingDecision.models import AGV  # noqa: E402
from SchedulingDecision.services import (  # noqa: E402
    GraphRouter,
    _build_or_opt_moves,
    _build_relocate_moves,
    _build_swap_moves,
    _build_two_opt_moves,
    _first_task_distance,
    _sequence_distance,
    _two_opt_single_order,
    build_baseline_solution,
    build_insertion_solution,
    evaluate_solution,
    optimize_multi_solution,
    optimize_single_order,
)

OUT_DIR = ROOT / "docs" / "report" / "evidence"
OUT_DIR.mkdir(parents=True, exist_ok=True)
NOW = datetime(2026, 10, 19, 8, 0, 0)
DEFAULT_WEIGHTS = {
    "agv_weight": 30.0,
    "wait_weight": 0.20,
    "distance_weight": 0.005,
    "priority_weight": 0.02,
}


def pct(value: float, base: float) -> float:
    return round((base - value) / base * 100.0, 4) if base else 0.0


def human_duration(value: float) -> str:
    return f"{value:.3f}"


def build_grid_map():
    blocked = set()
    for _code, _name, x, y, width, height in OBSTACLES:
        for col in range(int(x), int(x + width)):
            for row in range(int(y), int(y + height)):
                blocked.add((col, row))

    code_to_id = {}
    positions = {}
    node_id = 1
    for col in range(GRID_COLS):
        for row in range(GRID_ROWS):
            if (col, row) in blocked:
                continue
            code = next(
                (code for code, item in STATIONS.items() if item["x"] == col and item["y"] == row),
                f"G{col:02d}{row:02d}",
            )
            code_to_id[code] = node_id
            positions[node_id] = (float(col), float(row))
            node_id += 1

    graph = {node: [] for node in positions}
    edge_count = 0
    id_by_cell = {
        (int(x), int(y)): node for node, (x, y) in positions.items()
    }
    for (col, row), node in id_by_cell.items():
        for next_col, next_row in ((col + 1, row), (col, row + 1)):
            neighbor = id_by_cell.get((next_col, next_row))
            if neighbor is None:
                continue
            graph[node].append((neighbor, CELL_SIZE, 1.2))
            graph[neighbor].append((node, CELL_SIZE, 1.2))
            edge_count += 1
    return graph, positions, code_to_id, edge_count


def dijkstra_with_count(graph, start, end):
    distances = {start: 0.0}
    previous = {}
    queue = [(0.0, start)]
    visited = set()
    expanded = 0
    while queue:
        distance, current = heapq.heappop(queue)
        if current in visited:
            continue
        visited.add(current)
        expanded += 1
        if current == end:
            break
        for neighbor, weight, _speed in graph.get(current, []):
            candidate = distance + weight
            if candidate < distances.get(neighbor, float("inf")):
                distances[neighbor] = candidate
                previous[neighbor] = current
                heapq.heappush(queue, (candidate, neighbor))
    if end not in distances:
        return None, float("inf"), expanded
    path = [end]
    while path[-1] != start:
        path.append(previous[path[-1]])
    path.reverse()
    return path, distances[end], expanded


def astar_with_count(graph, positions, start, end):
    def heuristic(node):
        x1, y1 = positions[node]
        x2, y2 = positions[end]
        return (abs(x1 - x2) + abs(y1 - y2)) * CELL_SIZE

    queue = [(heuristic(start), 0.0, start)]
    best = {start: 0.0}
    previous = {}
    visited = set()
    expanded = 0
    while queue:
        _f, distance, current = heapq.heappop(queue)
        if current in visited:
            continue
        visited.add(current)
        expanded += 1
        if current == end:
            break
        for neighbor, weight, _speed in graph.get(current, []):
            candidate = distance + weight
            if candidate < best.get(neighbor, float("inf")):
                best[neighbor] = candidate
                previous[neighbor] = current
                heapq.heappush(queue, (candidate + heuristic(neighbor), candidate, neighbor))
    if end not in best:
        return None, float("inf"), expanded
    path = [end]
    while path[-1] != start:
        path.append(previous[path[-1]])
    path.reverse()
    return path, best[end], expanded


def bfs_path(graph, start, end):
    queue = deque([start])
    previous = {start: None}
    expanded = 0
    while queue:
        current = queue.popleft()
        expanded += 1
        if current == end:
            break
        for neighbor, _weight, _speed in graph.get(current, []):
            if neighbor not in previous:
                previous[neighbor] = current
                queue.append(neighbor)
    if end not in previous:
        return None, expanded
    path = [end]
    while path[-1] != start:
        path.append(previous[path[-1]])
    path.reverse()
    return path, expanded


def weighted_bfs_counterexample():
    graph = {
        0: [(1, 1.0, 1.0), (3, 100.0, 1.0)],
        1: [(0, 1.0, 1.0), (2, 1.0, 1.0)],
        2: [(1, 1.0, 1.0), (3, 1.0, 1.0)],
        3: [(0, 100.0, 1.0), (2, 1.0, 1.0)],
    }
    bfs_nodes, _ = bfs_path(graph, 0, 3)
    dij_nodes, dij_distance, _ = dijkstra_with_count(graph, 0, 3)
    return {
        "bfs_path": bfs_nodes,
        "bfs_distance": 100.0,
        "dijkstra_path": dij_nodes,
        "dijkstra_distance": dij_distance,
        "note": "BFS 只最小化边数，没有考虑边权；Dijkstra 最小化总距离。",
    }


def benchmark_path_planning():
    graph, positions, code_to_id, edge_count = build_grid_map()
    router = GraphRouter(graph)
    source, target = code_to_id["CHARGE"], code_to_id["HOME1"]
    path = router.path(source, target)

    node_ids = sorted(graph)
    dijkstra_distances = []
    astar_distances = []
    dijkstra_expanded = []
    astar_expanded = []
    t0 = time.perf_counter()
    for start in node_ids:
        for end in node_ids:
            _path, distance, expanded = dijkstra_with_count(graph, start, end)
            dijkstra_distances.append(distance)
            dijkstra_expanded.append(expanded)
    dijkstra_all_pairs_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    for start in node_ids:
        for end in node_ids:
            _path, distance, expanded = astar_with_count(graph, positions, start, end)
            astar_distances.append(distance)
            astar_expanded.append(expanded)
    astar_all_pairs_s = time.perf_counter() - t0

    rng = random.Random(20261019)
    query_pairs = [(rng.choice(node_ids), rng.choice(node_ids)) for _ in range(5000)]

    t0 = time.perf_counter()
    for start, end in query_pairs:
        router._dijkstra(start, end)
    uncached_s = time.perf_counter() - t0

    warm_router = GraphRouter(graph)
    t0 = time.perf_counter()
    for start in node_ids:
        for end in node_ids:
            warm_router.path(start, end)
    warm_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    for start, end in query_pairs:
        warm_router.path(start, end)
    cached_s = time.perf_counter() - t0

    return {
        "map": {
            "grid": f"{GRID_COLS}x{GRID_ROWS}",
            "nodes": len(graph),
            "edges": edge_count,
            "cell_size_m": CELL_SIZE,
            "obstacle_rectangles": len(OBSTACLES),
        },
        "example": {
            "source": "CHARGE",
            "target": "HOME1",
            "nodes": len(path.nodes),
            "distance_m": path.distance,
            "estimated_seconds_at_1_2_mps": round(path.distance / 1.2, 3),
            "route": path.nodes,
        },
        "all_pairs": {
            "query_count": len(node_ids) * len(node_ids),
            "dijkstra_total_s": round(dijkstra_all_pairs_s, 6),
            "dijkstra_mean_ms": round(dijkstra_all_pairs_s / len(dijkstra_distances) * 1000, 6),
            "astar_total_s": round(astar_all_pairs_s, 6),
            "astar_mean_ms": round(astar_all_pairs_s / len(astar_distances) * 1000, 6),
            "same_distance_count": sum(1 for a, b in zip(dijkstra_distances, astar_distances) if abs(a - b) < 1e-9),
            "dijkstra_mean_expanded": round(statistics.mean(dijkstra_expanded), 4),
            "astar_mean_expanded": round(statistics.mean(astar_expanded), 4),
        },
        "cache": {
            "query_count": len(query_pairs),
            "uncached_total_s": round(uncached_s, 6),
            "uncached_mean_us": round(uncached_s / len(query_pairs) * 1_000_000, 3),
            "warm_all_pairs_s": round(warm_s, 6),
            "cached_total_s": round(cached_s, 6),
            "cached_mean_us": round(cached_s / len(query_pairs) * 1_000_000, 3),
            "speedup_x": round(uncached_s / cached_s, 2) if cached_s else None,
        },
        "bfs_counterexample": weighted_bfs_counterexample(),
        "bfs_on_current_map_note": "当前演示地图所有道路长度均为 4 m，因此 BFS 的最少边数路径与 Dijkstra 的最短距离恰好一致；这不能作为 BFS 可用于一般加权图的依据。",
    }


def make_agv(agv_id, code, start_node, battery, capacity, speed):
    return SimpleNamespace(
        id=agv_id,
        code=code,
        name=code,
        status=AGV.Status.IDLE,
        current_node_id=start_node,
        battery_percent=battery,
        payload_capacity=capacity,
        speed=speed,
    )


def make_tasks(task_specs, code_to_id, start_id=1):
    tasks = []
    for offset, (pickup, dropoff, cargo, weight, priority) in enumerate(task_specs):
        tasks.append(SimpleNamespace(
            id=start_id + offset,
            task_no=f"TASK-DEMO-{start_id + offset:03d}",
            cargo_name=cargo,
            cargo_weight=float(weight),
            priority=int(priority),
            created_at=NOW.replace(microsecond=0) + __import__("datetime").timedelta(seconds=offset),
            pickup_node_id=code_to_id[pickup],
            dropoff_node_id=code_to_id[dropoff],
        ))
    return tasks


def task_costs(router, agv, tasks):
    first = [
        _first_task_distance(router, agv.current_node_id, task)
        for task in tasks
    ]
    transition = [
        [
            router.path(tasks[i].dropoff_node_id, tasks[j].pickup_node_id).distance
            + router.path(tasks[j].pickup_node_id, tasks[j].dropoff_node_id).distance
            for j in range(len(tasks))
        ]
        for i in range(len(tasks))
    ]
    return first, transition


def order_cost(order, first, transition):
    if not order:
        return 0.0
    total = first[order[0]]
    for left, right in zip(order, order[1:]):
        total += transition[left][right]
    return total


def exact_dp_order(first, transition):
    n = len(first)
    dp = {}
    for i in range(n):
        dp[(1 << i, i)] = (first[i], (i,))
    for mask in range(1, 1 << n):
        for last in range(n):
            state = (mask, last)
            if state not in dp or not (mask & (1 << last)):
                continue
            cost, path = dp[state]
            for nxt in range(n):
                if mask & (1 << nxt):
                    continue
                new_mask = mask | (1 << nxt)
                new_cost = cost + transition[last][nxt]
                key = (new_mask, nxt)
                existing = dp.get(key)
                if existing is None or new_cost < existing[0] - 1e-9:
                    dp[key] = (new_cost, path + (nxt,))
    full = (1 << n) - 1
    cost, order = min((dp[(full, last)] for last in range(n)), key=lambda item: item[0])
    return list(order), cost


def brute_force_order(first, transition):
    n = len(first)
    best_order = None
    best_cost = float("inf")
    for order in itertools.permutations(range(n)):
        cost = order_cost(order, first, transition)
        if cost < best_cost:
            best_cost = cost
            best_order = order
    return list(best_order), best_cost


def nn_2opt_order(agv, tasks, router):
    remaining = list(range(len(tasks)))
    order = []
    current_node = agv.current_node_id
    while remaining:
        selected = min(remaining, key=lambda i: _first_task_distance(router, current_node, tasks[i]))
        order.append(selected)
        current_node = tasks[selected].dropoff_node_id
        remaining.remove(selected)
    task_ids = [task.id for task in tasks]
    selected_ids = [task_ids[i] for i in order]
    task_lookup = {task.id: task for task in tasks}
    optimized = _two_opt_single_order(
        router, agv, tasks, [task_lookup[task_id].id for task_id in selected_ids]
    )
    return [task_ids.index(task_id) for task_id in optimized]


def benchmark_single_agv(graph, code_to_id):
    router = GraphRouter(graph)
    start = code_to_id["S3"]
    agv = make_agv(1, "AGV-03", start, 73.0, 150.0, 1.4)
    rows = []
    for n in (4, 6, 8, 10, 12, 14):
        for seed in range(5):
            rng = random.Random(1000 + seed + n)
            selected = rng.sample(TASK_TEMPLATES, n)
            tasks = make_tasks(selected, code_to_id)
            for task in tasks:
                _first_task_distance(router, agv.current_node_id, task)
                for other in tasks:
                    router.path(task.dropoff_node_id, other.pickup_node_id)
                    router.path(other.pickup_node_id, other.dropoff_node_id)
            first, transition = task_costs(router, agv, tasks)
            baseline_distance = order_cost(list(range(n)), first, transition)

            t0 = time.perf_counter()
            app_order = optimize_single_order(agv, tasks, router)
            app_time_ms = (time.perf_counter() - t0) * 1000
            app_indices = [next(i for i, task in enumerate(tasks) if task.id == task_id) for task_id in app_order]
            app_distance = order_cost(app_indices, first, transition)

            t0 = time.perf_counter()
            nn_indices = nn_2opt_order(agv, tasks, router)
            nn_time_ms = (time.perf_counter() - t0) * 1000
            nn_distance = order_cost(nn_indices, first, transition)

            t0 = time.perf_counter()
            dp_indices, dp_distance = exact_dp_order(first, transition)
            dp_time_ms = (time.perf_counter() - t0) * 1000

            brute_distance = None
            brute_time_ms = None
            if n <= 8:
                t0 = time.perf_counter()
                _brute_indices, brute_distance = brute_force_order(first, transition)
                brute_time_ms = (time.perf_counter() - t0) * 1000

            rows.append({
                "task_count": n,
                "seed": seed,
                "baseline_distance_m": round(baseline_distance, 3),
                "dp_distance_m": round(dp_distance, 3),
                "nn_2opt_distance_m": round(nn_distance, 3),
                "brute_force_distance_m": round(brute_distance, 3) if brute_distance is not None else None,
                "app_order_distance_m": round(app_distance, 3),
                "nn_gap_to_exact_pct": round((nn_distance - dp_distance) / dp_distance * 100.0, 4) if dp_distance else 0.0,
                "baseline_gap_to_exact_pct": round((baseline_distance - dp_distance) / dp_distance * 100.0, 4) if dp_distance else 0.0,
                "dp_time_ms": round(dp_time_ms, 6),
                "nn_2opt_time_ms": round(nn_time_ms, 6),
                "brute_force_time_ms": round(brute_time_ms, 6) if brute_time_ms is not None else None,
                "app_time_ms": round(app_time_ms, 6),
                "app_used_dp": n <= 10,
            })
    return rows


def build_synthetic_instance(n_customers, n_agvs, seed):
    rng = random.Random(seed)
    positions = {1: (50.0, 50.0)}
    for i in range(1, n_customers + 1):
        cx, cy = [(30, 30), (70, 30), (30, 70), (70, 70)][i % 4]
        positions[i + 1] = (
            max(0.0, min(100.0, cx + rng.uniform(-12, 12))),
            max(0.0, min(100.0, cy + rng.uniform(-12, 12))),
        )
    graph = {}
    for a, (x1, y1) in positions.items():
        graph[a] = [
            (b, round(math.dist((x1, y1), (x2, y2)), 6), 1.0)
            for b, (x2, y2) in positions.items() if b != a
        ]
    agvs = [make_agv(i + 1, f"AGV-{i + 1}", 1, 100.0, 100.0, 1.0) for i in range(n_agvs)]
    tasks = []
    for i in range(1, n_customers + 1):
        tasks.append(SimpleNamespace(
            id=i,
            task_no=f"T{i:03d}",
            cargo_name=f"货物{i}",
            cargo_weight=round(rng.uniform(5, 40), 1),
            priority=2,
            created_at=NOW.replace(microsecond=0) + __import__("datetime").timedelta(seconds=i),
            pickup_node_id=1,
            dropoff_node_id=i + 1,
        ))
    return graph, agvs, tasks


def build_current_map_instance(graph, code_to_id, task_count=6):
    agvs = [
        make_agv(1, "AGV-01", code_to_id["CHARGE"], 96.0, 120.0, 1.2),
        make_agv(2, "AGV-02", code_to_id["S2"], 88.0, 120.0, 1.1),
        make_agv(3, "AGV-03", code_to_id["S3"], 73.0, 150.0, 1.4),
        make_agv(4, "AGV-04", code_to_id["S10"], 64.0, 150.0, 1.35),
    ]
    tasks = make_tasks(TASK_TEMPLATES[:task_count], code_to_id)
    return agvs, tasks


def row_from_evaluation(algorithm, evaluation, elapsed_s, baseline=None, iterations=None):
    row = {
        "algorithm": algorithm,
        "feasible": evaluation.feasible,
        "objective": round(evaluation.objective, 4),
        "makespan_s": round(evaluation.makespan_seconds, 3),
        "total_distance_m": round(evaluation.total_distance, 3),
        "wait_s": round(evaluation.total_wait_seconds, 3),
        "used_agvs": evaluation.used_agvs,
        "runtime_s": round(elapsed_s, 6),
    }
    if iterations is not None:
        row["iterations"] = iterations
    if baseline is not None and baseline.feasible and baseline.objective:
        row["objective_improvement_pct"] = pct(evaluation.objective, baseline.objective)
        row["makespan_improvement_pct"] = pct(evaluation.makespan_seconds, baseline.makespan_seconds)
    return row


def benchmark_multi_agv_current(graph, code_to_id):
    agvs, tasks = build_current_map_instance(graph, code_to_id, task_count=6)
    task_map = {task.id: task for task in tasks}
    router = GraphRouter(graph)

    t0 = time.perf_counter()
    baseline = build_baseline_solution(tasks, agvs, router, NOW, DEFAULT_WEIGHTS)
    baseline_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    insertion = build_insertion_solution(tasks, agvs, router, NOW, DEFAULT_WEIGHTS)
    insertion_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    optimized, returned_baseline, iterations = optimize_multi_solution(
        tasks, agvs, router, NOW, DEFAULT_WEIGHTS
    )
    optimized_s = time.perf_counter() - t0

    return [
        row_from_evaluation("baseline_priority_earliest", baseline, baseline_s),
        row_from_evaluation("best_insertion", insertion, insertion_s, baseline=baseline),
        row_from_evaluation(
            "insertion_plus_vnd", optimized, optimized_s, baseline=baseline, iterations=iterations
        ),
    ], {
        "task_count": len(tasks),
        "agv_count": len(agvs),
        "baseline_matches_returned": abs(returned_baseline.objective - baseline.objective) < 1e-6,
    }


def benchmark_multi_agv_synthetic(configs, seeds):
    rows = []
    for n_customers, n_agvs in configs:
        for seed in seeds:
            graph, agvs, tasks = build_synthetic_instance(n_customers, n_agvs, seed)
            task_map = {task.id: task for task in tasks}
            router = GraphRouter(graph)
            for start in graph:
                for end in graph:
                    router.path(start, end)

            t0 = time.perf_counter()
            baseline = build_baseline_solution(tasks, agvs, router, NOW, DEFAULT_WEIGHTS)
            baseline_s = time.perf_counter() - t0

            t0 = time.perf_counter()
            insertion = build_insertion_solution(tasks, agvs, router, NOW, DEFAULT_WEIGHTS)
            insertion_s = time.perf_counter() - t0

            t0 = time.perf_counter()
            optimized, _returned_baseline, iterations = optimize_multi_solution(
                tasks, agvs, router, NOW, DEFAULT_WEIGHTS
            )
            optimized_s = time.perf_counter() - t0

            for algorithm, evaluation, elapsed in (
                ("baseline_priority_earliest", baseline, baseline_s),
                ("best_insertion", insertion, insertion_s),
                ("insertion_plus_vnd", optimized, optimized_s),
            ):
                row = row_from_evaluation(
                    algorithm,
                    evaluation,
                    elapsed,
                    baseline=baseline if algorithm != "baseline_priority_earliest" else None,
                    iterations=iterations if algorithm == "insertion_plus_vnd" else None,
                )
                row.update({"customers": n_customers, "agvs": n_agvs, "seed": seed})
                rows.append(row)
    return rows


def run_neighborhood_ablation(graph, agvs, tasks, initial):
    task_map = {task.id: task for task in tasks}
    router = GraphRouter(graph)
    for start in graph:
        for end in graph:
            router.path(start, end)
    all_builders = [
        ("relocate", _build_relocate_moves),
        ("swap", _build_swap_moves),
        ("or_opt", _build_or_opt_moves),
        ("two_opt", _build_two_opt_moves),
    ]
    rows = []
    for name, builders in [
        ("relocate_only", all_builders[:1]),
        ("swap_only", all_builders[1:2]),
        ("or_opt_only", all_builders[2:3]),
        ("two_opt_only", all_builders[3:4]),
        ("all_four", all_builders),
    ]:
        current = initial
        iterations = 0
        rng = random.Random(20261019)
        task_ids = [task.id for task in tasks]
        agv_ids = [agv.id for agv in agvs]
        stalled = 0
        rounds = 0
        deadline = time.monotonic() + 0.8
        builder_index = 0
        while rounds < 30 and stalled < len(builders) and time.monotonic() < deadline:
            rounds += 1
            builder = builders[builder_index][1]
            moves = builder(current.orders, task_ids, agv_ids) if builder is _build_relocate_moves else builder(current.orders, agv_ids)
            if len(moves) > 100:
                moves = rng.sample(moves, 100)
            improved = False
            for candidate in moves:
                if time.monotonic() >= deadline:
                    break
                iterations += 1
                evaluation = evaluate_solution(task_map, agvs, candidate, router, NOW, DEFAULT_WEIGHTS)
                if evaluation.feasible and evaluation.objective < current.objective - 1e-7:
                    current = evaluation
                    improved = True
                    break
            if improved:
                builder_index = 0
                stalled = 0
            else:
                builder_index = (builder_index + 1) % len(builders)
                stalled += 1
        rows.append({
            "variant": name,
            "initial_objective": round(initial.objective, 4),
            "final_objective": round(current.objective, 4),
            "improvement_pct": pct(current.objective, initial.objective),
            "iterations": iterations,
            "makespan_s": round(current.makespan_seconds, 3),
            "distance_m": round(current.total_distance, 3),
        })
    return rows


def write_csv(path, rows):
    if not rows:
        return
    fieldnames = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def aggregate_single(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["task_count"], []).append(row)
    out = []
    for n, items in sorted(grouped.items()):
        out.append({
            "task_count": n,
            "runs": len(items),
            "baseline_mean_m": round(statistics.mean(item["baseline_distance_m"] for item in items), 3),
            "exact_dp_mean_m": round(statistics.mean(item["dp_distance_m"] for item in items), 3),
            "nn_2opt_mean_m": round(statistics.mean(item["nn_2opt_distance_m"] for item in items), 3),
            "baseline_gap_mean_pct": round(statistics.mean(item["baseline_gap_to_exact_pct"] for item in items), 3),
            "nn_gap_mean_pct": round(statistics.mean(item["nn_gap_to_exact_pct"] for item in items), 3),
            "exact_dp_mean_ms": round(statistics.mean(item["dp_time_ms"] for item in items), 6),
            "nn_2opt_mean_ms": round(statistics.mean(item["nn_2opt_time_ms"] for item in items), 6),
            "brute_force_mean_ms": round(statistics.mean(item["brute_force_time_ms"] for item in items), 6) if items[0]["brute_force_time_ms"] is not None else None,
        })
    return out


def main():
    graph, positions, code_to_id, edge_count = build_grid_map()
    path_result = benchmark_path_planning()

    single_rows = benchmark_single_agv(graph, code_to_id)
    write_csv(OUT_DIR / "single_agv.csv", single_rows)
    single_summary = aggregate_single(single_rows)

    current_multi_rows, current_multi_meta = benchmark_multi_agv_current(graph, code_to_id)
    write_csv(OUT_DIR / "multi_agv.csv", current_multi_rows)

    synthetic_rows = benchmark_multi_agv_synthetic(
        configs=[(10, 2), (20, 3), (30, 4)],
        seeds=[42, 43, 44, 45, 46],
    )
    write_csv(OUT_DIR / "multi_agv_synthetic.csv", synthetic_rows)

    ablation_graph, ablation_agvs, ablation_tasks = build_synthetic_instance(20, 3, 42)
    ablation_router = GraphRouter(ablation_graph)
    for start in ablation_graph:
        for end in ablation_graph:
            ablation_router.path(start, end)
    ablation_initial = build_insertion_solution(
        ablation_tasks, ablation_agvs, ablation_router, NOW, DEFAULT_WEIGHTS
    )
    ablation_rows = run_neighborhood_ablation(
        ablation_graph, ablation_agvs, ablation_tasks, ablation_initial
    )

    path_rows = [{
        "case": "current_map_example",
        "source": path_result["example"]["source"],
        "target": path_result["example"]["target"],
        "nodes": path_result["example"]["nodes"],
        "distance_m": path_result["example"]["distance_m"],
        "dijkstra_mean_ms": path_result["all_pairs"]["dijkstra_mean_ms"],
        "astar_mean_ms": path_result["all_pairs"]["astar_mean_ms"],
        "mean_expanded_dijkstra": path_result["all_pairs"]["dijkstra_mean_expanded"],
        "mean_expanded_astar": path_result["all_pairs"]["astar_mean_expanded"],
    }]
    write_csv(OUT_DIR / "path_planning.csv", path_rows)

    metadata = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "python": sys.version,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "git_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip(),
        "command": ".venv/bin/python scripts/report_bench_scheduling.py",
        "db_engine_for_import": os.environ.get("DB_ENGINE", "sqlite"),
        "note": "实验不写业务数据库；使用项目实际地图、任务模板与 SchedulingDecision.services 实现。",
    }
    result = {
        "metadata": metadata,
        "path_planning": path_result,
        "single_agv": {
            "raw": single_rows,
            "summary": single_summary,
        },
        "multi_agv_current_map": {
            "meta": current_multi_meta,
            "rows": current_multi_rows,
        },
        "multi_agv_synthetic": synthetic_rows,
        "vnd_neighborhood_ablation": ablation_rows,
    }
    (OUT_DIR / "scheduling_benchmark.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("调度/路径实验完成")
    print(f"地图：{len(graph)} 节点 / {edge_count} 条边")
    print(f"CHARGE -> HOME1：{len(path_result['example']['route'])} 节点，{path_result['example']['distance_m']} m")
    print(f"Dijkstra 全源平均：{path_result['all_pairs']['dijkstra_mean_ms']:.6f} ms/次")
    print(f"A* 全源平均：{path_result['all_pairs']['astar_mean_ms']:.6f} ms/次")
    print(f"缓存加速：{path_result['cache']['speedup_x']}x")
    print("单 AGV 汇总：")
    for row in single_summary:
        print(
            f"  n={row['task_count']:>2}  exact={row['exact_dp_mean_m']:>8.3f} m  "
            f"NN+2opt={row['nn_2opt_mean_m']:>8.3f} m  gap={row['nn_gap_mean_pct']:>6.2f}%  "
            f"DP={row['exact_dp_mean_ms']:.6f} ms  NN={row['nn_2opt_mean_ms']:.6f} ms"
        )
    print("当前地图多 AGV：")
    for row in current_multi_rows:
        print(
            f"  {row['algorithm']}: objective={row['objective']:.2f}, "
            f"makespan={row['makespan_s']:.2f}s, distance={row['total_distance_m']:.1f}m, "
            f"runtime={row['runtime_s']:.3f}s"
        )
    print("VND 邻域消融：")
    for row in ablation_rows:
        print(
            f"  {row['variant']}: {row['initial_objective']:.2f} -> "
            f"{row['final_objective']:.2f} ({row['improvement_pct']:.2f}%)"
        )
    print(f"结果：{OUT_DIR / 'scheduling_benchmark.json'}")


if __name__ == "__main__":
    main()
