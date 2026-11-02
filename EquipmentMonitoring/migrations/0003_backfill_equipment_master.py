from django.db import migrations


def backfill_equipment_master(apps, schema_editor):
    Site = apps.get_model("Operations", "Site")
    Equipment = apps.get_model("Operations", "Equipment")
    Diagnosis = apps.get_model("EquipmentMonitoring", "EquipmentDiagnosisRecord")

    site, _ = Site.objects.get_or_create(
        code="SITE-01",
        defaults={"name": "默认制造站点", "location": "迁移自动创建"},
    )
    for record in Diagnosis.objects.filter(equipment__isnull=True).iterator():
        equipment, _ = Equipment.objects.get_or_create(
            code=record.equipment_code,
            defaults={"name": record.equipment_code, "site": site},
        )
        record.equipment = equipment
        record.save(update_fields=["equipment"])


class Migration(migrations.Migration):

    dependencies = [
        ("EquipmentMonitoring", "0002_equipmentdiagnosisrecord_equipment_and_more"),
        ("Operations", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_equipment_master, migrations.RunPython.noop),
    ]
