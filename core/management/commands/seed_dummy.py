"""
Management command: python manage.py seed_dummy

Creates a realistic set of dummy data for layout testing.
Safe to run multiple times — checks for existing data first.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from decimal import Decimal
import datetime

from core.models import (
    Client, Firm, Company, Site, Worker, Pest, Tag,
    Protocol, ProtocolColumn, TemplateFolder, Product,
)


class Command(BaseCommand):
    help = "Seed dummy data for layout testing (Stage 1b)"

    def handle(self, *args, **options):
        self.stdout.write("Seeding dummy data...")

        # ── Company ──────────────────────────────────────────────
        company, _ = Company.objects.get_or_create(
            name="ДДД Про ЕООД",
            defaults=dict(
                eik="123456789",
                address="гр. София, ул. Витоша 10",
                phone="02 888 8888",
                is_default=True,
                is_active=True,
            )
        )
        self.stdout.write("  ✓ Company")

        # ── Workers ───────────────────────────────────────────────
        ivan, _ = Worker.objects.get_or_create(
            name="Иван Петров",
            defaults=dict(role="Ръководител ДДД", is_default_supervisor=True, is_active=True)
        )
        maria, _ = Worker.objects.get_or_create(
            name="Мария Иванова",
            defaults=dict(role="Изпълнител", is_default_executor=True, is_active=True)
        )
        self.stdout.write("  ✓ Workers")

        # ── Pests ─────────────────────────────────────────────────
        pests_data = [
            ("Мухи",      "disinsection"),
            ("Хлебарки",  "disinsection"),
            ("Мравки",    "disinsection"),
            ("Бълхи",     "disinsection"),
            ("Плъхове",   "deratization"),
            ("Мишки",     "deratization"),
            ("Бактерии",  "disinfection"),
            ("Вируси",    "disinfection"),
        ]
        pest_objs = {}
        for name, cat in pests_data:
            p, _ = Pest.objects.get_or_create(name=name, category=cat)
            pest_objs[(name, cat)] = p
        self.stdout.write("  ✓ Pests")

        # ── Tags ──────────────────────────────────────────────────
        tags_data = [
            ("Хранителен обект", "#2d9e5c"),
            ("Договор",          "#aa767c"),
            ("Месечно",          "#2d5ca8"),
            ("Тримесечно",       "#7c5ca8"),
            ("Еднократно",       "#a87c2d"),
        ]
        tag_objs = {}
        for name, color in tags_data:
            t, _ = Tag.objects.get_or_create(name=name, defaults=dict(color=color))
            tag_objs[name] = t
        self.stdout.write("  ✓ Tags")

        # ── Clients + Sites ───────────────────────────────────────
        clients_data = [
            {
                "firm": "„Виктория Нутс\" ЕООД",
                "name": "Виктория Нутс",
                "eik": "111111111",
                "address": "гр. София, бул. Дондуков 22",
                "sites": [
                    ("Магазин №1", "ул. Витоша 15, гр. София"),
                    ("Магазин №3", "бул. Дондуков 22, гр. София"),
                    ("Склад Люлин", "ул. Народни Будители 8, гр. София"),
                ],
            },
            {
                "firm": "„Комета III\" ООД",
                "name": "Комета",
                "eik": "222222222",
                "address": "гр. Варна, бул. Пролет 42",
                "sites": [
                    ("Офис Варна", "бул. Пролет 42, гр. Варна"),
                ],
            },
            {
                "firm": "Транс Ком ООД",
                "name": "Транс Ком",
                "eik": "333333333",
                "address": "гр. Пловдив, ул. Индустриална 7",
                "sites": [
                    ("Склад Банишора", "ул. Индустриална 7, гр. Пловдив"),
                    ("Гараж",         "ул. Магистрална 3, гр. Пловдив"),
                ],
            },
            {
                "firm": "Строй ООД",
                "name": "Строй",
                "eik": "444444444",
                "address": "гр. Бургас, ул. Строителна 3",
                "sites": [
                    ("Склад №2", "ул. Строителна 3, гр. Бургас"),
                ],
            },
            {
                "firm": "ХранМаг ЕООД",
                "name": "ХранМаг",
                "eik": "555555555",
                "address": "гр. Русе, бул. Опълченски 88",
                "sites": [
                    ("Магазин №5", "бул. Опълченски 88, гр. Русе"),
                ],
            },
        ]

        client_objs = {}
        site_objs = {}
        for cd in clients_data:
            client, _ = Client.objects.get_or_create(name=cd["name"])
            Firm.objects.get_or_create(
                client=client, eik=cd["eik"],
                defaults=dict(name=cd["firm"], address=cd["address"], is_active=True),
            )
            client_objs[cd["name"]] = client
            for site_name, site_addr in cd["sites"]:
                site, _ = Site.objects.get_or_create(
                    client=client, name=site_name,
                    defaults=dict(address=site_addr, pseudonym=site_name)
                )
                site_objs[(cd["name"], site_name)] = site
        self.stdout.write("  ✓ Clients & Sites")

        # ── Protocols ─────────────────────────────────────────────
        protocols_data = [
            {
                "pseudo": "Виктория Нутс",
                "client": "Виктория Нутс",
                "site": "Магазин №1",
                "date": datetime.date(2026, 5, 15),
                "time_from": datetime.time(9, 0),
                "time_to":   datetime.time(11, 0),
                "executor": maria,
                "prepared": ivan,
                "contract": True,
                "price": Decimal("85.00"),
                "notes": "Клиентът е поискал допълнителна обработка в склада.",
                "pests_di": ["Мухи", "Хлебарки", "Мравки"],
                "pests_dr": [],
                "pests_dn": [],
                "tags": ["Хранителен обект", "Месечно"],
            },
            {
                "pseudo": "Комета",
                "client": "Комета",
                "site": "Офис Варна",
                "date": datetime.date(2026, 5, 12),
                "time_from": datetime.time(14, 0),
                "time_to":   datetime.time(15, 30),
                "executor": maria,
                "prepared": ivan,
                "contract": True,
                "price": Decimal("120.00"),
                "notes": "",
                "pests_di": [],
                "pests_dr": ["Плъхове", "Мишки"],
                "pests_dn": [],
                "tags": ["Договор"],
            },
            {
                "pseudo": "Транс Ком",
                "client": "Транс Ком",
                "site": "Склад Банишора",
                "date": datetime.date(2026, 5, 8),
                "time_from": datetime.time(10, 0),
                "time_to":   datetime.time(13, 0),
                "executor": ivan,
                "prepared": ivan,
                "contract": False,
                "price": None,
                "notes": "Препоръчана повторна проверка след 2 седмици.",
                "pests_di": ["Хлебарки", "Мравки"],
                "pests_dr": ["Плъхове", "Мишки"],
                "pests_dn": [],
                "tags": ["Еднократно"],
            },
            {
                "pseudo": "Строй",
                "client": "Строй",
                "site": "Склад №2",
                "date": datetime.date(2026, 5, 1),
                "time_from": datetime.time(8, 0),
                "time_to":   datetime.time(9, 30),
                "executor": maria,
                "prepared": ivan,
                "contract": True,
                "price": Decimal("60.00"),
                "notes": "",
                "pests_di": [],
                "pests_dr": ["Плъхове", "Мишки"],
                "pests_dn": [],
                "tags": ["Договор", "Месечно"],
            },
            {
                "pseudo": "ХранМаг №5",
                "client": "ХранМаг",
                "site": "Магазин №5",
                "date": datetime.date(2026, 4, 28),
                "time_from": datetime.time(15, 0),
                "time_to":   datetime.time(16, 0),
                "executor": ivan,
                "prepared": ivan,
                "contract": False,
                "price": Decimal("45.00"),
                "notes": "",
                "pests_di": ["Хлебарки", "Мравки"],
                "pests_dr": [],
                "pests_dn": [],
                "tags": ["Хранителен обект"],
            },
            {
                "pseudo": "Виктория Нутс",
                "client": "Виктория Нутс",
                "site": "Магазин №3",
                "date": datetime.date(2026, 4, 20),
                "time_from": datetime.time(10, 0),
                "time_to":   datetime.time(12, 0),
                "executor": maria,
                "prepared": ivan,
                "contract": True,
                "price": Decimal("70.00"),
                "notes": "",
                "pests_di": ["Хлебарки"],
                "pests_dr": [],
                "pests_dn": [],
                "tags": ["Хранителен обект", "Тримесечно"],
            },
        ]

        for pd in protocols_data:
            client = client_objs[pd["client"]]
            site   = site_objs[(pd["client"], pd["site"])]
            if Protocol.objects.filter(
                client=client, site=site, date=pd["date"], is_preset=False
            ).exists():
                continue

            protocol = Protocol.objects.create(
                client=client,
                site=site,
                company=company,
                pseudonym=pd["pseudo"],
                date=pd["date"],
                time_from=pd["time_from"],
                time_to=pd["time_to"],
                prepared_by=pd["prepared"],
                executed_by=pd["executor"],
                is_long_term_contract=pd["contract"],
                is_preset=False,
                price=pd["price"],
                notes=pd["notes"],
            )
            # Tags
            for tname in pd["tags"]:
                protocol.tags.add(tag_objs[tname])

            # Pests per column
            for col in protocol.columns.all():
                if col.service == "disinsection":
                    col.is_active = bool(pd["pests_di"])
                    col.save()
                    for pname in pd["pests_di"]:
                        col.pests.add(pest_objs[(pname, "disinsection")])
                elif col.service == "deratization":
                    col.is_active = bool(pd["pests_dr"])
                    col.save()
                    for pname in pd["pests_dr"]:
                        col.pests.add(pest_objs[(pname, "deratization")])
                elif col.service == "disinfection":
                    col.is_active = bool(pd["pests_dn"])
                    col.save()
                    for pname in pd["pests_dn"]:
                        col.pests.add(pest_objs[(pname, "disinfection")])

        self.stdout.write("  ✓ Protocols")

        # ── Template Folders ──────────────────────────────────────
        f_victoria, _ = TemplateFolder.objects.get_or_create(
            name="Виктория Нутс", parent=None
        )
        f_victoria_mag, _ = TemplateFolder.objects.get_or_create(
            name="Магазини", parent=f_victoria
        )
        f_victoria_sklad, _ = TemplateFolder.objects.get_or_create(
            name="Складове", parent=f_victoria
        )
        f_transcom, _ = TemplateFolder.objects.get_or_create(
            name="Транс Ком", parent=None
        )
        f_hranmag, _ = TemplateFolder.objects.get_or_create(
            name="ХранМаг", parent=None
        )
        self.stdout.write("  ✓ Template folders")

        # ── Templates (is_preset=True) ────────────────────────────
        templates_data = [
            {
                "pseudo": "Виктория Нутс",
                "client": "Виктория Нутс",
                "site": "Магазин №1",
                "preset_name": "Месечна ДИ — Магазин №1",
                "folder": f_victoria_mag,
                "price": Decimal("85.00"),
                "pests_di": ["Мухи", "Хлебарки", "Мравки"],
                "pests_dr": [],
                "tags": ["Хранителен обект", "Месечно"],
            },
            {
                "pseudo": "Виктория Нутс",
                "client": "Виктория Нутс",
                "site": "Магазин №3",
                "preset_name": "Тримесечна ДИ — Магазин №3",
                "folder": f_victoria_mag,
                "price": Decimal("70.00"),
                "pests_di": ["Хлебарки"],
                "pests_dr": [],
                "tags": ["Хранителен обект", "Тримесечно"],
            },
            {
                "pseudo": "Виктория Нутс",
                "client": "Виктория Нутс",
                "site": "Склад Люлин",
                "preset_name": "Дератизация — Склад Люлин",
                "folder": f_victoria_sklad,
                "price": None,
                "pests_di": [],
                "pests_dr": ["Плъхове", "Мишки"],
                "tags": ["Договор"],
            },
            {
                "pseudo": "Транс Ком",
                "client": "Транс Ком",
                "site": "Склад Банишора",
                "preset_name": "ДИ+ДР — Склад Банишора",
                "folder": f_transcom,
                "price": Decimal("120.00"),
                "pests_di": ["Хлебарки", "Мравки"],
                "pests_dr": ["Плъхове", "Мишки"],
                "tags": ["Договор", "Месечно"],
            },
            {
                "pseudo": "Транс Ком",
                "client": "Транс Ком",
                "site": "Гараж",
                "preset_name": "Дератизация — Гараж",
                "folder": f_transcom,
                "price": Decimal("40.00"),
                "pests_di": [],
                "pests_dr": ["Плъхове"],
                "tags": ["Договор"],
            },
            {
                "pseudo": "ХранМаг №5",
                "client": "ХранМаг",
                "site": "Магазин №5",
                "preset_name": "Месечна ДИ — Магазин №5",
                "folder": f_hranmag,
                "price": Decimal("45.00"),
                "pests_di": ["Хлебарки", "Мравки"],
                "pests_dr": [],
                "tags": ["Хранителен обект"],
            },
            # One loose template at root (no folder)
            {
                "pseudo": "Строй",
                "client": "Строй",
                "site": "Склад №2",
                "preset_name": "Дератизация — Склад №2",
                "folder": None,
                "price": Decimal("60.00"),
                "pests_di": [],
                "pests_dr": ["Плъхове", "Мишки"],
                "tags": ["Договор"],
            },
        ]

        for td in templates_data:
            client = client_objs[td["client"]]
            site   = site_objs[(td["client"], td["site"])]
            if Protocol.objects.filter(
                client=client, site=site,
                is_preset=True, preset_name=td["preset_name"]
            ).exists():
                continue

            tpl = Protocol.objects.create(
                client=client,
                site=site,
                company=company,
                pseudonym=td["pseudo"],
                preset_name=td["preset_name"],
                is_preset=True,
                folder=td["folder"],
                price=td["price"],
                is_long_term_contract=True,
                prepared_by=ivan,
                executed_by=maria,
            )
            for tname in td["tags"]:
                tpl.tags.add(tag_objs[tname])

            for col in tpl.columns.all():
                if col.service == "disinsection":
                    col.is_active = bool(td["pests_di"])
                    col.save()
                    for pname in td["pests_di"]:
                        col.pests.add(pest_objs[(pname, "disinsection")])
                elif col.service == "deratization":
                    col.is_active = bool(td.get("pests_dr", []))
                    col.save()
                    for pname in td.get("pests_dr", []):
                        col.pests.add(pest_objs[(pname, "deratization")])
                elif col.service == "disinfection":
                    col.is_active = False
                    col.save()

        self.stdout.write("  ✓ Templates")
        self.stdout.write(self.style.SUCCESS("\nDone. Run the server and open /protocols/ and /templates/"))