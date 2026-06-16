from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0027_appsettings_sync_auto_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='protocol',
            name='prepared_date',
            field=models.DateField(
                blank=True, null=True,
                verbose_name='Дата на изготвяне на протокола',
            ),
        ),
    ]
