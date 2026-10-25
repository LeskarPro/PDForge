from decimal import Decimal
from django.db import migrations


def create_other_and_backfill(apps, schema_editor):
    Protocol = apps.get_model('core', 'Protocol')
    OneTimeTreatment = apps.get_model('core', 'OneTimeTreatment')
    ProtocolLineItem = apps.get_model('core', 'ProtocolLineItem')
    OneTimeTreatmentLineItem = apps.get_model('core', 'OneTimeTreatmentLineItem')
    PriceCatalogItem = apps.get_model('core', 'PriceCatalogItem')
    NonChemicalMean = apps.get_model('core', 'NonChemicalMean')

    # 1. "Other" catalog item — service type, no product link. Holds every
    #    pre-existing flat price so no historical amount is lost.
    other_item, _ = PriceCatalogItem.objects.get_or_create(
        name='Други',
        item_type='service',
        non_chemical_mean=None,
        defaults={'default_price': None},
    )

    # 2. One catalog item per existing NonChemicalMean — auto-created only
    #    this once, for this migration. From now on this link is manual
    #    (Ценообразуване page, Stage 3).
    ncm_to_catalog = {}
    for ncm in NonChemicalMean.objects.all():
        catalog_item, _ = PriceCatalogItem.objects.get_or_create(
            non_chemical_mean=ncm,
            defaults={'name': ncm.name, 'item_type': 'product'},
        )
        ncm_to_catalog[ncm.id] = catalog_item

    # 3. Backfill "Other" on EVERY Protocol (including presets/templates) and
    #    OneTimeTreatment — qty=1, price=<the old flat price>, or price=None
    #    where there wasn't one. Every record gets the line either way; the
    #    user can delete it if it's not wanted rather than us guessing.
    for protocol in Protocol.objects.all():
        ProtocolLineItem.objects.create(
            protocol=protocol,
            catalog_item=other_item,
            quantity=Decimal('1'),
            price=protocol.price,
            order=0,
            snapshot_name=other_item.name,
            snapshot_item_type=other_item.item_type,
            snapshot_has_ncm_link=False,
        )

    for treatment in OneTimeTreatment.objects.all():
        OneTimeTreatmentLineItem.objects.create(
            treatment=treatment,
            catalog_item=other_item,
            quantity=Decimal('1'),
            price=treatment.price,
            order=0,
            snapshot_name=other_item.name,
            snapshot_item_type=other_item.item_type,
            snapshot_has_ncm_link=False,
        )

    # 4. For every Protocol, for each NonChemicalMean ticked on any of its
    #    columns (active or not — the save path doesn't restrict M2M writes
    #    to active columns either), add a qty=0/price=0 line pointing at
    #    that NCM's catalog item — migration-only convenience so the user
    #    has something to find and fill in, one line per distinct NCM even
    #    if it's ticked on more than one service column.
    for protocol in Protocol.objects.all():
        seen_ncm_ids = set()
        next_order = 1
        for column in protocol.columns.all():
            for ncm in column.non_chemical_means.all():
                if ncm.id in seen_ncm_ids:
                    continue
                seen_ncm_ids.add(ncm.id)
                catalog_item = ncm_to_catalog.get(ncm.id)
                if not catalog_item:
                    continue
                ProtocolLineItem.objects.create(
                    protocol=protocol,
                    catalog_item=catalog_item,
                    quantity=Decimal('0'),
                    price=Decimal('0'),
                    order=next_order,
                    snapshot_name=catalog_item.name,
                    snapshot_item_type=catalog_item.item_type,
                    snapshot_has_ncm_link=True,
                )
                next_order += 1


def reverse_backfill(apps, schema_editor):
    ProtocolLineItem = apps.get_model('core', 'ProtocolLineItem')
    OneTimeTreatmentLineItem = apps.get_model('core', 'OneTimeTreatmentLineItem')
    PriceCatalogItem = apps.get_model('core', 'PriceCatalogItem')

    ProtocolLineItem.objects.all().delete()
    OneTimeTreatmentLineItem.objects.all().delete()
    PriceCatalogItem.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0048_price_module_stage1'),
    ]

    operations = [
        migrations.RunPython(create_other_and_backfill, reverse_backfill),
    ]
