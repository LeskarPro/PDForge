from django import forms
from decimal import Decimal, InvalidOperation
from core.models import (
    Client, Site, Firm, SiteFirm, Contact, Tag, OneTimeTreatment, Product, Pest,
    NonChemicalMean, Worker, Company, PriceCatalogItem, _first_of_this_month,
)
from core.notes_html import sanitize_notes_html


class MonthField(forms.DateField):
    """Date field whose UI only collects month+year (day is pinned to 1).

    Used for Firm/Site start_date and end_date — Stage 8a/8b granularity.
    """
    widget = forms.DateInput(attrs={'type': 'month'}, format='%Y-%m')
    input_formats = ['%Y-%m']


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ['name', 'notes']
        widgets = {
            'name':    forms.TextInput(attrs={'placeholder': 'Виктория Нутс'}),
            'notes':   forms.Textarea(attrs={'rows': 3, 'placeholder': 'Бележки…'}),
        }

    def clean_notes(self):
        # Stage 10e: notes arrive as minimal HTML from the .rn-editable
        # widget — whitelist-sanitize before it ever touches the DB.
        return sanitize_notes_html(self.cleaned_data.get('notes', ''))


class FirmForm(forms.ModelForm):
    """A reusable legal-entity record (Stage 8a, reworked 2026-06-19).

    No dates/active state of its own — a Firm can be linked to several
    Sites at once, and the date range / active flag for each link lives on
    SiteFirm (below), since the same firm can be active for one site and
    ended for another.
    """

    class Meta:
        model = Firm
        fields = ['name', 'eik', 'address', 'phone']
        widgets = {
            'name':    forms.TextInput(attrs={'placeholder': '„Виктория Нутс" ЕООД'}),
            'eik':     forms.TextInput(attrs={'placeholder': '123456789', 'maxlength': '9'}),
            'address': forms.TextInput(attrs={'placeholder': 'гр. Sofia, бул. Дондуков 22'}),
            'phone':   forms.TextInput(attrs={'placeholder': '02 123 4567'}),
        }

    def clean_eik(self):
        # Firm.eik has a conditional unique constraint (non-empty, non-deleted
        # only) — Django's ModelForm validation doesn't check conditional
        # UniqueConstraints, so without this the duplicate only surfaces as
        # an uncaught IntegrityError at save() time. Covers both create and
        # edit (Фирми page) since both go through this same form; excludes
        # the instance's own row so re-saving an unchanged firm doesn't
        # false-flag itself.
        eik = (self.cleaned_data.get('eik') or '').strip()
        if not eik:
            return eik
        existing = Firm.objects.filter(eik=eik, deleted_at__isnull=True)
        if self.instance and self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        dupe = existing.first()
        if dupe:
            raise forms.ValidationError(
                f'Вече има фирма с този ЕИК: {dupe.name}'
            )
        return eik


class SiteFirmForm(forms.ModelForm):
    """Links a Firm to a Site for a date range (Stage 8a, reworked).

    `firm` and `site` are deliberately excluded here and set explicitly in
    the view — this form only covers the link's own active/date fields,
    used identically whether the view is creating a brand-new Firm or
    reusing an existing one (see core/views.py site_firm_link_create).
    """
    start_date = MonthField(label="Начална дата", required=False)
    end_date = MonthField(label="Крайна дата", required=False)

    class Meta:
        model = SiteFirm
        fields = ['is_active', 'start_date', 'end_date']

    def clean_start_date(self):
        return self.cleaned_data.get('start_date') or _first_of_this_month()


class SiteForm(forms.ModelForm):
    start_date = MonthField(label="Начална дата", required=False)
    end_date = MonthField(label="Крайна дата", required=False)

    class Meta:
        model = Site
        fields = ['pseudonym', 'name', 'address', 'area_m2', 'notes', 'tags',
                  'is_active', 'start_date', 'end_date']
        widgets = {
            'pseudonym': forms.TextInput(attrs={'placeholder': 'напр. Магазин Център'}),
            'name':    forms.TextInput(attrs={'placeholder': 'Магазин №1'}),
            'address': forms.TextInput(attrs={'placeholder': 'ул. Витоша 15, гр. Sofia'}),
            'area_m2': forms.NumberInput(attrs={'placeholder': '120', 'min': '1'}),
            'notes':   forms.Textarea(attrs={'rows': 3, 'placeholder': 'Бележки…'}),
            'tags':    forms.CheckboxSelectMultiple(),
        }

    def clean_start_date(self):
        return self.cleaned_data.get('start_date') or _first_of_this_month()

    def clean_notes(self):
        # Stage 10e — see ClientForm.clean_notes(). SiteFormFull inherits
        # this automatically (it only adds a `client` field on top).
        return sanitize_notes_html(self.cleaned_data.get('notes', ''))


