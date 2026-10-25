from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0051_protocol_client_site_optional"),
    ]

    operations = [
        migrations.AlterField(
            model_name="appsettings",
            name="default_protocol_format",
            field=models.CharField(
                choices=[("a5", "A4"), ("a5-land", "A5"), ("a4-p", "A4 портрет")],
                default="a5", max_length=20,
                verbose_name="Формат на протокол по подразбиране",
            ),
        ),
    ]
