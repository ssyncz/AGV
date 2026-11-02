from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from DemandForecast.models import DemandForecastRun
from EquipmentMonitoring.models import EquipmentDiagnosisRecord
from ManufacturingVision.models import VisionRecord
from SchedulingDecision.models import MapNode, ProductionPlan, TransportTask
from SchedulingDecision.production import generate_production_plan

from .models import (
    Alert,
    Equipment,
    ExecutionEvent,
    OperationEvent,
    OperationStep,
    Product,
    Site,
    WorkOrder,
)
from .services import (
    complete_operation_step,
    create_work_order,
    ingest_execution_event,
    record_equipment_result,
    record_quality_result,
    start_operation_step,
    transition_work_order,
)


class WorkOrderFlowTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="S1", name="一号车间")
        self.product = Product.objects.create(code="P1", name="测试产品")
        self.work_order = WorkOrder.objects.create(
            title="测试工单",
            site=self.site,
            product=self.product,
            quantity=10,
            due_at=timezone.now() + timedelta(hours=8),
        )

    def test_complete_requires_quality_pass(self):
        transition_work_order(self.work_order.id, "release")
        transition_work_order(self.work_order.id, "start")
        transition_work_order(self.work_order.id, "quality-check")
        with self.assertRaisesMessage(ValueError, "尚未通过质检"):
            transition_work_order(self.work_order.id, "complete")

        self.work_order.refresh_from_db()
        self.work_order.quality_status = WorkOrder.QualityStatus.PASS
        self.work_order.save(update_fields=["quality_status"])
        completed = transition_work_order(self.work_order.id, "complete")
        self.assertEqual(completed.status, WorkOrder.Status.COMPLETED)

    def test_quality_failure_blocks_work_order_and_creates_alert(self):
        self.work_order.status = WorkOrder.Status.IN_PROGRESS
        self.work_order.save(update_fields=["status"])
        record = VisionRecord.objects.create(
            task_type=VisionRecord.TaskType.CRACK,
            work_order=self.work_order,
            verdict="crack",
            quality_result=VisionRecord.QualityResult.FAIL,
        )
        updated = record_quality_result(
            self.work_order.id,
            record,
            WorkOrder.QualityStatus.FAIL,
            reason="检出裂纹",
        )
        self.assertEqual(updated.status, WorkOrder.Status.BLOCKED)
        self.assertEqual(updated.quality_status, WorkOrder.QualityStatus.FAIL)
        self.assertTrue(
            Alert.objects.filter(
                work_order=self.work_order,
                source_type=Alert.SourceType.QUALITY,
                status=Alert.Status.OPEN,
            ).exists()
        )
        self.assertTrue(
            OperationEvent.objects.filter(
                work_order=self.work_order, event_type="quality.failed"
            ).exists()
        )

    def test_equipment_fault_blocks_work_order(self):
        equipment = Equipment.objects.create(code="CNC-01", site=self.site)
        record = EquipmentDiagnosisRecord.objects.create(
            equipment_code=equipment.code,
            equipment=equipment,
            work_order=self.work_order,
            predicted_state="fault",
            confidence=0.93,
            rule_alerts=["振动超限"],
        )
        record_equipment_result(record)
        self.work_order.refresh_from_db()
        equipment.refresh_from_db()
        self.assertEqual(self.work_order.status, WorkOrder.Status.BLOCKED)
        self.assertEqual(equipment.status, Equipment.Status.FAULT)
        self.assertTrue(
            Alert.objects.filter(
                work_order=self.work_order,
                source_type=Alert.SourceType.EQUIPMENT,
            ).exists()
        )


