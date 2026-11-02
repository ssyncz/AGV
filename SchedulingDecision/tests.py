from types import SimpleNamespace
from unittest import mock
from datetime import timedelta

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from Operations.models import WorkOrder
from .models import AGV, DispatchRecord, MapNode, ProductionPlan, ScheduleRun, TransportTask
from .services import (
    SchedulingError,
    _build_or_opt_moves,
    _build_relocate_moves,
    _build_swap_moves,
    _build_two_opt_moves,
    complete_task,
    dispatch_batch,
    dispatch_single,
    dispatch_single_sequence,
    improve_solution_vns,
    start_task,
)


class SchedulingFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", "--reset", verbosity=0)

    def test_seed_demo_can_rebuild_twenty_tasks_without_replacing_base_data(self):
        node_count = MapNode.objects.count()
        agv_count = AGV.objects.count()
        agv = AGV.objects.first()
        original_node_id = agv.current_node_id
        agv.battery_percent = 42
        agv.status = AGV.Status.BUSY
        agv.save(update_fields=["battery_percent", "status"])

        call_command(
            "seed_demo", "--reset-tasks", "--task-count", "20", verbosity=0
        )

        self.assertEqual(TransportTask.objects.count(), 20)
        self.assertEqual(
            TransportTask.objects.filter(status=TransportTask.Status.PENDING).count(),
            20,
        )
        self.assertEqual(MapNode.objects.count(), node_count)
        self.assertEqual(AGV.objects.count(), agv_count)
        agv.refresh_from_db()
        self.assertEqual(agv.current_node_id, original_node_id)
        self.assertEqual(agv.battery_percent, 42)
        self.assertEqual(agv.status, AGV.Status.IDLE)

    def test_single_dispatch_builds_route_and_updates_status(self):
        task = TransportTask.objects.filter(status=TransportTask.Status.PENDING).first()
        result = dispatch_single(task.id)
        result.refresh_from_db()
        self.assertEqual(result.status, TransportTask.Status.ASSIGNED)
        self.assertIsNotNone(result.assigned_agv)
        self.assertGreater(result.total_distance, 0)
        self.assertIn(result.pickup_node_id, result.route["nodes"])
        self.assertIn(result.dropoff_node_id, result.route["nodes"])
        self.assertEqual(result.assigned_agv.status, AGV.Status.BUSY)

    def test_single_agv_multi_task_sequence_is_optimized(self):
        task_ids = list(
            TransportTask.objects.filter(status=TransportTask.Status.PENDING)
            .order_by("created_at")
            .values_list("id", flat=True)[:5]
        )
        result = dispatch_single_sequence(task_ids)
        tasks = list(
            TransportTask.objects.filter(id__in=task_ids)
            .select_related("assigned_agv", "schedule_run")
            .order_by("sequence_number")
        )
        self.assertEqual(len(tasks), 5)
        self.assertEqual(len({task.assigned_agv_id for task in tasks}), 1)
        self.assertEqual([task.sequence_number for task in tasks], [1, 2, 3, 4, 5])
        self.assertTrue(all(task.schedule_run_id for task in tasks))
        self.assertEqual(
            result["run"].algorithm, ScheduleRun.Algorithm.SINGLE_SEQUENCE
        )
        self.assertGreaterEqual(result["run"].improvement_percent, 0)

    def test_batch_dispatch_optimizes_multiple_agvs(self):
        result = dispatch_batch()
        evaluation = result["evaluation"]
        self.assertEqual(len(result["tasks"]), 6)
        self.assertGreaterEqual(evaluation["used_agvs"], 2)
        self.assertLessEqual(evaluation["used_agvs"], 4)
        self.assertGreater(evaluation["makespan_seconds"], 0)
        self.assertEqual(
            result["run"].algorithm, ScheduleRun.Algorithm.MULTI_VNS
        )
        self.assertEqual(
            TransportTask.objects.filter(status=TransportTask.Status.ASSIGNED).count(), 6
        )
        self.assertEqual(DispatchRecord.objects.filter(algorithm="batch").count(), 6)

    def test_optimized_sequence_must_be_executed_in_order(self):
        task_ids = list(
            TransportTask.objects.filter(status=TransportTask.Status.PENDING)
            .values_list("id", flat=True)[:3]
        )
        dispatch_single_sequence(task_ids)
        ordered = list(
            TransportTask.objects.filter(id__in=task_ids).order_by("sequence_number")
        )
        with self.assertRaises(SchedulingError):
            start_task(ordered[1].id)
        start_task(ordered[0].id)
        complete_task(ordered[0].id)
        start_task(ordered[1].id)
        complete_task(ordered[1].id)
        start_task(ordered[2].id)
        complete_task(ordered[2].id)
        self.assertEqual(
            TransportTask.objects.filter(id__in=task_ids, status="completed").count(), 3
        )
    def test_task_lifecycle_updates_agv_position_and_battery(self):
        task = TransportTask.objects.filter(status=TransportTask.Status.PENDING).first()
        dispatch_single(task.id)
        task.refresh_from_db()
        agv = task.assigned_agv
        original_battery = agv.battery_percent
        start_task(task.id)
        complete_task(task.id)
        task.refresh_from_db()
        agv.refresh_from_db()
        self.assertEqual(task.status, TransportTask.Status.COMPLETED)
        self.assertEqual(agv.current_node_id, task.dropoff_node_id)
        self.assertLess(agv.battery_percent, original_battery)

    def test_dispatch_order_continues_existing_work_order_sequence(self):
        work_order = WorkOrder.objects.create(title="连续顺序测试")
        pickup = MapNode.objects.get(code="S1")
        dropoff = MapNode.objects.get(code="S6")
        TransportTask.objects.create(
            task_no="SEQ-EXISTING-010",
            work_order=work_order,
            pickup_node=pickup,
            dropoff_node=dropoff,
            cargo_name="历史任务",
            cargo_weight=10,
            status=TransportTask.Status.COMPLETED,
            dispatch_order=10,
        )
        new_task = TransportTask.objects.create(
            task_no="SEQ-NEW-001",
            work_order=work_order,
            pickup_node=pickup,
            dropoff_node=dropoff,
            cargo_name="新任务",
            cargo_weight=10,
        )
        dispatch_batch([new_task.id])
        new_task.refresh_from_db()
        self.assertEqual(new_task.dispatch_order, 11)


class APITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", "--reset", verbosity=0)

    def setUp(self):
        self.client = APIClient()
        self.host = {"HTTP_HOST": "localhost"}

    def test_overview_and_map_endpoints(self):
        overview = self.client.get("/api/overview/", **self.host)
        graph = self.client.get("/api/map/", **self.host)
        self.assertEqual(overview.status_code, 200)
        self.assertEqual(overview.data["agv_total"], 4)
        self.assertEqual(graph.status_code, 200)
        self.assertEqual(len(graph.data["nodes"]), 76)
        self.assertEqual(len(graph.data["edges"]), 103)
        self.assertEqual(len(graph.data["obstacles"]), 10)

    def test_single_schedule_endpoint_accepts_multiple_tasks(self):
        task_ids = list(
            TransportTask.objects.filter(status=TransportTask.Status.PENDING)
            .values_list("id", flat=True)[:4]
        )
        response = self.client.post(
            "/api/schedules/single/",
            {"task_ids": task_ids},
            format="json",
            **self.host,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["tasks"]), 4)
        self.assertEqual(response.data["run"]["algorithm"], "single_sequence")
        self.assertGreater(response.data["evaluation"]["makespan_seconds"], 0)

    def test_path_planning_endpoint_avoids_obstacles(self):
        start = MapNode.objects.get(code="S2")
        end = MapNode.objects.get(code="S6")
        response = self.client.post(
            "/api/path-planning/",
            {"start_node_id": start.id, "end_node_id": end.id},
            format="json",
            **self.host,
        )
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.data["distance"], 0)
        self.assertEqual(response.data["route"]["nodes"][0], start.id)
        self.assertEqual(response.data["route"]["nodes"][-1], end.id)

    def test_batch_schedule_endpoint_returns_optimization_metrics(self):
        response = self.client.post(
            "/api/schedules/batch/", {}, format="json", **self.host
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["run"]["task_count"], 6)
        self.assertGreaterEqual(response.data["run"]["agv_count"], 2)
        self.assertTrue(response.data["evaluation"]["feasible"])


class ProductionPlanningApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", "--reset", verbosity=0)

    def setUp(self):
        self.client = APIClient()
        self.host = {"HTTP_HOST": "localhost"}

    def _create_forecast(self, horizon=2):
        response = self.client.post(
            "/api/forecast/predict/",
            {"horizon": horizon, "model": "moving_average"},
            format="json",
            **self.host,
        )
        self.assertEqual(response.status_code, 200)
        return response.data["record_id"]

    def _create_plan(self, forecast_run_id, **overrides):
        pickup = MapNode.objects.get(code="S1")
        dropoff = MapNode.objects.get(code="S6")
        payload = {
            "forecast_run_id": forecast_run_id,
            "name": "API 链路测试计划",
            "planning_start_date": (timezone.localdate() + timedelta(days=1)).isoformat(),
            "tasks_per_order": 0.02,
            "demand_buffer_percent": 10,
            "release_lead_hours": 24,
            "due_hour": 18,
            "max_tasks": 20,
            "pickup_node_id": pickup.id,
            "dropoff_node_id": dropoff.id,
            "cargo_name": "预测任务货物",
            "cargo_weight": 30,
            "priority": 2,
        }
        payload.update(overrides)
        return self.client.post(
            "/api/production-plans/generate/", payload, format="json", **self.host
        )

    def test_forecast_can_generate_plan_tasks_and_schedule(self):
        forecast_run_id = self._create_forecast(horizon=2)
        response = self._create_plan(forecast_run_id)
        self.assertEqual(response.status_code, 201)
        plan_id = response.data["plan"]["id"]
        plan = ProductionPlan.objects.get(pk=plan_id)
        tasks = list(plan.tasks.all())
        self.assertGreater(len(tasks), 0)
        self.assertEqual(len(tasks), plan.task_count)
        self.assertTrue(all(task.release_at and task.due_at for task in tasks))
        self.assertTrue(all(task.due_at > task.release_at for task in tasks))
        self.assertTrue(all(task.forecast_order_count > 0 for task in tasks))

        schedule = self.client.post(
            f"/api/production-plans/{plan_id}/schedule/",
            {"strict_deadlines": False},
            format="json",
            **self.host,
        )
        self.assertEqual(schedule.status_code, 200)
        self.assertEqual(schedule.data["run"]["production_plan"], plan_id)
        self.assertEqual(schedule.data["run"]["task_count"], plan.task_count)
        self.assertIn("late_task_count", schedule.data["run"])
        self.assertEqual(schedule.data["plan"]["status"], ProductionPlan.Status.SCHEDULED)
        plan.refresh_from_db()
        self.assertEqual(plan.status, ProductionPlan.Status.SCHEDULED)
        self.assertTrue(
            all(
                task.status == TransportTask.Status.ASSIGNED
                for task in plan.tasks.all()
            )
        )

    def test_task_cannot_start_before_release_time(self):
        forecast_run_id = self._create_forecast(horizon=1)
        start_day = timezone.localdate() + timedelta(days=3)
        response = self._create_plan(
            forecast_run_id,
            planning_start_date=start_day.isoformat(),
            release_lead_hours=1,
        )
        self.assertEqual(response.status_code, 201)
        plan_id = response.data["plan"]["id"]
        schedule = self.client.post(
            f"/api/production-plans/{plan_id}/schedule/",
            {"strict_deadlines": False},
            format="json",
            **self.host,
        )
        self.assertEqual(schedule.status_code, 200)
        task_id = schedule.data["tasks"][0]["id"]
        start = self.client.post(
            f"/api/tasks/{task_id}/start/", {}, format="json", **self.host
        )
        self.assertEqual(start.status_code, 400)
        self.assertIn("释放时间", start.data["detail"])

    def test_forecast_with_plan_cannot_be_deleted(self):
        forecast_run_id = self._create_forecast(horizon=1)
        response = self._create_plan(forecast_run_id)
        self.assertEqual(response.status_code, 201)
        deletion = self.client.delete(
            f"/api/forecast/runs/{forecast_run_id}/", **self.host
        )
        self.assertEqual(deletion.status_code, 400)
        self.assertIn("生产计划", deletion.data["detail"])

    def test_multi_route_plan_distributes_tasks(self):
        forecast_run_id = self._create_forecast(horizon=2)
        pickups = list(
            MapNode.objects.filter(node_type=MapNode.NodeType.PICKUP).order_by("code")[:2]
        )
        dropoffs = list(
            MapNode.objects.filter(node_type=MapNode.NodeType.DROPOFF).order_by("code")[:2]
        )
        self.assertEqual(len(pickups), 2)
        self.assertEqual(len(dropoffs), 2)
        response = self._create_plan(
            forecast_run_id,
            routes=[
                {
                    "pickup_node_id": pickups[0].id,
                    "dropoff_node_id": dropoffs[0].id,
                    "cargo_name": "路线 A 货物",
                    "cargo_weight": 30,
                    "priority": 2,
                    "share": 1,
                },
                {
                    "pickup_node_id": pickups[1].id,
                    "dropoff_node_id": dropoffs[1].id,
                    "cargo_name": "路线 B 货物",
                    "cargo_weight": 20,
                    "priority": 3,
                    "share": 1,
                },
            ],
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["plan"]["route_count"], 2)
        plan = ProductionPlan.objects.get(pk=response.data["plan"]["id"])
        used_pickups = set(plan.tasks.values_list("pickup_node_id", flat=True))
        used_pairs = set(plan.tasks.values_list("pickup_node_id", "dropoff_node_id"))
        self.assertEqual(len(used_pickups), 2)
        self.assertEqual(
            used_pairs,
            {(pickups[0].id, dropoffs[0].id), (pickups[1].id, dropoffs[1].id)},
        )

    def test_strict_deadline_rejects_late_task(self):
        task = TransportTask.objects.filter(status=TransportTask.Status.PENDING).first()
        task.due_at = timezone.now() - timedelta(minutes=1)
        task.save(update_fields=["due_at", "updated_at"])
        response = self.client.post(
            "/api/schedules/batch/",
            {"task_ids": [task.id], "strict_deadlines": True},
            format="json",
            **self.host,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("硬交期", response.data["detail"])


class NeighborhoodTests(SimpleTestCase):
    """变邻域算子与变邻域下降的纯逻辑测试（不需要数据库）。"""

    AGV_IDS = [1, 2, 3]
    TASK_IDS = [101, 102, 103, 104, 105, 106]
    INITIAL_ORDERS = {1: [101, 102, 103], 2: [104], 3: [105, 106]}

    def _assert_task_multiset_preserved(self, candidate):
        """每个任务必须出现且只出现一次（所有邻域都不能丢任务或复制任务）。"""
        flattened = [task_id for order in candidate.values() for task_id in order]
        self.assertEqual(len(flattened), len(self.TASK_IDS))
        self.assertEqual(sorted(flattened), sorted(self.TASK_IDS))

    def test_relocate_moves_preserve_tasks(self):
        moves = _build_relocate_moves(self.INITIAL_ORDERS, self.TASK_IDS, self.AGV_IDS)
        self.assertGreater(len(moves), 0)
        for candidate in moves:
            self._assert_task_multiset_preserved(candidate)

    def test_swap_moves_preserve_tasks(self):
        moves = _build_swap_moves(self.INITIAL_ORDERS, self.AGV_IDS)
        self.assertGreater(len(moves), 0)
        for candidate in moves:
            self._assert_task_multiset_preserved(candidate)

    def test_or_opt_moves_preserve_tasks(self):
        moves = _build_or_opt_moves(self.INITIAL_ORDERS, self.AGV_IDS)
        self.assertGreater(len(moves), 0)
        for candidate in moves:
            self._assert_task_multiset_preserved(candidate)

    def test_two_opt_moves_preserve_tasks(self):
        moves = _build_two_opt_moves(self.INITIAL_ORDERS, self.AGV_IDS)
        self.assertGreater(len(moves), 0)
        for candidate in moves:
            self._assert_task_multiset_preserved(candidate)

    def test_vns_reduces_objective_and_is_reproducible(self):
        """构造一个距离矩阵，验证 VND 能下降目标值，并且同种子结果一致。"""

        def cost(orders):
            total = 0.0
            for agv_id, order in orders.items():
                if not order:
                    continue
                total += 2.0 * agv_id + 3.0 * order[0]  # 起点成本
                for first, second in zip(order, order[1:]):
                    total += abs(first - second) * 1.5  # 任务间转移成本
            return total

        def fake_evaluate(tasks, agvs, orders, router, now, weights=None, **kwargs):
            normalized = {int(key): list(value) for key, value in orders.items()}
            flattened = [task_id for order in normalized.values() for task_id in order]
            feasible = sorted(flattened) == sorted(self.TASK_IDS)
            return SimpleNamespace(
                feasible=feasible,
                objective=cost(normalized) if feasible else float("inf"),
                orders=normalized,
            )

        initial_orders = {agv_id: list(order) for agv_id, order in self.INITIAL_ORDERS.items()}
        initial = SimpleNamespace(
            feasible=True, objective=cost(initial_orders), orders=initial_orders
        )
        agvs = [SimpleNamespace(id=agv_id) for agv_id in self.AGV_IDS]
        tasks = {task_id: None for task_id in self.TASK_IDS}

        with mock.patch("SchedulingDecision.services.evaluate_solution", fake_evaluate):
            first, iterations = improve_solution_vns(initial, tasks, agvs, None, None)
            second, _ = improve_solution_vns(
                SimpleNamespace(
                    feasible=True,
                    objective=cost({k: list(v) for k, v in self.INITIAL_ORDERS.items()}),
                    orders={k: list(v) for k, v in self.INITIAL_ORDERS.items()},
                ),
                tasks,
                agvs,
                None,
                None,
            )

        self.assertTrue(first.feasible)
        self.assertLess(first.objective, initial.objective)  # 目标值必须下降
        self.assertGreater(iterations, 0)  # 迭代次数被记录
        self.assertEqual(first.orders, second.orders)  # 固定种子 → 结果可复现
        self._assert_task_multiset_preserved(first.orders)
