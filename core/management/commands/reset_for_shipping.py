from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (
    Protocol, TemplateFolder, OneTimeTreatment, Site, Client,
    Product, NonChemicalMean, Company, Tag, Worker,
)

# Order matters: respects on_delete=PROTECT relationships between models.
MODELS_TO_CLEAR = [
    Protocol,          # Протоколи + Шаблони (cascades columns/products)
    TemplateFolder,    # Папки за шаблони
    OneTimeTreatment,  # Еднократни обработки (cascades its products)
    Site,              # Обекти (cascades contacts)
    Client,            # Клиенти
    Product,           # Препарати
    NonChemicalMean,   # Нехим. средства
    Company,           # Фирми
    Tag,               # Етикети
    Worker,            # Работници
]


class Command(BaseCommand):
    help = (
        "Wipe all business data for shipping a blank app build. "
        "Deletes everything EXCEPT Pests (Вредители) and AppSettings. "
        "Run this only against a COPY of the database used as the seed "
        "for the packaged app — never against your live dev database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes", action="store_true",
            help="Skip the confirmation prompt.",
        )

    def handle(self, *args, **options):
        counts = {m: m.objects.count() for m in MODELS_TO_CLEAR}

        self.stdout.write("This will permanently delete:")
        for model, count in counts.items():
            self.stdout.write(f"  {model._meta.verbose_name_plural}: {count}")
        self.stdout.write(self.style.WARNING(
            "Pests (Вредители) and app settings will be kept as-is."
        ))

        if not options["yes"]:
            answer = input("Type 'yes' to continue: ")
            if answer.strip().lower() != "yes":
                self.stdout.write(self.style.ERROR("Aborted."))
                return

        with transaction.atomic():
            for model in MODELS_TO_CLEAR:
                model.objects.all().delete()

        self.stdout.write(self.style.SUCCESS("Done — database is blank except Pests."))