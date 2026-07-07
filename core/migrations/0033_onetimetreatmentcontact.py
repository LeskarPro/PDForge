"""
Migration 0033 — OneTimeTreatment contacts overhaul.

Steps:
1. Create OneTimeTreatmentContact table (treatment FK, name, phone, position, order).
2. Data-migrate: for every OneTimeTreatment with a non-blank contact_name,
   create one OneTimeTreatmentContact row carrying over contact_name/phone.
3. Remove the now-unused contact_name / phone fields from OneTimeTreatment.
"""

import django.db.models.deletion
from django.db import migrations, models


def forward_migrate(apps, schema_editor):
    OneTimeTreatment = apps.get_model('core', 'OneTimeTreatment')
    OneTimeTreatmentContact = apps.get_model('core', 'OneTimeTreatmentContact')

    for t in OneTimeTreatment.objects.all():
        name = (t.contact_name or '').strip()
        if not name:
            continue
        OneTimeTreatmentContact.objects.create(
            treatment=t,
            name=name,
            phone=t.phone or '',
            order=0,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0032_contact_replace_sitecontact'),
    ]

    operations = [
        # 1. Create OneTimeTreatmentContact model
        migrations.CreateModel(
            name='OneTimeTreatmentContact',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, verbose_name='Име')),
                ('phone', models.CharField(blank=True, max_length=20, verbose_name='Телефон')),
                ('position', models.CharField(blank=True, max_length=255, verbose_name='Длъжност')),
                ('order', models.PositiveSmallIntegerField(default=0, verbose_name='Ред')),
                ('treatment', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='contacts',
                    to='core.onetimetreatment',
                    verbose_name='Обработка',
                )),
            ],
            options={
                'verbose_name': 'Контактно лице (еднократна обработка)',
                'verbose_name_plural': 'Контактни лица (еднократни обработки)',
                'ordering': ['order'],
            },
        ),

        # 2. Data migration — carry over existing contact_name/phone
        migrations.RunPython(forward_migrate, migrations.RunPython.noop),

        # 3. Drop the old single-contact fields
        migrations.RemoveField(model_name='onetimetreatment', name='contact_name'),
        migrations.RemoveField(model_name='onetimetreatment', name='phone'),
    ]
