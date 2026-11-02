from django.db import migrations
def renumber_dispatch_order(apps, schema_editor):
    TransportTask = apps.get_model("SchedulingDecision", "TransportTask")
    work_order_ids = (
        TransportTask.objects.exclude(work_order__isnull=True)
        .values_list("work_order_id", flat=True)
        .distinct()
    )
    for work_order_id in work_order_ids:
        tasks = TransportTask.objects.filter(
            work_order_id=work_order_id,
            schedule_run__isnull=False,
        ).exclude(status="cancelled").order_by(
            "scheduled_start", "dispatch_order", "sequence_number", "id"
        )
        for order, task in enumerate(tasks, start=1):
            if task.dispatch_order != order:
                task.dispatch_order = order
                task.save(update_fields=["dispatch_order"])

    plan_ids = (
        TransportTask.objects.filter(
            work_order__isnull=True,
            production_plan__isnull=False,
            schedule_run__isnull=False,
        )
        .values_list("production_plan_id", flat=True)
        .distinct()
    )
    for plan_id in plan_ids:
        tasks = TransportTask.objects.filter(
            production_plan_id=plan_id,
            work_order__isnull=True,
            schedule_run__isnull=False,
        ).exclude(status="cancelled").order_by(
            "scheduled_start", "dispatch_order", "sequence_number", "id"
        )
        for order, task in enumerate(tasks, start=1):
            if task.dispatch_order != order:
                task.dispatch_order = order
                task.save(update_fields=["dispatch_order"])


class Migration(migrations.Migration):

    dependencies = [
        ("SchedulingDecision", "0010_transporttask_operation_step_and_more"),
    ]

    operations = [
        migrations.RunPython(renumber_dispatch_order, migrations.RunPython.noop),
    ]
