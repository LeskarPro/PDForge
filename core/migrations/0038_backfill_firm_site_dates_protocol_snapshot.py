# Stage 8a/8b data backfill. Runs after 0037 (which added the new columns)
# and before 0039 (which removes the old Client.firm/eik/address/phone
# columns this migration still needs to read).
#
# IMPORTANT (2026-06-21): already applied for real against Kiril's live
# db_old.sqlite3 — do not edit. See the note in 0037 for the full story; the
# bridge to the later Firm-on-Site rework is in 0040-0042.

from django.db import migrations


def migrate_data_forward(apps, schema_editor):
    Client = apps.get_model("core", "Client")
    Firm = apps.get_model("core", "Firm")
    Site = apps.get_model("core", "Site")
    Protocol = apps.get_model("core", "Protocol")

    # One Firm per existing Client, carrying over its current firm/EIK/
    # address/phone — the best available history, since there was no
    # separate firm record before this migration. start_date uses the
    # client's own creation month rather than today.
    for client in Client.objects.all():
        Firm.objects.create(
            client=client,
            name=client.firm, eik=client.eik,
            address=client.address, phone=client.phone,
            is_active=True,
            start_date=client.created_at.date().replace(day=1),
            end_date=None,
        )

    # Existing sites: keep them active, but set start_date to each site's
    # own creation month rather than the date this migration happened to run
    # (0037's AddField default would otherwise stamp every row with today).
    sites = list(Site.objects.all())
    for site in sites:
        site.is_active = True
        site.start_date = site.created_at.date().replace(day=1)
    if sites:
        Site.objects.bulk_update(sites, ["is_active", "start_date"])

    # Freeze each existing protocol's client-firm snapshot from the data
    # that's about to be removed off Client (Stage 8a) — same idea as the
    # pre-existing company snapshot, applied retroactively so old protocols
    # keep showing what was printed at the time.
    protocols = list(Protocol.objects.select_related("client").all())
    for p in protocols:
        if p.client_id:
            p.snapshot_client_firm_name = p.client.firm
            p.snapshot_client_eik = p.client.eik
            p.snapshot_client_address = p.client.address
            p.snapshot_client_phone = p.client.phone
    if protocols:
        Protocol.objects.bulk_update(
            protocols,
            ["snapshot_client_firm_name", "snapshot_client_eik",
             "snapshot_client_address", "snapshot_client_phone"],
            batch_size=200,
        )


def migrate_data_backward(apps, schema_editor):
    # Best-effort only (same precedent as 0034/0035/0036) — delete the Firm
    # rows this migration created and clear the protocol snapshots. Site
    # is_active/start_date are left as-is; there's nothing meaningful to
    # revert them to.
    Firm = apps.get_model("core", "Firm")
    Protocol = apps.get_model("core", "Protocol")
    Firm.objects.all().delete()
    protocols = list(Protocol.objects.all())
    for p in protocols:
        p.snapshot_client_firm_name = ""
        p.snapshot_client_eik = ""
        p.snapshot_client_address = ""
        p.snapshot_client_phone = ""
    if protocols:
        Protocol.objects.bulk_update(
            protocols,
            ["snapshot_client_firm_name", "snapshot_client_eik",
             "snapshot_client_address", "snapshot_client_phone"],
            batch_size=200,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0037_firm_site_active_dates_protocol_snapshot"),
    ]

    operations = [
        migrations.RunPython(migrate_data_forward, migrate_data_backward),
    ]
