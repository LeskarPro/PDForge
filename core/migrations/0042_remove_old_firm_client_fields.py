# Stage 8a REWORK cleanup — remove the old Firm.client/is_active/start_date/
# end_date fields (now superseded by SiteFirm) and the old Protocol
# snapshot_client_* fields (superseded by snapshot_firm_* from 0040/0041).
#
# Protocol's old snapshot fields get an explicit default="" via AlterField
# first, same safe-reverse pattern used in 0039 — they were originally
# added with blank=True but no explicit default, and a bare RemoveField's
# reverse needs one to backfill existing rows. Firm.is_active/start_date
# already have usable defaults; Firm.client/end_date are already nullable
# (the client FK was relaxed to null=True in 0040 for exactly this reason).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0041_backfill_sitefirm_from_old_firm"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="firm",
            options={
                "ordering": ["name"],
                "verbose_name": "Фирма",
                "verbose_name_plural": "Фирми",
            },
        ),
        migrations.AlterField(
            model_name="protocol", name="snapshot_client_firm_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AlterField(
            model_name="protocol", name="snapshot_client_eik",
            field=models.CharField(blank=True, default="", max_length=9),
        ),
        migrations.AlterField(
            model_name="protocol", name="snapshot_client_address",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AlterField(
            model_name="protocol", name="snapshot_client_phone",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.RemoveField(model_name="protocol", name="snapshot_client_firm_name"),
        migrations.RemoveField(model_name="protocol", name="snapshot_client_eik"),
        migrations.RemoveField(model_name="protocol", name="snapshot_client_address"),
        migrations.RemoveField(model_name="protocol", name="snapshot_client_phone"),
        migrations.RemoveField(model_name="firm", name="client"),
        migrations.RemoveField(model_name="firm", name="is_active"),
        migrations.RemoveField(model_name="firm", name="start_date"),
        migrations.RemoveField(model_name="firm", name="end_date"),
    ]
