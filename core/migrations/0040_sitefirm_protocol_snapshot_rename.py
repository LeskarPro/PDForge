# Stage 8a REWORK (2026-06-19/21) — Firm moves off Client and onto Site.
#
# Context: by the time this rework was designed, 0037-0039 (Firm-on-Client)
# had already been auto-applied for real against Kiril's live db_old.sqlite3
# (run_app.py calls `migrate` on every app launch, and the app was opened
# during this same working session before the rework was finalised). So
# 0037-0039 are kept as-is (matching what's actually in the live db), and
# this migration + 0041 (data) + 0042 (cleanup) bridge from that
# already-applied Firm-on-Client shape to the new Firm-on-Site shape —
# rather than reusing 0037-0039's numbers for different content, which
# would have left Django thinking those migrations were already applied
# and silently skipping the real schema change.
#
# Schema only (additive) here: the new SiteFirm link model, and Protocol's
# renamed snapshot_firm_* fields (snapshot_client_firm_name etc. stay
# around until 0042, so 0041's data migration can still read them).

import uuid

import django.db.models.deletion
from django.db import migrations, models

import core.models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0039_remove_client_firm_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="SiteFirm",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True, verbose_name="Активна")),
                ("start_date", models.DateField(default=core.models._first_of_this_month, verbose_name="Начална дата")),
                ("end_date", models.DateField(blank=True, null=True, verbose_name="Крайна дата")),
                ("firm", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="site_links", to="core.firm", verbose_name="Фирма",
                )),
                ("site", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="firm_links", to="core.site", verbose_name="Обект",
                )),
            ],
            options={
                "verbose_name": "Връзка обект-фирма",
                "verbose_name_plural": "Връзки обект-фирма",
                "ordering": ["-is_active", "-start_date"],
            },
        ),
        migrations.AddField(
            model_name="protocol",
            name="snapshot_firm_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="protocol",
            name="snapshot_firm_eik",
            field=models.CharField(blank=True, max_length=9),
        ),
        migrations.AddField(
            model_name="protocol",
            name="snapshot_firm_address",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="protocol",
            name="snapshot_firm_phone",
            field=models.CharField(blank=True, max_length=20),
        ),
        # Firm.client must become nullable before 0042 can remove it cleanly
        # (a required FK can't have its reverse-AddField backfilled safely).
        migrations.AlterField(
            model_name="firm", name="client",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="firms", to="core.client", verbose_name="Клиент",
            ),
        ),
    ]
