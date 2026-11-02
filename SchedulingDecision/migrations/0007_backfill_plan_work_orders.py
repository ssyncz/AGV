from datetime import datetime, time

from django.db import migrations
from django.utils import timezone


def backfill_plan_work_orders(apps, schema_editor):
    Site = apps.get_model("Operations", "Site")
    Product = apps.get_model("Operations", "Product")
    WorkOrder = apps.get_model("Operations", "WorkOrder")
    OperationEvent = apps.get_model("Operations", "OperationEvent")
    ProductionPlan = apps.get_model("SchedulingDecision", "ProductionPlan")

    site, _ = Site.objects.get_or_create(
        code="SITE-01",
        defaults={"name": "默认制造站点", "location": "迁移自动创建"},
    )
    product, _ = Product.objects.get_or_create(
        code="PROD-01",
        defaults={"name": "默认产品", "specification": "迁移自动创建"},
    )

    for plan in ProductionPlan.objects.filter(work_order__isnull=True).iterator():
        due_at = timezone.make_aware(
            datetime.combine(plan.planning_end, time(hour=plan.due_hour or 18))
        )
        work_order = WorkOrder.objects.create(
            order_no=f"WO-LEGACY-{plan.id:06d}",
            title=f"{plan.name} · 历史执行工单",
            site=site,
            product=product,
            quantity=plan.forecast_order_total or plan.task_count,
            status="released",
            planned_start=plan.planning_start,
            due_at=due_at,
            released_at=timezone.now(),
            notes=f"由历史生产计划 {plan.plan_no} 自动回填。",
        )
        plan.work_order = work_order
        plan.save(update_fields=["work_order"])
        plan.tasks.update(work_order=work_order)
        OperationEvent.objects.create(
            work_order=work_order,
            aggregate_type="work_order",
            aggregate_id=work_order.id,
            event_type="work_order.backfilled",
            summary=f"历史生产计划 {plan.plan_no} 已关联执行工单",
            from_status="",
            to_status="released",
            actor="migration",
            payload={"plan_id": plan.id, "plan_no": plan.plan_no},
        )


class Migration(migrations.Migration):

    dependencies = [
        ("Operations", "0001_initial"),
        ("SchedulingDecision", "0006_productionplan_work_order_transporttask_work_order_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_plan_work_orders, migrations.RunPython.noop),
    ]
