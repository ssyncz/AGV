from datetime import datetime, time, timedelta

from django.db import migrations
from django.utils import timezone


def backfill_operation_steps(apps, schema_editor):
    Site = apps.get_model("Operations", "Site")
    WorkCalendar = apps.get_model("Operations", "WorkCalendar")
    WorkOrder = apps.get_model("Operations", "WorkOrder")
    OperationStep = apps.get_model("Operations", "OperationStep")
    TransportTask = apps.get_model("SchedulingDecision", "TransportTask")

    for site in Site.objects.all().iterator():
        WorkCalendar.objects.get_or_create(
            site=site,
            name="默认白班",
            defaults={
                "weekdays": [1, 2, 3, 4, 5],
                "shift_start": time(8, 0),
                "shift_end": time(18, 0),
                "is_active": True,
            },
        )

    definitions = [
        (10, "OP-010", "物料配送", "logistics", 60, False),
        (20, "OP-020", "生产加工", "production", 120, False),
        (30, "OP-030", "质量检验", "quality", 30, True),
        (40, "OP-040", "完工入库", "warehouse", 30, False),
    ]
    for work_order in WorkOrder.objects.all().iterator():
        if OperationStep.objects.filter(work_order_id=work_order.id).exists():
            continue
        start = timezone.now().replace(second=0, microsecond=0)
        steps = []
        for index, (sequence, code, name, step_type, minutes, quality_gate) in enumerate(
            definitions
        ):
            end = start + timedelta(minutes=minutes)
            steps.append(
                OperationStep(
                    work_order_id=work_order.id,
                    sequence_number=sequence,
                    code=code,
                    name=name,
                    step_type=step_type,
                    standard_duration_minutes=minutes,
                    planned_start=start,
                    planned_end=end,
                    status=(
                        "ready"
                        if index == 0
                        and work_order.status
                        in ["released", "in_progress", "quality_check", "blocked"]
                        else "pending"
                    ),
                    quality_gate=quality_gate,
                )
            )
            start = end
        OperationStep.objects.bulk_create(steps)
        logistics = OperationStep.objects.filter(
            work_order_id=work_order.id, step_type="logistics"
        ).first()
        if logistics:
            TransportTask.objects.filter(
                work_order_id=work_order.id, operation_step__isnull=True
            ).update(operation_step=logistics)


class Migration(migrations.Migration):

    dependencies = [
        ("Operations", "0002_operationstep_executionevent_workcalendar_and_more"),
        ("SchedulingDecision", "0010_transporttask_operation_step_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_operation_steps, migrations.RunPython.noop),
    ]
