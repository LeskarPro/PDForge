from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0022_onetimetreatmentproduct_concentration'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='pseudonym',
            field=models.CharField(
                blank=True,
                help_text='Помощно название за избор в протокол (напр. „Айкън 25% – стандарт").',
                max_length=200,
                verbose_name='Псевдоним',
            ),
        ),
    ]
