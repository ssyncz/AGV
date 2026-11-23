from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from Orders.models import Customer, Order, OrderEvent
from Operations.models import WorkOrder
from SchedulingDecision.models import (
    AGV,
    DispatchRecord,
    MapEdge,
    MapNode,
    MapObstacle,
    ProductionPlan,
    ScheduleRun,
    TransportTask,
)


GRID_COLS = 12
GRID_ROWS = 8
CELL_SIZE = 4.0

OBSTACLES = [
    ("O01", "障碍区 01", 1, 1, 2, 1),
    ("O02", "障碍区 02", 4, 0, 1, 2),
    ("O03", "障碍区 03", 7, 1, 2, 1),
    ("O04", "障碍区 04", 10, 1, 1, 2),
    ("O05", "障碍区 05", 2, 3, 2, 1),
    ("O06", "障碍区 06", 5, 3, 1, 2),
    ("O07", "障碍区 07", 8, 3, 2, 1),
    ("O08", "障碍区 08", 1, 5, 2, 1),
    ("O09", "障碍区 09", 4, 6, 2, 1),
    ("O10", "障碍区 10", 8, 6, 2, 1),
]

STATIONS = {
    "CHARGE": {"name": "充电区", "node_type": "charging", "x": 0, "y": 0},
    "S1": {"name": "工作站 S1", "node_type": "dropoff", "x": 11, "y": 3},
    "S2": {"name": "工作站 S2", "node_type": "pickup", "x": 6, "y": 1},
    "S3": {"name": "工作站 S3", "node_type": "pickup", "x": 8, "y": 0},
    "S4": {"name": "工作站 S4", "node_type": "pickup", "x": 4, "y": 2},
    "S5": {"name": "工作站 S5", "node_type": "pickup", "x": 7, "y": 2},
    "S6": {"name": "工作站 S6", "node_type": "dropoff", "x": 4, "y": 4},
    "S7": {"name": "工作站 S7", "node_type": "dropoff", "x": 6, "y": 4},
    "S8": {"name": "工作站 S8", "node_type": "dropoff", "x": 9, "y": 4},
    "S9": {"name": "工作站 S9", "node_type": "dropoff", "x": 1, "y": 6},
    "S10": {"name": "工作站 S10", "node_type": "pickup", "x": 2, "y": 7},
    "HOME1": {"name": "停车区 1", "node_type": "parking", "x": 11, "y": 7},
    "HOME2": {"name": "停车区 2", "node_type": "parking", "x": 0, "y": 7},
    "HOME3": {"name": "停车区 3", "node_type": "parking", "x": 11, "y": 0},
}

TASK_TEMPLATES = [
    ("S2", "S6", "电子元件箱", 35, 3),
    ("S3", "S8", "汽车零部件", 70, 4),
    ("S10", "S1", "成品包装箱", 45, 2),
    ("S4", "S7", "原料托盘", 95, 3),
    ("S5", "S9", "质检样品", 18, 1),
    ("S9", "S1", "装配工装", 60, 2),
    ("S6", "S2", "周转空箱", 12, 1),
    ("S8", "S3", "成品组件", 82, 4),
    ("S1", "S10", "紧急线束", 55, 4),
    ("S7", "S4", "补料托盘", 40, 2),
    ("S9", "S5", "检测工装", 22, 3),
    ("S1", "S9", "包装材料", 64, 2),
    ("S10", "S6", "电机组件", 88, 3),
    ("S2", "S8", "传感器盒", 28, 2),
    ("S3", "S1", "精密齿轮", 48, 4),
    ("S5", "S7", "工装夹具", 33, 1),
    ("S4", "S9", "钢板样件", 105, 3),
    ("S8", "S10", "成品机箱", 75, 2),
    ("S6", "S1", "回收托盘", 20, 1),
    ("S7", "S3", "装配零件", 52, 4),
]

CUSTOMER_TEMPLATES = [
    ("张伟", "13800000001"),
    ("李娜", "13900000002"),
    ("王磊", "13700000003"),
    ("赵敏", "13600000004"),
    ("陈晨", "13500000005"),
]


