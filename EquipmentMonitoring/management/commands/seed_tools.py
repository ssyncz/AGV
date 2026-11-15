"""初始化一把在机刀具（演示用）：CNC-01 装 T-001，磨损 0.82。

    python manage.py seed_tools
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from EquipmentMonitoring.models import Tool
from Operations.models import Equipment


class Command(BaseCommand):
    help = "初始化刀具演示数据（CNC-01 装 T-001）"

    def add_arguments(self, parser):
        parser.add_argument("--wear", type=float, default=0.82, help="初始磨损率 0-1")
        parser.add_argument("--used", type=float, default=196.0, help="累计切削分钟")

    def handle(self, *args, **options):
        equipment = Equipment.objects.filter(code="CNC-01").first()
        if equipment is None:
            raise CommandError("找不到设备 CNC-01，请先运行 seed_demo")

        metadata = dict(equipment.metadata or {})
        metadata.setdefault("map_node", "S6")
        equipment.metadata = metadata
        equipment.save(update_fields=["metadata", "updated_at"])

        # 刀具库也是一条设备档案：它的 map_node 就是配送起点
        crib, _ = Equipment.objects.update_or_create(
            code="TOOL-CRIB",
            defaults={
                "name": "刀具库",
                "equipment_type": "tool_crib",
                "site": equipment.site,
                "status": Equipment.Status.NORMAL,
                "metadata": {"map_node": "S10"},
            },
        )

        tool, created = Tool.objects.update_or_create(
            code="T-001",
            defaults={
                "name": "硬质合金立铣刀 Φ10",
                "equipment": equipment,
                "wear_ratio": options["wear"],
                "threshold": 0.78,
                "life_minutes": 240.0,
                "used_minutes": options["used"],
                "status": Tool.Status.IN_USE,
                "changed_at": timezone.now(),
                "notes": "演示刀具：来自设备监测的磨损信号",
            },
        )
        second, _ = Tool.objects.get_or_create(
            code="T-002",
            defaults={
                "name": "备用铣刀 Φ10（库存）",
                "equipment": None,
                "wear_ratio": 0.0,
                "life_minutes": 240.0,
                "used_minutes": 0.0,
                "status": Tool.Status.IN_USE,
                "notes": "刀具库备用",
            },
        )

        self.stdout.write(self.style.SUCCESS(
            f"{'创建' if created else '更新'} {tool.code}：磨损 {tool.wear_ratio:.2f}，"
            f"剩余 {tool.remaining_minutes:.0f} 分钟，设备 {equipment.code}（站点 {metadata['map_node']}）"
        ))
        self.stdout.write(f"备用刀 {second.code} 就绪")
