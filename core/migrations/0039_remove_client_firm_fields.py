# Stage 8a — remove the old firm/eik/address/phone fields off Client now
# that 0038 has copied everything onto Firm + Protocol snapshots.
#
# IMPORTANT (2026-06-21): already applied for real against Kiril's live
# db_old.sqlite3 — do not edit. See the note in 0037 for the full story; the
# bridge to the later Firm-on-Site rework is in 0040-0042.
#
# Each RemoveField is preceded by an AlterField giving the field an explicit
# default="" — RemoveField's reverse (re-adding the column on a rollback)
# needs a default to backfill existing rows, and `address` in particular
# never had blank=True/default originally, which made a bare reverse crash
# with a NOT NULL constraint error (verified against a throwaway DB copy).
# Giving all four an explicit default here keeps `migrate core <earlier>`
# safe to run, even though this is in practice a one-way upgrade.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0038_backfill_firm_site_dates_protocol_snapshot"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="client",
            name="unique_client_eik_nonempty",
        ),
        migrations.AlterField(
            model_name="client", name="firm",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="Фирма"),
        ),
        migrations.AlterField(
            model_name="client", name="eik",
            field=models.CharField(blank=True, default="", max_length=9, verbose_name="ЕИК"),
        ),
        migrations.AlterField(
            model_name="client", name="address",
            field=models.CharField(blank=True, default="", max_length=500, verbose_name="Адрес"),
        ),
        migrations.AlterField(
            model_name="client", name="phone",
            field=models.CharField(blank=True, default="", max_length=20, verbose_name="Телефон"),
        ),
        migrations.RemoveField(model_name="client", name="firm"),
        migrations.RemoveField(model_name="client", name="eik"),
        migrations.RemoveField(model_name="client", name="address"),
        migrations.RemoveField(model_name="client", name="phone"),
    ]