def build_task_specs(count):
    """按固定模板生成可重复的演示任务。"""
    specs = []
    for index in range(count):
        pickup, dropoff, cargo, weight, priority = TASK_TEMPLATES[
            index % len(TASK_TEMPLATES)
        ]
        specs.append(
            (f"TASK-DEMO-{index + 1:03d}", pickup, dropoff, cargo, weight, priority)
        )
    return specs


def upsert_demo_tasks(task_specs, station_node):
    """写入一一对应的演示订单和运输任务。"""
    for index, (task_no, pickup, dropoff, cargo, weight, priority) in enumerate(
        task_specs, start=1
    ):
        task, _ = TransportTask.objects.update_or_create(
            task_no=task_no,
            defaults={
                "pickup_node": station_node(pickup),
                "dropoff_node": station_node(dropoff),
                "cargo_name": cargo,
                "cargo_weight": weight,
                "priority": priority,
                "status": TransportTask.Status.PENDING,
                "assigned_agv": None,
                "schedule_run": None,
                "sequence_number": 0,
                "planned_wait_seconds": 0,
                "optimization_details": {},
                "route": {},
                "total_distance": 0,
                "estimated_duration": 0,
                "scheduled_start": None,
                "scheduled_end": None,
                "started_at": None,
                "completed_at": None,
                "notes": "",
            },
        )
        customer_name, customer_phone = CUSTOMER_TEMPLATES[
            (index - 1) % len(CUSTOMER_TEMPLATES)
        ]
        customer, _ = Customer.objects.get_or_create(
            phone=customer_phone,
            defaults={"name": customer_name},
        )
        order_no = f"ORD-DEMO-{index:03d}"
        order, _ = Order.objects.update_or_create(
            order_no=order_no,
            defaults={
                "customer": customer,
                "cargo_name": cargo,
                "cargo_weight": weight,
                "pickup_node": station_node(pickup),
                "dropoff_node": station_node(dropoff),
                "priority": priority,
                "notes": "",
                "status": TransportTask.Status.PENDING,
            },
        )
        if task.order_id != order.id:
            task.order = order
            task.save(update_fields=["order"])
        OrderEvent.objects.filter(order=order).delete()
        OrderEvent.objects.create(
            order=order,
            event_type=OrderEvent.EventType.CREATED,
            to_status=TransportTask.Status.PENDING,
            title="订单已创建",
            description="演示订单已提交，等待安排运输。",
        )


