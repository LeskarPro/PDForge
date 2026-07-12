from django.db import models
from django.db.models import Q
from django.utils import timezone
from datetime import date as _date
import uuid


def _first_of_this_month():
    """Default start date for Firm/Site — the 1st of the current month."""
    return _date.today().replace(day=1)


class TimeStampedModel(models.Model):
    """Abstract base: UUID primary key, timestamps, soft-delete."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        abstract = True
        ordering = ["created_at"]

    @property
    def is_deleted(self):
        return self.deleted_at is not None

class Client(TimeStampedModel):
    """A Client — the company / institution that hires us for DDD.

    Stage 8a (reworked): a Firm is no longer attached to Client at all — it
    attaches to Site (see Firm/SiteFirm below), because one client can have
    several sites that each need their own firm identity. Client keeps only
    its stable identity: name (which doubles as the pseudonym, per the 8c
    decision) and notes.
    """

    name = models.CharField("Име", max_length=255)
    notes = models.TextField("Бележки", blank=True)

    class Meta:
        verbose_name = "Клиент"
        verbose_name_plural = "Клиенти"
        ordering = ["name"]

    @property
    def is_active(self) -> bool:
        """Derived, not stored — a client with no active Site is inactive."""
        return self.sites.filter(is_active=True, deleted_at__isnull=True).exists()

    def __str__(self) -> str:
        return self.name


class Firm(TimeStampedModel):
    """A reusable legal-entity record (name/EIK/address/phone only).

    Not tied to a single Client or Site — it can be linked to several Sites
    at once via SiteFirm (see below), and editing it here updates everywhere
    it's linked. Date range / active-inactive state lives on the link
    (SiteFirm), not here, since the same firm can be active for one site and
    ended for another.
    """

    name = models.CharField("Фирма", max_length=255)
    eik = models.CharField("ЕИК", max_length=9, blank=True)
    address = models.CharField("Адрес", max_length=500)
    phone = models.CharField("Телефон", max_length=20, blank=True)

    class Meta:
        verbose_name = "Фирма"
        verbose_name_plural = "Фирми"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["eik"],
                condition=Q(eik__gt='') & Q(deleted_at__isnull=True),
                name="unique_firm_eik_nonempty",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Company(TimeStampedModel):
    """An executor company (us) whose identity prints in the protocol header.

    Several legal entities are supported; exactly one is the default for new
    protocols. Logo and slogan are set once here and read live; the text
    identity (name/ЕИК/address/phone) is snapshotted onto each protocol.
    """

    name = models.CharField("Име", max_length=255)
    eik = models.CharField("ЕИК", max_length=13)
    address = models.CharField("Адрес", max_length=500, blank=True)
    phone = models.CharField("Телефон", max_length=100, blank=True)
    slogan = models.CharField("Слоган", max_length=255, blank=True)
    logo = models.ImageField("Лого", upload_to="logos/", null=True, blank=True)
    is_default = models.BooleanField("По подразбиране", default=False)
    is_active = models.BooleanField("Активна", default=True)
    order = models.PositiveIntegerField("Ред", default=0, db_index=True)

    class Meta:
        verbose_name = "Фирма (изпълнител)"
        verbose_name_plural = "Фирми (изпълнители)"
        ordering = ["order", "name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            Company.objects.exclude(pk=self.pk).filter(is_default=True).update(
                is_default=False
            )

class Site(TimeStampedModel):
    """A physical site / building belonging to a Client."""
    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        related_name="sites",
        verbose_name="Клиент")
    # Display name used on the Обекти / Клиенти lists and in the protocol
    # editor's site picker — name remains the official site name printed
    # on protocol documents.
    pseudonym = models.CharField(
        "Псевдоним", max_length=255,
        help_text="Кратко показно наименование на обекта (за списъците).")
    name = models.CharField("Име на обекта", max_length=255)
    address = models.CharField("Адрес", max_length=500, blank=True)
    area_m2 = models.PositiveIntegerField("Обща площ (m²)", null=True, blank=True)
    notes = models.TextField("Бележки", blank=True)
    tags = models.ManyToManyField(
        "Tag", blank=True, related_name="sites", verbose_name="Етикети"
    )

    # Stage 8b — active/inactive + date range (month+year granularity).
    is_active = models.BooleanField("Активен", default=True)
    start_date = models.DateField("Начална дата", default=_first_of_this_month)
    end_date = models.DateField("Крайна дата", null=True, blank=True)

    class Meta:
        verbose_name = "Обект"
        verbose_name_plural = "Обекти"
        ordering = ["client__name", "name"]

    def save(self, *args, **kwargs):
        if self.is_active:
            # An active record never carries a stale end date.
            self.end_date = None
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.client.name} — {self.name}"

    @property
    def active_firm_link(self):
        """This site's currently active SiteFirm link, or None."""
        return (
            self.firm_links
            .filter(is_active=True, deleted_at__isnull=True)
            .select_related('firm')
            .order_by('-start_date')
            .first()
        )

    @property
    def active_firm(self):
        """The Firm currently linked to this site, or None."""
        link = self.active_firm_link
        return link.firm if link else None