class ProductionPlanWorkOrderTests(TestCase):
    def test_generated_plan_creates_linked_work_order_and_tasks(self):
        pickup = MapNode.objects.create(
            code="P1", name="取货点", node_type=MapNode.NodeType.PICKUP, x=1, y=1
        )
        dropoff = MapNode.objects.create(
            code="D1", name="放货点", node_type=MapNode.NodeType.DROPOFF, x=2, y=2
        )
        forecast = DemandForecastRun.objects.create(
            model_name=DemandForecastRun.ModelName.AUTO,
            selected_model="moving_average",
            horizon=1,
            history_count=10,
            predicted_total=2,
            forecast=[{"date": "2026-11-03", "order_count": 2}],
        )
        plan = generate_production_plan(
            {
                "forecast_run_id": forecast.id,
                "planning_start_date": "2026-11-03",
                "tasks_per_order": 1,
                "demand_buffer_percent": 10,
                "max_tasks": 20,
                "pickup_node_id": pickup.id,
                "dropoff_node_id": dropoff.id,
            }
        )
        plan.refresh_from_db()
        self.assertIsNotNone(plan.work_order_id)
        tasks = TransportTask.objects.filter(production_plan=plan)
        self.assertGreater(tasks.count(), 0)
        self.assertFalse(tasks.exclude(work_order=plan.work_order).exists())


class OperationStepFlowTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="OPS", name="工序测试站点")
        self.product = Product.objects.create(code="OPP", name="工序测试产品")
        self.work_order = create_work_order(
            {
                "title": "工序顺序测试",
                "site_id": self.site.id,
                "product_id": self.product.id,
                "planned_start": timezone.localdate().isoformat(),
            }
        )
        transition_work_order(self.work_order.id, "release")

    def test_operation_steps_enforce_sequence(self):
        steps = list(self.work_order.operation_steps.order_by("sequence_number"))
        self.assertEqual(len(steps), 4)
        self.assertEqual(steps[0].status, OperationStep.Status.READY)
        with self.assertRaisesMessage(ValueError, "只有已就绪工序可以开始"):
            start_operation_step(steps[1].id)

        started = start_operation_step(steps[0].id)
        self.assertEqual(started.status, OperationStep.Status.IN_PROGRESS)
        completed = complete_operation_step(steps[0].id)
        self.assertEqual(completed.status, OperationStep.Status.COMPLETED)
        steps[1].refresh_from_db()
        self.assertEqual(steps[1].status, OperationStep.Status.READY)

    def test_quality_gate_requires_quality_pass(self):
        steps = list(self.work_order.operation_steps.order_by("sequence_number"))
        start_operation_step(steps[0].id)
        complete_operation_step(steps[0].id)
        start_operation_step(steps[1].id)
        complete_operation_step(steps[1].id)
        start_operation_step(steps[2].id)
        with self.assertRaisesMessage(ValueError, "质量门禁工序尚未通过质检"):
            complete_operation_step(steps[2].id)

    def test_execution_event_is_idempotent(self):
        step = self.work_order.operation_steps.order_by("sequence_number").first()
        payload = {
            "external_id": "event-op-start-001",
            "source": "rcs-simulator",
            "event_type": "operation_step.started",
            "object_id": str(step.id),
        }
        event, duplicate = ingest_execution_event(payload)
        self.assertFalse(duplicate)
        self.assertEqual(event.status, ExecutionEvent.Status.PROCESSED)
        duplicate_event, duplicate = ingest_execution_event(payload)
        self.assertTrue(duplicate)
        self.assertEqual(duplicate_event.id, event.id)
        self.assertEqual(ExecutionEvent.objects.count(), 1)


class OperationsApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.site = Site.objects.create(code="S1", name="一号车间")
        self.product = Product.objects.create(code="P1", name="测试产品")

    def test_create_and_query_work_order(self):
        response = self.client.post(
            "/api/v1/operations/work-orders/",
            {
                "title": "API 工单",
                "site": self.site.id,
                "product": self.product.id,
                "quantity": 8,
            },
            format="json",
            HTTP_X_OPERATOR="tester",
        )
        self.assertEqual(response.status_code, 201, response.data)
        work_order_id = response.data["id"]
        detail = self.client.get(f"/api/v1/operations/work-orders/{work_order_id}/timeline/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["work_order"]["order_no"], response.data["order_no"])
        self.assertGreaterEqual(len(detail.data["events"]), 1)

    def test_command_center_aggregates_work_orders(self):
        WorkOrder.objects.create(title="驾驶舱工单", site=self.site, product=self.product)
        response = self.client.get("/api/v1/operations/command-center/")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.data["kpis"]["work_order_total"], 1)
