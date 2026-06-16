from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0024_company_order'),
    ]

    operations = [
        migrations.CreateModel(
            name='AppSettings',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('theme', models.CharField(
                    choices=[('coral', 'Coral'), ('slate', 'Slate'),
                             ('silver', 'Silver'), ('dark', 'Dark')],
                    default='coral', max_length=20, verbose_name='Тема',
                )),
                ('default_protocol_format', models.CharField(
                    choices=[('a5', 'A5 (2 стр.)'), ('a5-land', 'A5 → A4 пейзаж'),
                             ('a4-p', 'A4 портрет')],
                    default='a5', max_length=20,
                    verbose_name='Формат на протокол по подразбиране',
                )),
            ],
            options={
                'verbose_name': 'Настройки на приложението',
            },
        ),
    ]