class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ['name', 'phone', 'position']
        widgets = {
            'name':     forms.TextInput(attrs={'placeholder': 'Иван Петров'}),
            'phone':    forms.TextInput(attrs={'placeholder': '0888 123 456'}),
            'position': forms.TextInput(attrs={'placeholder': 'Управител'}),
        }

class SiteFormFull(SiteForm):
    """SiteForm + client selector — used when creating a site from the Обекти page."""
    client = forms.ModelChoiceField(
        queryset=Client.objects.filter(deleted_at__isnull=True).order_by('name'),
        label="Клиент",
        empty_label="— изберете клиент —",
    )

    class Meta(SiteForm.Meta):
        fields = ['client'] + SiteForm.Meta.fields

class TagForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = ['name', 'color', 'description']
        widgets = {
            'name': forms.TextInput(attrs={
                'placeholder': 'напр. Апартамент, Завод, Скал…',
            }),
            'color': forms.TextInput(attrs={
                'type': 'color',
                'class': 'color-native-input',
            }),
            'description': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Кратко описание за какво се използва…',
            }),
        }

class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ['name', 'eik', 'address', 'phone', 'slogan', 'logo', 'is_active']
        widgets = {
            'name':    forms.TextInput(attrs={'placeholder': 'напр. „ДДД Про" ЕООД'}),
            'eik':     forms.TextInput(attrs={'placeholder': '123456789'}),
            'address': forms.TextInput(attrs={'placeholder': 'гр. София, бул. Витоша 1'}),
            'phone':   forms.TextInput(attrs={'placeholder': '02 123 4567'}),
            'slogan':  forms.TextInput(attrs={'placeholder': 'напр. Вашата защита е наша грижа'}),
            'logo':    forms.FileInput(),  # plain FileInput — no "Изчисти" checkbox
        }


class PestForm(forms.ModelForm):
    class Meta:
        model = Pest
        fields = ['name', 'category']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'напр. Хлебарки'}),
        }


class NonChemicalMeanForm(forms.ModelForm):
    class Meta:
        model = NonChemicalMean
        fields = ['name', 'category', 'notes']
        widgets = {
            'name':  forms.TextInput(attrs={'placeholder': 'напр. Лепкава примамка'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Бележки…'}),
        }

    def clean_notes(self):
        # Stage 10e-2 — see ClientForm.clean_notes().
        return sanitize_notes_html(self.cleaned_data.get('notes', ''))


class PriceCatalogItemForm(forms.ModelForm):
    """Ценообразуване — the billable-item catalog (Stage 3 of the price
    module). item_type stays a plain <select>; the NCM-link field is only
    meaningful for 'product' — cleared server-side when type is 'service'
    (the JS in _form.html hides the field client-side, but the form doesn't
    trust that alone)."""

    class Meta:
        model = PriceCatalogItem
        fields = ['name', 'item_type', 'non_chemical_mean', 'default_price']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'напр. Извънредно посещение'}),
            'default_price': forms.TextInput(attrs={
                'placeholder': 'напр. 3.50 (по избор)', 'inputmode': 'decimal',
            }),
        }

    def __init__(self, *args, **kwargs):
        # Same comma/dot normalization as OneTimeTreatmentForm — Django's
        # own DecimalField validation runs before clean_default_price()
        # and rejects a comma outright, so normalize before the form binds.
        data = args[0] if args else kwargs.get('data')
        if data:
            data = data.copy()
            if data.get('default_price'):
                data['default_price'] = str(data['default_price']).replace(',', '.')
            if args:
                args = (data,) + args[1:]
            else:
                kwargs['data'] = data
        super().__init__(*args, **kwargs)
        self.fields['non_chemical_mean'].required = False
        self.fields['non_chemical_mean'].queryset = (
            NonChemicalMean.objects.filter(deleted_at__isnull=True).order_by('category', 'name')
        )
        self.fields['default_price'].required = False

    def clean_default_price(self):
        raw = (self.data.get('default_price') or '').strip()
        if not raw:
            return None
        raw = raw.replace(',', '.')
        try:
            return Decimal(raw)
        except InvalidOperation:
            raise forms.ValidationError("Въведете валидна цена (напр. 3.50 или 3,50).")

    def clean(self):
        cleaned = super().clean()
        # A service item is never linked to a non-chemical product —
        # product is the only type this relationship makes sense for.
        if cleaned.get('item_type') == PriceCatalogItem.ItemType.SERVICE:
            cleaned['non_chemical_mean'] = None
        return cleaned


