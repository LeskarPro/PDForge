from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0023_product_pseudonym'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='order',
            field=models.PositiveIntegerField(db_index=True, default=0, verbose_name='Ред'),
        ),
        migrations.AlterModelOptions(
            name='company',
            options={
                'ordering': ['order', 'name'],
                'verbose_name': 'Фирма (изпълнител)',
                'verbose_name_plural': 'Фирми (изпълнители)',
            },
        ),
    ]