class SiteFirm(TimeStampedModel):
    """Link between a Site and a Firm, valid for a date range.

    A Firm can be linked to many Sites at once (reusable); a Site can have
    many SiteFirm rows over time (its own firm history), normally only one
    active at once. Saving a new active link for a site auto-ends that
    site's *previous* active link, but never touches the firm's links to
    other sites. Site.is_active is independent of this — ending a firm link
    does not deactivate the site, and vice versa.
    """

    site = models.ForeignKey(
        Site, on_delete=models.CASCADE,
        related_name="firm_links", verbose_name="Обект",
    )
    firm = models.ForeignKey(
        Firm, on_delete=models.CASCADE,
        related_name="site_links", verbose_name="Фирма",
    )
    is_active = models.BooleanField("Активна", default=True)
    start_date = models.DateField("Начална дата", default=_first_of_this_month)
    end_date = models.DateField("Крайна дата", null=True, blank=True)

    class Meta:
        verbose_name = "Връзка обект-фирма"
        verbose_name_plural = "Връзки обект-фирма"
        ordering = ["-is_active", "-start_date"]

    def __str__(self) -> str:
        return f"{self.firm.name} — {self.site}"

    def save(self, *args, **kwargs):
        if self.is_active:
            # An active record never carries a stale end date.
            self.end_date = None
        super().save(*args, **kwargs)
        if self.is_active:
            # Only one active firm-link per SITE — ending the previous one
            # at the moment this one starts. Scoped to this site only, so
            # the same firm's links to other sites are untouched.
            SiteFirm.objects.exclude(pk=self.pk).filter(
                site_id=self.site_id, is_active=True, deleted_at__isnull=True,
            ).update(is_active=False, end_date=self.start_date)


class Contact(TimeStampedModel):
    """Contact person for a Client, optionally linked to one or more Sites.
    UI-only — not printed on protocols."""

    client = models.ForeignKey(
        'Client',
        on_delete=models.CASCADE,
        related_name='contacts',
        verbose_name='Клиент',
    )
    sites = models.ManyToManyField(
        'Site',
        blank=True,
        related_name='contacts',
        verbose_name='Обекти',
    )
    name = models.CharField("Име", max_length=255)
    phone = models.CharField("Телефон", max_length=20, blank=True)
    position = models.CharField("Длъжност", max_length=255, blank=True)
    order = models.PositiveSmallIntegerField("Ред", default=0)

    class Meta:
        verbose_name = "Контактно лице"
        verbose_name_plural = "Контактни лица"
        ordering = ['order', 'created_at']

    def __str__(self) -> str:
        return f"{self.name} — {self.client}"
    
class Product(TimeStampedModel):
    """A biocide / chemical product used in DDD treatments."""

    class Category(models.TextChoices):
        DISINSECTION = "disinsection", "Дезинсекция и дезакаризация"
        DERATIZATION = "deratization", "Дератизация"
        DISINFECTION = "disinfection", "Дезинфекция"

    pseudonym = models.CharField(
        "Псевдоним", max_length=200, blank=True,
        help_text="Помощно название за избор в протокол (напр. „Айкън 10 КС - 25мл\").",
    )
    name = models.CharField("Търговско наименование", max_length=255)
    category = models.CharField(
        "Категория", max_length=20, choices=Category.choices
    )
    authorization_no = models.CharField("№ на разрешението", max_length=100)
    formulation = models.CharField("Формулация", max_length=255)
    active_substances = models.TextField("Активни вещества и концентрация")
    working_solution = models.TextField("Работен разтвор")
    action_time = models.CharField("Време на въздействие", max_length=255, blank=True)
    antidote = models.CharField("Антидот", max_length=255, blank=True)
    safety_instructions = models.TextField("Мерки за безопасност", blank=True)
    access_info = models.TextField("Достъп до обработените площи", blank=True)
    surfaces_to_wipe = models.CharField(
        "Повърхности за забърсване", max_length=255, blank=True
    )
    bait_descriptor = models.CharField(
        "Текст за дератизационна примамка", max_length=255, blank=True,
        help_text="Напр. „70гр. Мишемор Грийн“. Ползва се за ред 11 при дератизация.",
    )
    notes = models.TextField("Бележки", blank=True)

    class Meta:
        verbose_name = "Препарат"
        verbose_name_plural = "Препарати"
        ordering = ["category", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_category_display()})"

class Pest(TimeStampedModel):
    """Row 1: pests targeted (disinsection/deratization) or action spectrum (disinfection)."""

    name = models.CharField("Наименование", max_length=255)
    category = models.CharField(
        "Категория",
        max_length=20,
        choices=Product.Category.choices,  # reuse the exact same enum
    )

    class Meta:
        verbose_name = "Вредител / спектър"
        verbose_name_plural = "Вредители / спектри"
        ordering = ["category", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "category"],
                name="unique_pest_per_category",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_category_display()})"


