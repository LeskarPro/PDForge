from django import forms
from core.models import Client, Site, SiteContact, Tag, OneTimeTreatment, Product, Pest, NonChemicalMean, Worker, Company


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ['firm', 'name', 'eik', 'address', 'phone', 'notes']
        widgets = {
            'firm':    forms.TextInput(attrs={'placeholder': '„Виктория Нутс" ЕООД'}),
            'name':    forms.TextInput(attrs={'placeholder': 'Виктория Нутс'}),
            'eik':     forms.TextInput(attrs={'placeholder': '123456789', 'maxlength': '9'}),
            'address': forms.TextInput(attrs={'placeholder': 'гр. Sofia, бул. Дондуков 22'}),
            'phone':   forms.TextInput(attrs={'placeholder': '02 123 4567'}),
            'notes':   forms.Textarea(attrs={'rows': 3, 'placeholder': 'Бележки…'}),
        }


class SiteForm(forms.ModelForm):
    class Meta:
        model = Site
        fields = ['pseudonym', 'name', 'address', 'area_m2', 'notes', 'tags']
        widgets = {
            'pseudonym': forms.TextInput(attrs={'placeholder': 'напр. Магазин Център'}),
            'name':    forms.TextInput(attrs={'placeholder': 'Магазин №1'}),
            'address': forms.TextInput(attrs={'placeholder': 'ул. Витоша 15, гр. Sofia'}),
            'area_m2': forms.NumberInput(attrs={'placeholder': '120', 'min': '1'}),
            'notes':   forms.Textarea(attrs={'rows': 3, 'placeholder': 'Бележки…'}),
            'tags':    forms.CheckboxSelectMultiple(),
        }


class SiteContactForm(forms.ModelForm):
    class Meta:
        model = SiteContact
        fields = ['name', 'phone', 'position']
        widgets = {
            'name':     forms.TextInput(attrs={'placeholder': 'Иван Петров'}),
            'phone':    forms.TextInput(attrs={'placeholder': '0888 123 456'}),
            'position': forms.TextInput(attrs={'placeholder': 'Управител'}),
        }

class SiteFormFull(SiteForm):
    """SiteForm + client selector — used when creating a site from the Обекти page."""
    client = forms.ModelChoiceField(
        queryset=Client.objects.filter(deleted_at__isnull=True).order_by('firm'),
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

    class Meta:
        model = OneTimeTreatment
        fields = [
            'pseudonym', 'address', 'contact_name', 'phone',
            'date', 'time_from', 'time_to',
            'pests', 'executed_by', 'tags',
            'price', 'notes',
        ]
        widgets = {
            'pseudonym':     forms.TextInput(attrs={'placeholder': 'напр. бл.41, Ап. 43'}),
            'address':       forms.TextInput(attrs={'placeholder': 'ул. Витоша 15, ет. 3, ап. 8'}),
            'contact_name':  forms.TextInput(attrs={'placeholder': 'Иван Иванов'}),
            'phone':         forms.TextInput(attrs={'placeholder': '0888 123 456'}),
            'date':          forms.DateInput(attrs={'type': 'date'}),
            'time_from':     forms.TimeInput(attrs={'type': 'time'}),
            'time_to':       forms.TimeInput(attrs={'type': 'time'}),
            'pests':         forms.CheckboxSelectMultiple(),
            'executed_by':   forms.CheckboxSelectMultiple(),
            'tags':          forms.CheckboxSelectMultiple(),
            'price':         forms.NumberInput(attrs={'placeholder': '85.00', 'step': '0.01', 'min': '0'}),
            'notes':         forms.Textarea(attrs={'rows': 3, 'placeholder': 'Бележки…'}),
        }

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

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.service_types = self.cleaned_data.get('service_types', [])
        if commit:
            instance.save()
            self._save_m2m()
        return instance