class Command(BaseCommand):
    help = "初始化 AGV 调度演示数据（障碍地图、AGV、任务和管理员）"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="清空业务数据后重新初始化")
        parser.add_argument(
            "--reset-tasks",
            action="store_true",
            help="仅清空调度任务、调度记录和优化记录，保留地图与 AGV 基础数据",
        )
        parser.add_argument(
            "--task-count",
            type=int,
            default=6,
            help="生成的待调度演示任务数量（默认 6）",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        task_count = options["task_count"]
        if task_count < 1:
            raise CommandError("--task-count 必须大于 0。")

        if options["reset"]:
            DispatchRecord.objects.all().delete()
            TransportTask.objects.all().delete()
            ScheduleRun.objects.all().delete()
            OrderEvent.objects.all().delete()
            Order.objects.all().delete()
            Customer.objects.all().delete()
            ProductionPlan.objects.all().delete()
            WorkOrder.objects.all().delete()
            AGV.objects.all().delete()
            MapEdge.objects.all().delete()
            MapObstacle.objects.all().delete()
            MapNode.objects.all().delete()
        elif options["reset_tasks"]:
            DispatchRecord.objects.all().delete()
            TransportTask.objects.all().delete()
            ScheduleRun.objects.all().delete()
            OrderEvent.objects.all().delete()
            Order.objects.all().delete()
            ProductionPlan.objects.all().delete()
            WorkOrder.objects.all().delete()
            AGV.objects.update(status=AGV.Status.IDLE)

            required_codes = {
                code for template in TASK_TEMPLATES for code in template[:2]
            }
            station_nodes = {
                node.code: node
                for node in MapNode.objects.filter(code__in=required_codes)
            }
            missing_codes = sorted(required_codes - station_nodes.keys())
            if missing_codes:
                raise CommandError(
                    "缺少调度基础数据，请先执行 seed_demo --reset："
                    + ", ".join(missing_codes)
                )

            task_specs = build_task_specs(task_count)
            upsert_demo_tasks(task_specs, station_nodes.__getitem__)
            self.stdout.write(self.style.SUCCESS(
                f"调度任务已重建：待调度任务 "
                f"{TransportTask.objects.filter(status='pending').count()} 个，"
                f"演示订单 {Order.objects.count()} 个；"
                "地图与 AGV 位置、电量保持不变，AGV 状态已重置为空闲。"
            ))
            return

        blocked = set()
        for _code, _name, x, y, width, height in OBSTACLES:
            for col in range(int(x), int(x + width)):
                for row in range(int(y), int(y + height)):
                    blocked.add((col, row))
            MapObstacle.objects.update_or_create(
                code=_code,
                defaults={
                    "name": _name,
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                    "is_active": True,
                },
            )

        station_by_position = {
            (item["x"], item["y"]): (code, item)
            for code, item in STATIONS.items()
        }
        node_map = {}
        for col in range(GRID_COLS):
            for row in range(GRID_ROWS):
                if (col, row) in blocked:
                    continue
                station = station_by_position.get((col, row))
                if station:
                    code, item = station
                    name = item["name"]
                    node_type = item["node_type"]
                else:
                    code = f"G{col:02d}{row:02d}"
                    name = f"路径节点 {col}-{row}"
                    node_type = MapNode.NodeType.INTERSECTION
                node, _ = MapNode.objects.update_or_create(
                    code=code,
                    defaults={
                        "name": name,
                        "node_type": node_type,
                        "x": col,
                        "y": row,
                        "is_active": True,
                    },
                )
                node_map[(col, row)] = node

        for (col, row), node in node_map.items():
            for next_col, next_row in ((col + 1, row), (col, row + 1)):
                next_node = node_map.get((next_col, next_row))
                if next_node is None:
                    continue
                MapEdge.objects.update_or_create(
                    start_node=node,
                    end_node=next_node,
                    defaults={
                        "distance": CELL_SIZE,
                        "speed_limit": 1.2,
                        "bidirectional": True,
                        "is_active": True,
                    },
                )

        def station_node(code):
            item = STATIONS[code]
            return node_map[(item["x"], item["y"])]

        agv_specs = [
            ("AGV-01", "天马一号", "T1-100", "CHARGE", 96, 120, 1.2),
            ("AGV-02", "天马二号", "T1-100", "S2", 88, 120, 1.1),
            ("AGV-03", "天马三号", "T2-150", "S3", 73, 150, 1.4),
            ("AGV-04", "天马四号", "T2-150", "S10", 64, 150, 1.35),
        ]
        for code, name, model_name, node_code, battery, capacity, speed in agv_specs:
            AGV.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "model_name": model_name,
                    "current_node": station_node(node_code),
                    "battery_percent": battery,
                    "payload_capacity": capacity,
                    "speed": speed,
                    "status": AGV.Status.IDLE,
                },
            )

        task_specs = build_task_specs(task_count)
        upsert_demo_tasks(task_specs, station_node)

        User = get_user_model()
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@example.com", "Admin123!")
            self.stdout.write(self.style.SUCCESS("已创建管理员 admin / Admin123!"))
        else:
            self.stdout.write("管理员 admin 已存在，未修改密码。")

        self.stdout.write(self.style.SUCCESS(
            f"演示数据初始化完成：节点 {MapNode.objects.count()}，道路 {MapEdge.objects.count()}，"
            f"障碍 {MapObstacle.objects.count()}，AGV {AGV.objects.count()}，"
            f"待调度任务 {TransportTask.objects.filter(status='pending').count()}"
            f"（本次生成 {len(task_specs)}），订单 {Order.objects.count()}"
        ))