class NonChemicalMean(TimeStampedModel):
    """Row 5: traps, lamps, etc. (non-chemical means)."""

    name = models.CharField("Наименование", max_length=255)
    category = models.CharField(
        "Категория",
        max_length=20,
        choices=Product.Category.choices,
    )

    notes = models.TextField("Бележки", blank=True)

    class Meta:
        verbose_name = "Нехимично средство"
        verbose_name_plural = "Нехимични средства"
        ordering = ["category", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_category_display()})"

class Tag(TimeStampedModel):
    """Reusable label for sites and protocols, used for filtering."""

    name = models.CharField("Етикет", max_length=100, unique=True)
    color = models.CharField(
        "Цвят",
        max_length=7,
        default="#6B7280",
        help_text="Например #3B82F6 за синьо. Използва се за визуално различаване в списъци.",
    )
    description = models.TextField("Описание", blank=True, default="")
    order = models.PositiveIntegerField("Ред", default=0, db_index=True)

    class Meta:
        verbose_name = "Етикет"
        verbose_name_plural = "Етикети"
        ordering = ["order", "name"]

    def __str__(self) -> str:
        return self.name

class Worker(TimeStampedModel):
    """A field worker / DDD operator. Their name appears on protocols."""

    name = models.CharField("Име и фамилия", max_length=255)
    role = models.CharField("Длъжност", max_length=100, blank=True)

    is_default_supervisor = models.BooleanField(
        "По подразбиране за 'Подготвил'", default=False,
        help_text=(
            "Маркирай един работник, който да се избира автоматично за полето "
            "'Подготвил' при създаване на нов протокол."
        ),
    )
    is_default_executor = models.BooleanField(
        "По подразбиране за 'Изпълнил'", default=False,
        help_text=(
            "Маркирай един работник, който да се избира автоматично за полето "
            "'Изпълнил' при създаване на нов протокол."
        ),
    )
    is_active = models.BooleanField(
        "Активен", default=True,
        help_text="Неактивните работници не се показват в падащите менюта при нов протокол.",
    )

    class Meta:
        verbose_name = "Работник"
        verbose_name_plural = "Работници"
        ordering = ["-is_active", "name"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default_supervisor:
            Worker.objects.exclude(pk=self.pk).filter(is_default_supervisor=True).update(
                is_default_supervisor=False
            )
        if self.is_default_executor:
            Worker.objects.exclude(pk=self.pk).filter(is_default_executor=True).update(
                is_default_executor=False
            )

    def __str__(self) -> str:
        suffix = "" if self.is_active else " (неактивен)"
        return f"{self.name}{suffix}"


class TemplateFolder(TimeStampedModel):
    """A folder for organising protocol templates. Supports arbitrary nesting."""

    name = models.CharField("Наименование", max_length=255)
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='subfolders',
        verbose_name='Родителска папка',
    )

    class Meta:
        verbose_name = "Папка за шаблони"
        verbose_name_plural = "Папки за шаблони"
        ordering = ['name']

    def __str__(self) -> str:
        return self.name

    def get_ancestors(self):
        """Returns [root, ..., parent] — not including self."""
        ancestors = []
        current = self.parent
        while current:
            ancestors.insert(0, current)
            current = current.parent
        return ancestors

    def get_breadcrumb(self):
        """Returns [root, ..., self] for breadcrumb display."""
        return self.get_ancestors() + [self]


def _normalize_tax_fields(instance):
    """Freeze `tax_rate_snapshot` the first time VAT is turned on for a
    record, and clear the VAT fields when it's off. Shared by Protocol and
    OneTimeTreatment save() — see AppSettings.vat_percent for the live
    default rate new records pick up."""
    if instance.tax_included:
        if instance.tax_rate_snapshot is None:
            instance.tax_rate_snapshot = AppSettings.get().vat_percent
    else:
        instance.price_with_tax = None
        instance.tax_rate_snapshot = None


