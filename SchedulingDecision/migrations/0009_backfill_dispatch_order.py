from django.db import migrations


def backfill_dispatch_order(apps, schema_editor):
    TransportTask = apps.get_model("SchedulingDecision", "TransportTask")
    keys = set(
        TransportTask.objects.exclude(production_plan__isnull=True)
        .values_list("production_plan_id", flat=True)
        .distinct()
    )
    for plan_id in keys:
        tasks = TransportTask.objects.filter(production_plan_id=plan_id).order_by(
            "scheduled_start", "sequence_number", "created_at", "id"
        )
        for order, task in enumerate(tasks, start=1):
            if task.schedule_run_id and task.dispatch_order != order:
                task.dispatch_order = order
                task.save(update_fields=["dispatch_order"])


class Migration(migrations.Migration):

    dependencies = [
        ("SchedulingDecision", "0008_transporttask_dispatch_order"),
    ]

    operations = [
        migrations.RunPython(backfill_dispatch_order, migrations.RunPython.noop),
    ]
