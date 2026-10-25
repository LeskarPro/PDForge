from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0049_price_module_backfill"),
    ]

    operations = [
        migrations.AddField(
            model_name="protocolcolumn",
            name="ncm_counts",
            field=models.JSONField(
                blank=True, default=dict,
                help_text="{non_chemical_mean_id: брой} — отпечатва се на ред 5.",
                verbose_name="Брой нехимични средства",
            ),
        ),
    ]
