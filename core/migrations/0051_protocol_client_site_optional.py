import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0050_protocolcolumn_ncm_counts"),
    ]

    operations = [
        migrations.AlterField(
            model_name="protocol",
            name="client",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="protocols", to="core.client", verbose_name="Клиент",
            ),
        ),
        migrations.AlterField(
            model_name="protocol",
            name="site",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="protocols", to="core.site", verbose_name="Обект",
            ),
        ),
    ]
