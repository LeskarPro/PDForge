"""
Migration 0032 — Replace SiteContact with Contact (client FK + sites M2M).

Steps:
1. Create Contact table + contact_sites junction table.
2. Data-migrate: for every SiteContact row, create a Contact linked to the
   site's client and add that site to the Contact.sites M2M.
3. Delete the SiteContact table.
"""

import uuid
import django.db.models.deletion
from django.db import migrations, models


def forward_migrate(apps, schema_editor):
    SiteContact = apps.get_model('core', 'SiteContact')
    Contact = apps.get_model('core', 'Contact')

    for sc in SiteContact.objects.select_related('site__client').all():
        contact = Contact(
            id=uuid.uuid4(),
            client=sc.site.client,
            name=sc.name,
            phone=sc.phone,
            position=sc.position,
            order=sc.order,
            deleted_at=sc.deleted_at,
        )
        contact.save()
        contact.sites.add(sc.site)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0031_alter_client_options_remove_client_unique_client_eik_and_more'),
    ]

    operations = [
        # 1. Create Contact model
        migrations.CreateModel(
            name='Contact',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('name', models.CharField(max_length=255, verbose_name='Име')),
                ('phone', models.CharField(blank=True, max_length=20, verbose_name='Телефон')),
                ('position', models.CharField(blank=True, max_length=255, verbose_name='Длъжност')),
                ('order', models.PositiveSmallIntegerField(default=0, verbose_name='Ред')),
                ('client', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='contacts',
                    to='core.client',
                    verbose_name='Клиент',
                )),
                ('sites', models.ManyToManyField(
                    blank=True,
                    related_name='contacts',
                    to='core.site',
                    verbose_name='Обекти',
                )),
            ],
            options={
                'verbose_name': 'Контактно лице',
                'verbose_name_plural': 'Контактни лица',
                'ordering': ['order', 'created_at'],
            },
        ),

        # 2. Data migration
        migrations.RunPython(forward_migrate, migrations.RunPython.noop),

        # 3. Drop SiteContact
        migrations.DeleteModel(name='SiteContact'),
    ]