class WorkerForm(forms.ModelForm):
    class Meta:
        model = Worker
        fields = ['name', 'role', 'is_default_supervisor', 'is_default_executor', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'напр. Иван Петров'}),
            'role': forms.TextInput(attrs={'placeholder': 'напр. ДДД специалист'}),
        }


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'pseudonym', 'name', 'category',
            'authorization_no', 'formulation', 'active_substances',
            'working_solution', 'action_time', 'antidote',
            'safety_instructions', 'access_info', 'surfaces_to_wipe',
            'bait_descriptor', 'notes',
        ]
        widgets = {
            'pseudonym':           forms.TextInput(attrs={'placeholder': 'напр. Айкън 25% – стандарт'}),
            'name':                forms.TextInput(attrs={'placeholder': 'напр. Ikon 25 EC'}),
            'category':            forms.Select(),
            'authorization_no':    forms.TextInput(attrs={'placeholder': 'напр. BG-2023-0042'}),
            'formulation':         forms.TextInput(attrs={'placeholder': 'напр. EC, SC, WP…'}),
            'active_substances':   forms.Textarea(attrs={'rows': 2, 'placeholder': 'напр. Циперметрин 25 г/л'}),
            'working_solution':    forms.TextInput(attrs={'placeholder': 'напр. 20 мл / 10 л вода'}),
            'action_time':         forms.TextInput(attrs={'placeholder': 'напр. 24 часа'}),
            'antidote':            forms.TextInput(attrs={'placeholder': 'напр. Витамин К1'}),
            'safety_instructions': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Мерки за безопасност…'}),
            'access_info':         forms.Textarea(attrs={'rows': 2, 'placeholder': 'Достъп до обработените площи…'}),
            'surfaces_to_wipe':    forms.TextInput(attrs={'placeholder': 'напр. Хранителни повърхности'}),
            'bait_descriptor':     forms.TextInput(attrs={'placeholder': 'напр. Парафинова примамка с бромадиолон 0.005%'}),
            'notes':               forms.Textarea(attrs={'rows': 2, 'placeholder': 'Бележки…'}),
        }

    def clean_notes(self):
        # Stage 10e-2 — see ClientForm.clean_notes().
        return sanitize_notes_html(self.cleaned_data.get('notes', ''))


SERVICE_TYPE_CHOICES = [
    ('disinsection', 'Дезинсекция'),
    ('deratization', 'Дератизация'),
    ('disinfection', 'Дезинфекция'),
]

class OneTimeTreatmentForm(forms.ModelForm):
    service_types = forms.MultipleChoiceField(
        choices=SERVICE_TYPE_CHOICES,
        widget=forms.CheckboxSelectMultiple(),
        required=False,
        label="Услуги",
    )
    date = forms.DateField(
        label="Дата",
        widget=forms.DateInput(attrs={'type': 'date'}),
        input_formats=['%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y'],
        required=False,
    )

    class Meta:
        model = OneTimeTreatment
        fields = [
            'pseudonym', 'address',
            'date', 'time_from', 'time_to',
            'pests', 'pests_other', 'executed_by', 'tags',
            'tax_included', 'document_status', 'payment_type', 'notes',
        ]
        widgets = {
            'pseudonym':     forms.TextInput(attrs={'placeholder': 'напр. бл.41, Ап. 43'}),
            'address':       forms.TextInput(attrs={'placeholder': 'ул. Витоша 15, ет. 3, ап. 8'}),
            'time_from':     forms.TimeInput(attrs={'type': 'time'}),
            'time_to':       forms.TimeInput(attrs={'type': 'time'}),
            'pests':         forms.CheckboxSelectMultiple(),
            'pests_other':   forms.TextInput(attrs={'placeholder': 'опишете, разделени със запетая — напр. молци, бълхи'}),
            'executed_by':   forms.CheckboxSelectMultiple(),
            'tags':          forms.CheckboxSelectMultiple(),
            'tax_included':  forms.CheckboxInput(),
            'notes':         forms.Textarea(attrs={'rows': 3, 'placeholder': 'Бележки…'}),
        }
        # price / price_with_tax are NOT form fields anymore (Stage 5 —
        # price module): they're computed from the line-items table by
        # _save_treatment_line_items() after this form saves, same as
        # Protocol (Stage 4). payment_type follows document_status's
        # existing pattern — a real Meta field, but rendered by hand as a
        # hidden input + pill switch in the template, not the default widget.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['pests'].queryset = (
            Pest.objects.filter(deleted_at__isnull=True).order_by('category', 'name')
        )
        self.fields['executed_by'].queryset = (
            Worker.objects.filter(is_active=True, deleted_at__isnull=True).order_by('name')
        )
        self.fields['tags'].queryset = (
            Tag.objects.filter(deleted_at__isnull=True).order_by('order', 'name')
        )
        if self.instance.pk:
            self.fields['service_types'].initial = self.instance.service_types or []

    def clean_notes(self):
        # Stage 10e-3 — see ClientForm.clean_notes().
        return sanitize_notes_html(self.cleaned_data.get('notes', ''))

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.service_types = self.cleaned_data.get('service_types', [])
        if commit:
            instance.save()
            self._save_m2m()
        return instance