class Protocol(TimeStampedModel):
    """One DDD treatment protocol (or a saved preset for one)."""

    # Basic info: client, site, date and time of the work
    client = models.ForeignKey(
        Client, on_delete=models.PROTECT,
        related_name="protocols", verbose_name="Клиент",
    )
    site = models.ForeignKey(
        Site, on_delete=models.PROTECT,
        related_name="protocols", verbose_name="Обект",
    )

    company = models.ForeignKey(
        "Company", on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="protocols", verbose_name="Фирма изпълнител",
    )
    # Frozen copy of the company's text identity at selection time.
    snapshot_company_name = models.CharField(max_length=255, blank=True)
    snapshot_company_eik = models.CharField(max_length=13, blank=True)
    snapshot_company_address = models.CharField(max_length=500, blank=True)
    snapshot_company_phone = models.CharField(max_length=100, blank=True)

    # Frozen copy of the site's active Firm link at save time (Stage 8a,
    # reworked — Firm now attaches to Site, not Client) — the printed
    # document must keep showing what was true when it was made, even if
    # the site's firm later changes or ends. Same pattern as the company
    # snapshot above.
    snapshot_firm_name = models.CharField(max_length=255, blank=True)
    snapshot_firm_eik = models.CharField(max_length=9, blank=True)
    snapshot_firm_address = models.CharField(max_length=500, blank=True)
    snapshot_firm_phone = models.CharField(max_length=20, blank=True)

    # When the work was done
    date = models.DateField("Дата на извършване (попълва се на място)", null=True, blank=True)
    # Date the protocol document itself was prepared (footer: "Подготвено от → Дата")
    prepared_date = models.DateField("Дата на изготвяне на протокола", null=True, blank=True)
    time_from = models.TimeField("Час от", null=True, blank=True)
    time_to = models.TimeField("Час до", null=True, blank=True)

    # Who
    prepared_by = models.ForeignKey(
        Worker, on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="prepared_protocols",
        verbose_name="Подготвил (ръководител на ДДД)",
    )
    executed_by = models.ForeignKey(
        Worker, on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="executed_protocols",
        verbose_name="Изпълнил",
    )
    client_signatory = models.CharField(
        "Заявител (подпис)", max_length=255, blank=True,
    )

    # Type of engagement (the two checkboxes in the header)
    is_long_term_contract = models.BooleanField("Дългосрочен договор", default=False)

    # Preset machinery
    is_preset = models.BooleanField("Шаблон", default=False)
    preset_name = models.CharField(
        "Име на пресет", max_length=255, blank=True,
        help_text="Попълва се само когато е шаблон.",
    )

    # Display name used on the protocol list and templates list
    pseudonym = models.CharField(
        "Псевдоним", max_length=255, blank=True,
        help_text="Кратко показно наименование (напр. 'Виктория Нутс'). "
                  "Ако е празно, се използва client.name.",
    )

    # Price — often filled in after the protocol is printed and signed.
    # `price` is always the net (no-VAT) amount — the canonical value used
    # everywhere (dashboard, справки). `price_with_tax` + `tax_rate_snapshot`
    # are only meaningful when `tax_included` is True — see save() below.
    price = models.DecimalField(
        "Цена (лв)", max_digits=10, decimal_places=2,
        null=True, blank=True,
    )
    tax_included = models.BooleanField("Цена с ДДС", default=False)
    price_with_tax = models.DecimalField(
        "Цена с ДДС (лв)", max_digits=10, decimal_places=2,
        null=True, blank=True,
    )
    tax_rate_snapshot = models.DecimalField(
        "ДДС % (за тази цена)", max_digits=5, decimal_places=2,
        null=True, blank=True,
        help_text="Замразен ДДС процент към момента на въвеждане — не се "
                   "променя ако общата настройка за ДДС бъде сменена по-късно.",
    )

    # Template folder — only relevant when is_preset=True
    folder = models.ForeignKey(
        'TemplateFolder',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='templates',
        verbose_name='Папка',
        help_text="Само за шаблони (is_preset=True).",
    )

    # Provenance — set when a protocol is created "from" a template
    # (template_use / protocol_create_from with a preset source).
    source_template = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='generated_protocols',
        verbose_name='Създаден от шаблон',
    )

    # Free-text + tags
    notes = models.TextField("Бележки", blank=True)
    tags = models.ManyToManyField(
        "Tag", blank=True, related_name="protocols", verbose_name="Етикети",
    )

    class Meta:
        verbose_name = "Протокол"
        verbose_name_plural = "Протоколи"
        ordering = ["-date", "-created_at"]

    @property
    def display_name(self) -> str:
        """Best name to show in list/card views.
        For templates (is_preset=True), the user-typed preset_name wins.
        Otherwise pseudonym, falling back to client name as a last resort."""
        if self.is_preset and self.preset_name:
            return self.preset_name
        return self.pseudonym or (self.client.name if self.client_id else "—")

    def __str__(self) -> str:
        if self.is_preset:
            return f"[Пресет] {self.preset_name or self.site}"
        d = self.date.isoformat() if self.date else "без дата"
        return f"{d} — {self.site}"

    def refresh_company_snapshot(self) -> None:
        """Copy the linked company's current text identity into the snapshot."""
        if self.company_id:
            self.snapshot_company_name = self.company.name
            self.snapshot_company_eik = self.company.eik
            self.snapshot_company_address = self.company.address
            self.snapshot_company_phone = self.company.phone

    def refresh_firm_snapshot(self) -> None:
        """Copy the site's currently active Firm's identity into the snapshot."""
        firm = self.site.active_firm if self.site_id else None
        if firm:
            self.snapshot_firm_name = firm.name
            self.snapshot_firm_eik = firm.eik
            self.snapshot_firm_address = firm.address
            self.snapshot_firm_phone = firm.phone

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        if not self.company_id:
            self.company = Company.objects.filter(
                is_default=True, is_active=True
            ).first()
        if self.company_id and not self.snapshot_company_name:
            self.refresh_company_snapshot()
        if self.site_id and not self.snapshot_firm_name:
            self.refresh_firm_snapshot()
        _normalize_tax_fields(self)
        super().save(*args, **kwargs)
        if is_new:
            for code, _ in Product.Category.choices:
                ProtocolColumn.objects.create(protocol=self, service=code)

    @property
    def columns_by_service(self) -> dict:
        from types import SimpleNamespace
        existing = {c.service: c for c in self.columns.all()}
        result = {}
        for code, _ in Product.Category.choices:
            if code in existing:
                result[code] = existing[code]
            else:
                all_pests = list(
                    Pest.objects.filter(category=code).order_by("created_at")
                )
                with_status = [(p, False) for p in all_pests]
                pairs = []
                for i in range(0, len(with_status), 2):
                    left = with_status[i]
                    right = with_status[i + 1] if i + 1 < len(with_status) else None
                    pairs.append((left, right))
                result[code] = SimpleNamespace(
                    pests=SimpleNamespace(all=lambda: []),
                    pests_other="",
                    treated_area_m2=None,
                    surface_description="",
                    treatment_methods_display="",
                    non_chemical_means=SimpleNamespace(all=lambda: []),
                    protocol_products=SimpleNamespace(all=lambda: []),
                    total_used="",
                    recommendations="",
                    corrections="",
                    all_pests_with_status=with_status,
                    pest_pairs=pairs,
                    is_active=False,
                    safety_other="",
                )
        return result

    @property
    def deratization_bait_text(self) -> str:
        """Row 11b deratization cell — auto-built from the deratization
        products' bait descriptors (manufacturer info, edited on the Product)."""
        col = self.columns_by_service["deratization"]
        descriptors = [
            pp.snapshot_bait_descriptor
            for pp in col.protocol_products.all()
            if pp.snapshot_bait_descriptor
        ]
        if not descriptors:
            return ""
        if len(descriptors) == 1:
            return f"...бр. {descriptors[0]}"
        return "....бр. комбинирани примамки - " + " + ".join(descriptors)
    @property
    def pest_grid_rows(self):
        """Visual rows for protocol row 1, with merge instructions.
        Each row: {'dis': {...}, 'der': {...}, 'dinf': {...}} where each value
        has a 'kind' the template switches on."""
        cols = self.columns_by_service

        def make_entries(code, with_other, lower):
            col = cols[code]
            out = [
                {"sel": sel, "name": pest.name.lower() if lower else pest.name}
                for pest, sel in col.all_pests_with_status
            ]
            if with_other:
                other = col.pests_other
                out.append(
                    {"sel": True, "name": other} if other
                    else {"sel": False, "name": "други (опишете)"}
                )
            return out

        dis = make_entries("disinsection", with_other=True, lower=True)
        der = make_entries("deratization", with_other=True, lower=False)
        dinf = make_entries("disinfection", with_other=False, lower=True)

        # Дезинсекция — pair the normal pests; "other" is its own full-width row
        dis_normal, dis_other = dis[:-1], dis[-1]
        dis_rows = []
        for i in range(0, len(dis_normal), 2):
            right = dis_normal[i + 1] if i + 1 < len(dis_normal) else None
            dis_rows.append({"kind": "pairs", "left": dis_normal[i], "right": right})
        dis_rows.append({"kind": "other", "entry": dis_other})

        # Дезинфекция — plain pest rows, no "other"
        dinf_rows = [{"kind": "pest", "entry": e} for e in dinf]

        # total visual row count
        der_normal, der_other = der[:-1], der[-1]
        n = max(len(dis_rows), len(der_normal) + 1, len(dinf_rows))

        # Дератизация — normal pests, then "other" spanning all remaining rows
        der_rows = [{"kind": "pest", "entry": e} for e in der_normal]
        der_rows.append({
            "kind": "other", "entry": der_other,
            "rowspan": n - len(der_normal),
        })
        der_rows += [{"kind": "covered"}] * (n - len(der_rows))

        # pad дезинсекция / дезинфекция to n
        dis_rows += [{"kind": "empty"}] * (n - len(dis_rows))
        dinf_rows += [{"kind": "empty"}] * (n - len(dinf_rows))

        return [
            {"dis": dis_rows[i], "der": der_rows[i], "dinf": dinf_rows[i]}
            for i in range(n)
        ]

    @property
    def row11_show_total(self) -> bool:
        """Row 11a ("Общо количество...") shows if Дезинсекция or Дезинфекция active."""
        cols = self.columns_by_service
        return cols["disinsection"].is_active or cols["disinfection"].is_active

    @property
    def row11_show_baits(self) -> bool:
        """Row 11b ("Брой на поставените... кутии") shows if Дератизация active."""
        return self.columns_by_service["deratization"].is_active

    @property
    def row10_on_back(self) -> bool:
        """Decide whether row 10 (working solution) belongs on the back panel.
        True when its content is bulky enough to crowd the front."""
        cols = self.columns_by_service

        def column_volume(code):
            return sum(
                len(pp.snapshot_working_solution or "")
                for pp in cols[code].protocol_products.all()
            )

        busiest = max(
            column_volume(c)
            for c in ("disinsection", "deratization", "disinfection")
        )
        return busiest > 355  # threshold of char length to decide where row 10 will be displayed (front or back of the protocol)

