import html

from django.db import migrations


def _to_rich(plain):
    """Old notes are plain text — escape any literal HTML special chars so
    they keep displaying literally, then turn real newlines into <br> so
    the new rich-notes renderer preserves them exactly as before."""
    if not plain:
        return plain
    return html.escape(plain).replace('\r\n', '\n').replace('\n', '<br>')


def migrate_notes_forward(apps, schema_editor):
    Client = apps.get_model('core', 'Client')
    Site = apps.get_model('core', 'Site')
    for model in (Client, Site):
        rows = list(model.objects.exclude(notes='').exclude(notes__isnull=True))
        for obj in rows:
            obj.notes = _to_rich(obj.notes)
        if rows:
            model.objects.bulk_update(rows, ['notes'], batch_size=200)


def migrate_notes_backward(apps, schema_editor):
    # Best-effort only: turn <br> back into newlines and unescape entities.
    # Bold/italic/underline formatting added after the forward migration
    # cannot be losslessly reversed — this is a one-way upgrade in practice.
    import re
    Client = apps.get_model('core', 'Client')
    Site = apps.get_model('core', 'Site')
    for model in (Client, Site):
        rows = list(model.objects.exclude(notes='').exclude(notes__isnull=True))
        for obj in rows:
            text = re.sub(r'<br\s*/?>', '\n', obj.notes)
            text = re.sub(r'</?(?:b|i|u)>', '', text)
            obj.notes = html.unescape(text)
        if rows:
            model.objects.bulk_update(rows, ['notes'], batch_size=200)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0033_onetimetreatmentcontact'),
    ]

    operations = [
        migrations.RunPython(migrate_notes_forward, migrate_notes_backward),
    ]
