# Stage 8a/8b — schema only (additive). See 0038 for the data backfill and
# 0039 for removing the old firm/eik/address/phone fields off Client — split
# into three migrations so the data migration can still read the old Client
# columns before they're dropped.
#
# IMPORTANT (2026-06-21): this migration's CONTENT must stay exactly as it
# was first written and applied — it is already applied for real against
# Kiril's live db_old.sqlite3 (apparently auto-applied by run_app.py's
# `call_command("migrate")` on an app launch during this same working
# session). The Firm-on-Client design here was superseded later the same
# day by a Firm-on-Site rework (see core/models.py) — that rework is
# expressed as NEW migrations 0040-0042 below, which bridge from this
# already-applied shape to the new one. Do not edit 0037-0039 again.

import uuid

import django.db.models.deletion
from django.db import migrations, models

import core.models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0036_richtext_notes_protocol_onetimetreatment"),
    ]

    operations = [
        migrations.CreateModel(
            name="Firm",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("name", models.CharField(max_length=255, verbose_name="Фирма")),
                ("eik", models.CharField(blank=True, max_length=9, verbose_name="ЕИК")),
                ("address", models.CharField(max_length=500, verbose_name="Адрес")),
                ("phone", models.CharField(blank=True, max_length=20, verbose_name="Телефон")),
                ("is_active", models.BooleanField(default=True, verbose_name="Активна")),
                ("start_date", models.DateField(default=core.models._first_of_this_month, verbose_name="Начална дата")),
                ("end_date", models.DateField(blank=True, null=True, verbose_name="Крайна дата")),
                ("client", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="firms", to="core.client", verbose_name="Клиент",
                )),
            ],
            options={
                "verbose_name": "Фирма (на клиент)",
                "verbose_name_plural": "Фирми (на клиенти)",
                "ordering": ["-is_active", "-start_date"],
            },
        ),
        migrations.AddConstraint(
            model_name="firm",
            constraint=models.UniqueConstraint(
                condition=models.Q(("eik__gt", "")),
                fields=("eik",),
                name="unique_firm_eik_nonempty",
            ),
        ),
        migrations.AddField(
            model_name="site",
            name="is_active",
            field=models.BooleanField(default=True, verbose_name="Активен"),
        ),
        migrations.AddField(
            model_name="site",
            name="start_date",
            field=models.DateField(default=core.models._first_of_this_month, verbose_name="Начална дата"),
        ),
        migrations.AddField(
            model_name="site",
            name="end_date",
            field=models.DateField(blank=True, null=True, verbose_name="Крайна дата"),
        ),
        migrations.AddField(
            model_name="protocol",
            name="snapshot_client_firm_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="protocol",
            name="snapshot_client_eik",
            field=models.CharField(blank=True, max_length=9),
        ),
        migrations.AddField(
            model_name="protocol",
            name="snapshot_client_address",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="protocol",
            name="snapshot_client_phone",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
