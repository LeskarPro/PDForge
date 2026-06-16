from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_protocol_price_protocol_pseudonym_templatefolder_and_more'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='client',
            constraint=models.UniqueConstraint(
                fields=['eik'], name='unique_client_eik'
            ),
        ),
        migrations.CreateModel(
            name='SiteContact',
            fields=[
                ('id', models.UUIDField(
                    default=uuid.uuid4, editable=False,
                    primary_key=True, serialize=False,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('name', models.CharField(max_length=255, verbose_name='Име')),
                ('phone', models.CharField(
                    blank=True, max_length=20, verbose_name='Телефон'
                )),
                ('position', models.CharField(
                    blank=True, max_length=255, verbose_name='Длъжност'
                )),
                ('order', models.PositiveSmallIntegerField(
                    default=0, verbose_name='Ред'
                )),
                ('site', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='contacts',
                    to='core.site',
                    verbose_name='Обект',
                )),
            ],
            options={
                'verbose_name': 'Контактно лице',
                'verbose_name_plural': 'Контактни лица',
                'ordering': ['order', 'created_at'],
                'abstract': False,
            },
        ),
    ]