from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from SchedulingDecision.models import AGV, MapNode, TransportTask

from .models import Customer, Order, OrderEvent
from .services import create_order


class OrderAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", "--reset", verbosity=0)

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.host = {"HTTP_HOST": "localhost"}
        self.pickup = MapNode.objects.get(code="S2")
        self.dropoff = MapNode.objects.get(code="S6")

    def payload(self, **overrides):
        data = {
            "customer_name": "测试客户",
            "customer_phone": "13812345678",
            "cargo_name": "测试货物",
            "cargo_weight": 24.5,
            "pickup_node": self.pickup.id,
            "dropoff_node": self.dropoff.id,
            "priority": TransportTask.Priority.NORMAL,
            "notes": "接口测试订单",
        }
        data.update(overrides)
        return data

    def create_order_via_api(self, **overrides):
        response = self.client.post(
            "/api/orders/",
            self.payload(**overrides),
            format="json",
            **self.host,
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def test_create_order_atomically_creates_customer_task_and_event(self):
        response = self.create_order_via_api()
        order = Order.objects.get(pk=response.data["id"])
        self.assertTrue(order.order_no.startswith("ORD-"))
        self.assertEqual(order.customer.phone, "13812345678")
        self.assertEqual(order.transport_task.status, TransportTask.Status.PENDING)
        self.assertEqual(order.events.count(), 1)
        self.assertEqual(order.events.first().event_type, OrderEvent.EventType.CREATED)
        self.assertEqual(response.data["transport_task"]["id"], order.transport_task.id)

    def test_existing_customer_is_reused_by_normalized_phone(self):
        self.create_order_via_api(customer_phone="138-1234 5678")
        self.create_order_via_api(cargo_name="第二单")
        self.assertEqual(Customer.objects.filter(phone="13812345678").count(), 1)
        self.assertEqual(
            Order.objects.filter(customer__phone="13812345678").count(),
            2,
        )

    def test_create_validation_rejects_same_node_and_invalid_phone(self):
        same_node = self.client.post(
            "/api/orders/",
            self.payload(dropoff_node=self.pickup.id),
            format="json",
            **self.host,
        )
        bad_phone = self.client.post(
            "/api/orders/",
            self.payload(customer_phone="12345"),
            format="json",
            **self.host,
        )
        self.assertEqual(same_node.status_code, 400)
        self.assertEqual(bad_phone.status_code, 400)
        self.assertEqual(Order.objects.filter(order_no__startswith="ORD-DEMO").count(), 6)

    def test_list_supports_search_and_status_filter(self):
        created = self.create_order_via_api(cargo_name="唯一检索货物")
        response = self.client.get(
            "/api/orders/?search=唯一检索货物&status=pending",
            **self.host,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], created.data["id"])

    def test_pending_order_can_be_updated_and_cannot_be_deleted(self):
        created = self.create_order_via_api()
        url = f"/api/orders/{created.data['id']}/"
        response = self.client.patch(
            url,
            {"cargo_name": "修改后的货物", "cargo_weight": 30},
            format="json",
            **self.host,
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["cargo_name"], "修改后的货物")
        self.assertEqual(response.data["transport_task"]["id"], created.data["transport_task"]["id"])
        self.assertEqual(
            TransportTask.objects.get(pk=created.data["transport_task"]["id"]).cargo_name,
            "修改后的货物",
        )
        self.assertEqual(self.client.delete(url, **self.host).status_code, 405)

    def test_schedule_start_and_complete_project_status_to_order(self):
        created = self.create_order_via_api()
        order_id = created.data["id"]
        task_id = created.data["transport_task"]["id"]

        schedule = self.client.post(
            "/api/schedules/single/",
            {"task_ids": [task_id]},
            format="json",
            **self.host,
        )
        self.assertEqual(schedule.status_code, 200, schedule.data)
        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.status, TransportTask.Status.ASSIGNED)

        start = self.client.post(f"/api/tasks/{task_id}/start/", {}, format="json", **self.host)
        self.assertEqual(start.status_code, 200, start.data)
        order.refresh_from_db()
        self.assertEqual(order.status, TransportTask.Status.IN_PROGRESS)

        complete = self.client.post(
            f"/api/tasks/{task_id}/complete/", {}, format="json", **self.host
        )
        self.assertEqual(complete.status_code, 200, complete.data)
        order.refresh_from_db()
        self.assertEqual(order.status, TransportTask.Status.COMPLETED)
        self.assertEqual(
            list(order.events.values_list("event_type", flat=True)),
            [
                OrderEvent.EventType.CREATED,
                OrderEvent.EventType.SCHEDULED,
                OrderEvent.EventType.STARTED,
                OrderEvent.EventType.COMPLETED,
            ],
        )

    def test_assigned_order_is_read_only_and_can_be_cancelled(self):
        created = self.create_order_via_api()
        order_id = created.data["id"]
        task_id = created.data["transport_task"]["id"]
        self.client.post(
            "/api/schedules/single/",
            {"task_ids": [task_id]},
            format="json",
            **self.host,
        )
        patch = self.client.patch(
            f"/api/orders/{order_id}/",
            {"cargo_name": "不应修改"},
            format="json",
            **self.host,
        )
        self.assertEqual(patch.status_code, 400)

        cancel = self.client.post(f"/api/orders/{order_id}/cancel/", {}, format="json", **self.host)
        self.assertEqual(cancel.status_code, 200, cancel.data)
        self.assertEqual(cancel.data["status"], TransportTask.Status.CANCELLED)
        task = TransportTask.objects.get(pk=task_id)
        self.assertEqual(task.status, TransportTask.Status.CANCELLED)

    def test_public_lookup_requires_matching_tail_and_masks_private_fields(self):
        created = self.create_order_via_api(customer_phone="13987654321")
        order_no = created.data["order_no"]
        success = self.client.post(
            "/api/orders/lookup/",
            {"order_no": order_no, "phone_tail": "4321"},
            format="json",
            **self.host,
        )
        wrong_tail = self.client.post(
            "/api/orders/lookup/",
            {"order_no": order_no, "phone_tail": "0000"},
            format="json",
            **self.host,
        )
        invalid_tail = self.client.post(
            "/api/orders/lookup/",
            {"order_no": order_no, "phone_tail": "12a4"},
            format="json",
            **self.host,
        )
        self.assertEqual(success.status_code, 200, success.data)
        self.assertEqual(success.data["customer_phone"], "139****4321")
        self.assertNotIn("id", success.data)
        self.assertNotIn("transport_task", success.data)
        self.assertNotIn("assigned_agv_code", str(success.data))
        self.assertEqual(wrong_tail.status_code, 404)
        self.assertEqual(invalid_tail.status_code, 400)

    def test_public_lookup_is_rate_limited(self):
        created = self.create_order_via_api()
        body = {
            "order_no": created.data["order_no"],
            "phone_tail": "0000",
        }
        statuses = [
            self.client.post(
                "/api/orders/lookup/", body, format="json", **self.host
            ).status_code
            for _ in range(21)
        ]
        self.assertEqual(statuses[:20], [404] * 20)
        self.assertEqual(statuses[20], 429)

    def test_overview_exposes_order_todo_counts(self):
        self.create_order_via_api()
        response = self.client.get("/api/overview/", **self.host)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["order_total"], 7)
        self.assertEqual(response.data["order_status_counts"]["pending"], 7)
        self.assertEqual(response.data["today_order_count"], 7)


class OrderServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", "--reset", verbosity=0)

    def test_legacy_transport_task_remains_unlinked(self):
        task = TransportTask.objects.create(
            task_no="TASK-LEGACY-001",
            pickup_node=MapNode.objects.get(code="S4"),
            dropoff_node=MapNode.objects.get(code="S7"),
            cargo_name="历史任务",
            cargo_weight=10,
        )
        self.assertIsNone(task.order)

    def test_create_order_service_uses_generated_unique_order_numbers(self):
        pickup = MapNode.objects.get(code="S2")
        dropoff = MapNode.objects.get(code="S6")
        first = create_order(
            customer_name="甲",
            customer_phone="13700001111",
            cargo_name="货物甲",
            cargo_weight=3,
            pickup_node=pickup,
            dropoff_node=dropoff,
        )
        second = create_order(
            customer_name="乙",
            customer_phone="13700002222",
            cargo_name="货物乙",
            cargo_weight=4,
            pickup_node=pickup,
            dropoff_node=dropoff,
        )
        self.assertNotEqual(first.order_no, second.order_no)
        self.assertTrue(first.transport_task.task_no.startswith("TASK-ORD-"))

    def test_demo_orders_and_single_creation_events_are_repeatable(self):
        call_command("seed_demo", "--reset-tasks", "--task-count", "3", verbosity=0)
        call_command("seed_demo", "--reset-tasks", "--task-count", "3", verbosity=0)
        self.assertEqual(Order.objects.count(), 3)
        self.assertEqual(OrderEvent.objects.count(), 3)
        self.assertEqual(
            TransportTask.objects.filter(order__isnull=False).count(),
            3,
        )
        self.assertTrue(
            OrderEvent.objects.filter(event_type=OrderEvent.EventType.CREATED).exists()
        )
