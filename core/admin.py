from django.contrib import admin
from django import forms
from core.models import *

# Register your models here.

class SiteInLine(admin.TabularInline):
    """Lets you edit a Client's Sites directly on the Client edit page."""

    model = Site
    extra = 1
    fields = ["name", "address", "area_m2"]

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    """Admin for Clients."""

    list_display = ("firm", "name", "eik", "phone", "address")
    search_fields = ("firm", "name", "eik", "address")
    inlines = [SiteInLine]

@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    """Admin for Sites."""

    list_display = ("client", "pseudonym", "name", "address", "notes")
    search_fields = ("pseudonym", "name", "address", "client__name", "client__eik", "client__firm")
    list_filter = ("client", "tags",)
    autocomplete_fields = ("client",)
    filter_horizontal = ("tags",)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Admin for Products."""

    list_display = ("name", "category", "authorization_no", "formulation")
    list_filter = ("category",)
    search_fields = ("name", "active_substances", "category")
    fieldsets = (
        ("Основни данни", {
            "fields": ("name", "category", "authorization_no", "formulation"),
        }),
        ("Състав и приложение", {
            "fields": ("active_substances", "working_solution", "bait_descriptor"),
        }),
        ("Безопасност", {
            "fields": ("safety_instructions", "access_info", "surfaces_to_wipe",
                       "action_time", "antidote"),
        }),
        ("Други", {
            "fields": ("notes",),
            "classes": ("collapse",),
        }),
    )

@admin.register(Pest)
class PestAdmin(admin.ModelAdmin):
    list_display = ("name", "category")
    list_filter = ("category",)
    search_fields = ("name",)


@admin.register(NonChemicalMean)
class NonChemicalMeanAdmin(admin.ModelAdmin):
    list_display = ("name", "category",)
    list_filter = ("category",)
    search_fields = ("name",)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "color", "site_count")
    search_fields = ("name",)

    @admin.display(description="Брой обекти")
    def site_count(self, obj):
        return obj.sites.count()


class ProtocolProductInline(admin.TabularInline):
    """Edit a column's products inline."""
    model = ProtocolProduct
    extra = 0
    fields = ("product", "order", "snapshot_name", "snapshot_working_solution")
    readonly_fields = ("snapshot_name", "snapshot_working_solution")
    autocomplete_fields = ("product",)

class ProtocolColumnForm(forms.ModelForm):
    """Custom form so treatment_methods renders as checkboxes, not raw JSON."""

    treatment_methods = forms.MultipleChoiceField(
        choices=ProtocolColumn.TreatmentMethod.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Вид на обработката",
    )

    class Meta:
        model = ProtocolColumn
        fields = "__all__"

@admin.register(ProtocolColumn)
class ProtocolColumnAdmin(admin.ModelAdmin):
    form = ProtocolColumnForm
    list_display = ("protocol", "service", "treated_area_m2")
    list_filter = ("service",)
    autocomplete_fields = ("protocol",)
    filter_horizontal = ("pests", "non_chemical_means")
    inlines = [ProtocolProductInline]


class ProtocolColumnInline(admin.StackedInline):
    model = ProtocolColumn
    form = ProtocolColumnForm
    extra = 0
    readonly_fields = ("service",)             # <-- add this
    fields = (
        "service", "is_active",
        "pests", "pests_other",
        "treated_area_m2",
        "surface_description",
        "treatment_methods",
        "non_chemical_means",
        "total_used",
        "safety_other",  # row 12.5
        "recommendations",
        "corrections",
    )
    filter_horizontal = ("pests", "non_chemical_means")
    can_delete = False                          # <-- prevent accidental column deletion
    show_change_link = True

@admin.register(Protocol)
class ProtocolAdmin(admin.ModelAdmin):
    list_display = (
        "client", "site", "prepared_by", "executed_by",
        "is_preset", "preset_name",
    )
    list_filter = ("is_preset", "is_long_term_contract", "tags", "client", "prepared_by")
    search_fields = (
        "client__firm", "client__name", "site__name", "preset_name", "notes",
    )
    autocomplete_fields = ("client", "site", "prepared_by", "executed_by")
    filter_horizontal = ("tags",)
    inlines = [ProtocolColumnInline]
    fieldsets = (
        (None, {
            "fields": ("client", "site", "date", "time_from", "time_to"),
        }),
        ("Подписи и тип", {
            "fields": (
                "prepared_by", "executed_by", "client_signatory",
                "is_long_term_contract",
            ),
        }),
        ("Шаблон", {
            "fields": ("is_preset", "preset_name"),
            "classes": ("collapse",),
        }),
        ("Други", {
            "fields": ("notes", "tags"),
        }),
    )

@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ("name", "role", "is_active", "is_default_supervisor", "is_default_executor")
    list_filter = ("is_active",)
    search_fields = ("name", "role")

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "eik", "is_default", "is_active")
    list_filter = ("is_active", "is_default")
    search_fields = ("name", "eik")