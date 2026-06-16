from django.db import migrations


def create_default_company(apps, schema_editor):
    Company = apps.get_model("core", "Company")
    Protocol = apps.get_model("core", "Protocol")
    company, _ = Company.objects.get_or_create(
        eik="202719904",
        defaults={
            "name": "Саниста ВИП СС ООД",
            "address": 'гр.София, ул."Нишава", №58, ет.1, ап.6',
            "phone": "0888 61 47 46, 0888 28 24 90",
            "slogan": "Вашият избор за спокойствие и уют!",
            "is_default": True,
            "is_active": True,
        },
    )
    Protocol.objects.filter(company__isnull=True).update(
        company=company,
        snapshot_company_name=company.name,
        snapshot_company_eik=company.eik,
        snapshot_company_address=company.address,
        snapshot_company_phone=company.phone,
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0016_company_protocol_snapshot_company_address_and_more"),
    ]
    operations = [
        migrations.RunPython(create_default_company, noop),
    ]