class ProtocolColumn(TimeStampedModel):
    """One service column on a protocol (Disinsection / Deratization / Disinfection)."""

    class TreatmentMethod(models.TextChoices):
        MECHANICAL = "mechanical", "Механична"
        PHYSICAL = "physical", "Физична"
        BIOLOGICAL = "biological", "Биологична"
        CHEMICAL_BIOCIDE = "chemical_biocide", "Химична с биоцидни sпрепарати"

    protocol = models.ForeignKey(
        Protocol, on_delete=models.CASCADE,
        related_name="columns", verbose_name="Протокол",
    )
    service = models.CharField(
        "Услуга", max_length=20, choices=Product.Category.choices,
    )

    # Row 1 — pests/spectrum
    pests = models.ManyToManyField(
        Pest, blank=True, related_name="protocol_columns", verbose_name="Вредители / спектър",
    )
    pests_other = models.CharField(
        "Други (опишете)", max_length=255, blank=True,
    )

    # Row 2
    treated_area_m2 = models.PositiveIntegerField(
        "Обработена площ (m²)", null=True, blank=True,
    )

    # Row 3
    surface_description = models.TextField("Вид на обработените площи", blank=True)

    # Row 4 — multi-select of TreatmentMethod values
    treatment_methods = models.JSONField(
        "Вид на обработката", default=list, blank=True, null=True
    )

    # Row 5
    non_chemical_means = models.ManyToManyField(
        NonChemicalMean, blank=True,
        related_name="protocol_columns", verbose_name="Нехимични средства",
    )

    # Rows 6–10, 12.x come from products (M2M through ProtocolProduct, defined below)

    # Row 11 — total used / bait box counts (handwritten in printout)
    total_used = models.TextField(
        "Общо изразходван препарат / брой кутии", blank=True,
    )
    is_active = models.BooleanField(
        "Активна услуга", default=True,
        help_text="Маркирай услугите, които този протокол реално покрива.",
    )
    safety_other = models.TextField("Други мерки за безопасност (12.5)", blank=True)
    # Rows 13 + 14 — per-column free text
    recommendations = models.TextField("Препоръки (ред 13)", blank=True)
    corrections = models.TextField("Промени и корекции (ред 14)", blank=True)

    class Meta:
        verbose_name = "Колона от протокол"
        verbose_name_plural = "Колони от протокол"
        ordering = ["service"]
        constraints = [
            models.UniqueConstraint(
                fields=["protocol", "service"],
                name="unique_service_per_protocol",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_service_display()} ({self.protocol})"

    @property
    def treatment_methods_display(self) -> str:
        labels = dict(self.TreatmentMethod.choices)
        return ", ".join(labels.get(m, m) for m in (self.treatment_methods or []))

    @property
    def all_pests_with_status(self):
        """[(pest, is_selected), ...] in regulatory (seed) order."""
        selected_ids = set(self.pests.values_list("id", flat=True))
        return [
            (pest, pest.id in selected_ids)
            for pest in Pest.objects.filter(category=self.service).order_by("created_at")
        ]

    @property
    def pest_pairs(self):
        """List of (left, right) pairs of (pest, selected) — right is None on odd count."""
        items = self.all_pests_with_status
        pairs = []
        for i in range(0, len(items), 2):
            left = items[i]
            right = items[i + 1] if i + 1 < len(items) else None
            pairs.append((left, right))
        return pairs

class ProtocolProduct(models.Model):
    """A product used in a ProtocolColumn, with a snapshot of its data at save time."""

    column = models.ForeignKey(
        ProtocolColumn, on_delete=models.CASCADE,
        related_name="protocol_products", verbose_name="Колона",
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT,
        related_name="protocol_uses", verbose_name="Препарат",
    )
    order = models.PositiveSmallIntegerField("Ред", default=0)

    # --- Snapshot of Product fields, frozen at save time ---
    snapshot_name = models.CharField(max_length=255, blank=True)
    snapshot_authorization_no = models.CharField(max_length=100, blank=True)
    snapshot_formulation = models.CharField(max_length=255, blank=True)
    snapshot_active_substances = models.TextField(blank=True)
    snapshot_working_solution = models.TextField(blank=True)
    snapshot_action_time = models.CharField(max_length=255, blank=True)
    snapshot_antidote = models.CharField(max_length=255, blank=True)
    snapshot_safety_instructions = models.TextField(blank=True)
    snapshot_access_info = models.TextField(blank=True)
    snapshot_surfaces_to_wipe = models.CharField(max_length=255, blank=True)
    snapshot_bait_descriptor = models.CharField(max_length=255, blank=True)
    SNAPSHOT_FIELDS = (
        "name", "authorization_no", "formulation", "active_substances",
        "working_solution", "action_time", "antidote",
        "safety_instructions", "access_info", "surfaces_to_wipe",
        "bait_descriptor",
    )

    class Meta:
        verbose_name = "Препарат в протокол"
        verbose_name_plural = "Препарати в протокол"
        ordering = ["order"]

    def __str__(self) -> str:
        return self.snapshot_name or (self.product.name if self.product_id else "—")

    def refresh_snapshot(self) -> None:
        """Copy current Product field values into snapshot_* fields."""
        for f in self.SNAPSHOT_FIELDS:
            setattr(self, f"snapshot_{f}", getattr(self.product, f))

    def save(self, *args, **kwargs):
        # On first save, populate the snapshot from the linked product.
        # On later saves we leave the snapshot alone unless someone explicitly
        # calls refresh_snapshot() (which presets do when loaded).
        if not self.pk and self.product_id and not self.snapshot_name:
            self.refresh_snapshot()
        super().save(*args, **kwargs)

class OneTimeTreatment(TimeStampedModel):
    """A DDD job done without a formal protocol (apartments, small basements, etc.)."""

    pseudonym = models.CharField(
        "Псевдоним", max_length=255,
        help_text="Кратко показно наименование (напр. 'Ап. Иванови').",
    )
    address = models.CharField("Адрес", max_length=500, blank=True)

    date = models.DateField("Дата", default=_date.today)
    time_from = models.TimeField("Час от", null=True, blank=True)
    time_to = models.TimeField("Час до", null=True, blank=True)

    # list of 'disinsection' / 'deratization' / 'disinfection'
    service_types = models.JSONField("Услуги", default=list, blank=True)

    pests = models.ManyToManyField(
        Pest, blank=True,
        related_name="one_time_treatments",
        verbose_name="Вредители / спектър",
    )
    pests_other = models.CharField(
        "Други (опишете)", max_length=255, blank=True,
        help_text="Разделени със запетая, ако са повече от един.",
    )
    executed_by = models.ManyToManyField(
        Worker, blank=True,
        related_name="one_time_treatments",
        verbose_name="Изпълнители",
    )
    tags = models.ManyToManyField(
        Tag, blank=True,
        related_name="one_time_treatments",
        verbose_name="Етикети",
    )

    # `price` is always the net (no-VAT) amount — see _normalize_tax_fields().
    price = models.DecimalField(
        "Цена (лв)", max_digits=10, decimal_places=2,
        null=True, blank=True,
    )
    tax_included = models.BooleanField("Цена с ДДС", default=False)
    price_with_tax = models.DecimalField(
        "Цена с ДДС (лв)", max_digits=10, decimal_places=2,
        null=True, blank=True,
    )
    tax_rate_snapshot = models.DecimalField(
        "ДДС % (за тази цена)", max_digits=5, decimal_places=2,
        null=True, blank=True,
    )
    notes = models.TextField("Бележки", blank=True)

    class Meta:
        verbose_name = "Еднократна обработка"
        verbose_name_plural = "Еднократни обработки"
        ordering = ["-date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.date} — {self.pseudonym}"

    def save(self, *args, **kwargs):
        _normalize_tax_fields(self)
        super().save(*args, **kwargs)


class OneTimeTreatmentProduct(models.Model):
    """A biocide product used in a OneTimeTreatment, with free-text quantity."""

    treatment = models.ForeignKey(
        OneTimeTreatment, on_delete=models.CASCADE,
        related_name="products", verbose_name="Обработка",
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT,
        related_name="one_time_uses", verbose_name="Препарат",
    )
    concentration = models.CharField(
        "Концентрация", max_length=100, blank=True,
        help_text="Напр. '0.1%', '1:100'.",
    )
    quantity_text = models.CharField(
        "Количество", max_length=100, blank=True,
        help_text="Напр. '50 мл', '2 примамки'.",
    )
    order = models.PositiveSmallIntegerField("Ред", default=0)

    class Meta:
        verbose_name = "Препарат в еднократна обработка"
        verbose_name_plural = "Препарати в еднократни обработки"
        ordering = ["order"]

    def __str__(self) -> str:
        return f"{self.product.name} ({self.treatment})"


class OneTimeTreatmentContact(models.Model):
    """Contact person for a single OneTimeTreatment job. UI-only — not printed."""

    treatment = models.ForeignKey(
        OneTimeTreatment, on_delete=models.CASCADE,
        related_name="contacts", verbose_name="Обработка",
    )
    name = models.CharField("Име", max_length=255)
    phone = models.CharField("Телефон", max_length=20, blank=True)
    position = models.CharField("Длъжност", max_length=255, blank=True)
    order = models.PositiveSmallIntegerField("Ред", default=0)

    class Meta:
        verbose_name = "Контактно лице (еднократна обработка)"
        verbose_name_plural = "Контактни лица (еднократни обработки)"
        ordering = ["order"]

    def __str__(self) -> str:
        return f"{self.name} — {self.treatment}"


# ─────────────────────────────────────────────────────────────────────────────
# App Settings — singleton (pk=1 always)
# ─────────────────────────────────────────────────────────────────────────────

class AppSettings(models.Model):
    """Single-row settings table for app-wide preferences."""

    class Theme(models.TextChoices):
        CORAL  = 'coral',  'Coral'
        SLATE  = 'slate',  'Slate'
        SILVER = 'silver', 'Silver'
        DARK   = 'dark',   'Dark'

    class ProtocolFormat(models.TextChoices):
        A5      = 'a5',      'A5 (2 стр.)'
        A5_LAND = 'a5-land', 'A5 → A4 пейзаж'
        A4_P    = 'a4-p',    'A4 портрет'

    theme = models.CharField(
        'Тема', max_length=20,
        choices=Theme.choices, default=Theme.CORAL,
    )
    default_protocol_format = models.CharField(
        'Формат на протокол по подразбиране', max_length=20,
        choices=ProtocolFormat.choices, default=ProtocolFormat.A5,
    )

    # ── Pricing (price/VAT toggle on protocols + one-time treatments) ────
    vat_percent = models.DecimalField(
        'ДДС %', max_digits=5, decimal_places=2, default=20,
        help_text='Използва се за изчисляване на цената с ДДС. Промяна тук '
                   'засяга само нови/бъдещи изчисления — вече запазени цени '
                   'пазят своя замразен процент.',
    )

    # ── OneDrive / backup sync (Stage 6a) ─────────────────────────────────
    SYNC_INTERVAL_CHOICES = [
        (5, '5 минути'),
        (15, '15 минути'),
        (30, '30 минути'),
        (60, '60 минути'),
    ]

    sync_folder_path = models.CharField(
        'Папка за резервно копие', max_length=500, blank=True, default='',
    )
    sync_interval_minutes = models.PositiveIntegerField(
        'Интервал на синхронизация', choices=SYNC_INTERVAL_CHOICES, default=15,
    )
    sync_auto_enabled = models.BooleanField(
        'Автоматична синхронизация', default=True,
    )
    data_version = models.DateTimeField(
        'Версия на данните', default=timezone.now,
    )

    class Meta:
        verbose_name = 'Настройки на приложението'

    @classmethod
    def get(cls):
        """Return the singleton row, creating it if it doesn't exist."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    # ── CSS variable overrides per theme ──────────────────────────────────
    _THEME_VARS = {
        'coral': '',   # default — no override needed
        'slate': """
            --c-plum:#1e293b; --c-coral:#3b82f6; --c-clay:#2563eb;
            --c-mauve:#4a7abf; --c-peach:#93c5fd;
            --sidebar-bg:#1e293b; --sidebar-brand-bg:#0f172a;
            --nav-text-active:#93c5fd; --nav-bg-hover:#273549;
            --nav-bg-active:#2d4060; --nav-accent-active:#3b82f6;
            --nav-sub-bg:#162030; --nav-sub-bg-hover:#243550;
            --version-text:#334f70;
            --content-bg:#f1f5f9; --card-bg:#ffffff;
            --text-primary:#0f172a; --text-muted:#64748b;
            --border-subtle:rgba(100,116,139,0.2);
            --btn-primary-bg:#3b82f6; --btn-primary-hover:#2563eb;
        """,
        'silver': """
            --c-plum:#3a3d42; --c-coral:#6b8cba; --c-clay:#5a7aaa;
            --c-mauve:#7a9cbf; --c-peach:#a8c0d8;
            --sidebar-bg:#3a3d42; --sidebar-brand-bg:#25272b;
            --nav-text-active:#a8c0d8; --nav-bg-hover:#454850;
            --nav-bg-active:#4e5158; --nav-accent-active:#6b8cba;
            --nav-sub-bg:#2e3035; --nav-sub-bg-hover:#3a3d44;
            --version-text:#5a6070;
            --content-bg:#edeef0; --card-bg:#ffffff;
            --text-primary:#25272b; --text-muted:#8a8f96;
            --border-subtle:rgba(100,105,115,0.18);
            --btn-primary-bg:#6b8cba; --btn-primary-hover:#5a7aaa;
        """,
        'dark': """
            --c-plum:#111827; --c-coral:#c0533a; --c-clay:#a04530;
            --c-mauve:#8a4030; --c-peach:#fec196;
            --sidebar-bg:#111827; --sidebar-brand-bg:#0a0f1a;
            --nav-text-active:#fec196; --nav-bg-hover:#1f2937;
            --nav-bg-active:#243040; --nav-accent-active:#c0533a;
            --nav-sub-bg:#0d1420; --nav-sub-bg-hover:#1a2232;
            --version-text:#374151;
            --content-bg:#1f2937; --card-bg:#111827;
            --text-primary:#f9fafb; --text-muted:#9ca3af;
            --border-subtle:rgba(255,255,255,0.1);
            --btn-primary-bg:#c0533a; --btn-primary-hover:#a04530;
        """,
    }

    @property
    def theme_css_vars(self):
        return self._THEME_VARS.get(self.theme, '')

