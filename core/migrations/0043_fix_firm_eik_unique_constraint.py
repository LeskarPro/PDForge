from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0042_remove_old_firm_client_fields"),
    ]

    operations = [
        # Drop the old constraint (only checked eik > '').
        migrations.RemoveConstraint(
            model_name="firm",
            name="unique_firm_eik_nonempty",
        ),
        # Replace with one that also requires deleted_at IS NULL, so
        # soft-deleted firms no longer block reuse of the same EIK.
        migrations.AddConstraint(
            model_name="firm",
            constraint=models.UniqueConstraint(
                fields=["eik"],
                condition=models.Q(eik__gt="") & models.Q(deleted_at__isnull=True),
                name="unique_firm_eik_nonempty",
            ),
        ),
    ]
