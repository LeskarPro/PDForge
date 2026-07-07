# Stage 8a REWORK data migration. For each existing Firm row (still
# Client-linked at this point, per 0037-0039), create a SiteFirm link to
# every one of that client's sites, carrying over the firm's is_active/
# start_date/end_date — this is the best available approximation, since
# there was no per-site firm history before this rework either.
#
# Also copies Protocol.snapshot_client_* (frozen by 0038) into the new
# snapshot_firm_* fields added in 0040 — a straight value copy, no
# re-derivation needed since the old snapshot already holds the right data.

from django.db import migrations


def migrate_forward(apps, schema_editor):
    Firm = apps.get_model("core", "Firm")
    SiteFirm = apps.get_model("core", "SiteFirm")
    Protocol = apps.get_model("core", "Protocol")

    for firm in Firm.objects.filter(client_id__isnull=False):
        for site in firm.client.sites.all():
            SiteFirm.objects.create(
                site=site, firm=firm,
                is_active=firm.is_active,
                start_date=firm.start_date,
                end_date=firm.end_date,
            )

    protocols = list(Protocol.objects.all())
    for p in protocols:
        p.snapshot_firm_name = p.snapshot_client_firm_name
        p.snapshot_firm_eik = p.snapshot_client_eik
        p.snapshot_firm_address = p.snapshot_client_address
        p.snapshot_firm_phone = p.snapshot_client_phone
    if protocols:
        Protocol.objects.bulk_update(
            protocols,
            ["snapshot_firm_name", "snapshot_firm_eik",
             "snapshot_firm_address", "snapshot_firm_phone"],
            batch_size=200,
        )


def migrate_backward(apps, schema_editor):
    # Best-effort only — delete the SiteFirm rows this created and clear
    # the new snapshot fields. The old snapshot_client_* / Firm.client data
    # this was copied FROM is untouched by this migration, so reversing
    # 0041 alone doesn't lose anything (0040/0039 etc. handle the rest).
    SiteFirm = apps.get_model("core", "SiteFirm")
    Protocol = apps.get_model("core", "Protocol")
    SiteFirm.objects.all().delete()
    protocols = list(Protocol.objects.all())
    for p in protocols:
        p.snapshot_firm_name = ""
        p.snapshot_firm_eik = ""
        p.snapshot_firm_address = ""
        p.snapshot_firm_phone = ""
    if protocols:
        Protocol.objects.bulk_update(
            protocols,
            ["snapshot_firm_name", "snapshot_firm_eik",
             "snapshot_firm_address", "snapshot_firm_phone"],
            batch_size=200,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0040_sitefirm_protocol_snapshot_rename"),
    ]

    operations = [
        migrations.RunPython(migrate_forward, migrate_backward),
    ]
