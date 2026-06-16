from django.db import migrations, models


def backfill_pseudonym(apps, schema_editor):
    Site = apps.get_model('core', 'Site')
    for site in Site.objects.all():
        if not site.pseudonym:
            site.pseudonym = site.name
            site.save(update_fields=['pseudonym'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0028_protocol_prepared_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='site',
            name='pseudonym',
            field=models.CharField(
                default='', max_length=255,
                verbose_name='Псевдоним',
                help_text='Кратко показно наименование на обекта (за списъците).',
            ),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_pseudonym, noop_reverse),
    ]
