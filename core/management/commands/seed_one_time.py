from django.core.management.base import BaseCommand
from datetime import date, time, timedelta
from core.models import (
    OneTimeTreatment, OneTimeTreatmentProduct,
    Worker, Pest, Tag, Product,
)


class Command(BaseCommand):
    help = 'Seed sample Еднократни обработки records'

    def handle(self, *args, **options):
        # ── Workers ──────────────────────────────────────────
        w1, _ = Worker.objects.get_or_create(
            name='Петър Петров',
            defaults={'role': 'Оператор', 'is_active': True},
        )
        w2, _ = Worker.objects.get_or_create(
            name='Георги Димитров',
            defaults={'role': 'Оператор', 'is_active': True},
        )

        # ── Tags ─────────────────────────────────────────────
        t_urgent, _ = Tag.objects.get_or_create(
            name='Спешно', defaults={'color': '#e74c3c', 'order': 10},
        )
        t_contract, _ = Tag.objects.get_or_create(
            name='Договор', defaults={'color': '#27ae60', 'order': 11},
        )
        t_control, _ = Tag.objects.get_or_create(
            name='Контрол', defaults={'color': '#f39c12', 'order': 12},
        )

        # ── Reference data ────────────────────────────────────
        pests = {p.name: p for p in Pest.objects.filter(deleted_at__isnull=True)}
        products = list(Product.objects.filter(deleted_at__isnull=True).order_by('name'))

        def pest(*names):
            return [pests[n] for n in names if n in pests]

        def prod(index):
            return products[index] if index < len(products) else None

        today = date.today()

        entries = [
            dict(
                pseudonym='Ап. Иванови',
                address='ул. Витоша 15, ет. 3, ап. 8',
                contact_name='Иван Иванов',
                phone='0888 123 456',
                date=today - timedelta(days=3),
                time_from=time(9, 0),
                time_to=time(10, 30),
                service_types=['disinsection', 'deratization'],
                pests=pest('Хлебарки', 'Мишки', 'Мравки'),
                workers=[w1, w2],
                tags=[t_urgent, t_contract],
                price='85.00',
                notes='Клиентът иска повторно посещение след 2 седмици за контрол. Да се провери под мивката.',
                products=[
                    (prod(0), '50 мл', '0.05%'),
                    (prod(1), '2 примамки', ''),
                ],
            ),
            dict(
                pseudonym='Бл. 14 — мазе',
                address='бул. България 44, вх. Б, мазе',
                contact_name='Красимира Стоянова',
                phone='0877 654 321',
                date=today - timedelta(days=8),
                time_from=time(8, 0),
                time_to=None,
                service_types=['deratization'],
                pests=pest('Плъхове', 'Мишки'),
                workers=[w1],
                tags=[],
                price='40.00',
                notes='',
                products=[
                    (prod(1), '4 примамки', ''),
                ],
            ),
            dict(
                pseudonym='Фризьорски салон',
                address='ул. Раковски 7, партер',
                contact_name='Стилияна Маринова',
                phone='0899 111 222',
                date=today - timedelta(days=16),
                time_from=time(7, 30),
                time_to=time(9, 0),
                service_types=['disinsection', 'disinfection'],
                pests=pest('Хлебарки', 'Мухи'),
                workers=[w2],
                tags=[t_control],
                price='120.00',
                notes='Да се внимава с препаратите — до салона има кафене.',
                products=[
                    (prod(0), '100 мл', '0.1%'),
                    (prod(2) or prod(0), '200 мл', '0.05%'),
                ],
            ),
            dict(
                pseudonym='Гараж Петков',
                address='ж.к. Надежда, гараж №12',
                contact_name='Димитър Петков',
                phone='0888 999 000',
                date=today - timedelta(days=24),
                time_from=None,
                time_to=None,
                service_types=['deratization'],
                pests=[],
                workers=[w1],
                tags=[],
                price=None,
                notes='',
                products=[],
            ),
        ]

        created = 0
        for e in entries:
            if OneTimeTreatment.objects.filter(
                pseudonym=e['pseudonym'], address=e['address']
            ).exists():
                self.stdout.write(f'  skip  {e["pseudonym"]}')
                continue

            t = OneTimeTreatment.objects.create(
                pseudonym=e['pseudonym'],
                address=e['address'],
                contact_name=e['contact_name'],
                phone=e['phone'],
                date=e['date'],
                time_from=e['time_from'],
                time_to=e['time_to'],
                service_types=e['service_types'],
                price=e['price'],
                notes=e['notes'],
            )
            if e['pests']:
                t.pests.set(e['pests'])
            if e['workers']:
                t.executed_by.set(e['workers'])
            if e['tags']:
                t.tags.set(e['tags'])

            for i, (product, qty, conc) in enumerate(e['products']):
                if product:
                    OneTimeTreatmentProduct.objects.create(
                        treatment=t,
                        product=product,
                        quantity_text=qty,
                        concentration=conc,
                        order=i,
                    )
            created += 1
            self.stdout.write(f'  created  {t.pseudonym}')

        self.stdout.write(self.style.SUCCESS(f'\nDone — {created} record(s) created.'))