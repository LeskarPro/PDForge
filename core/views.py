from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Prefetch, Max
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.template.loader import render_to_string
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.clickjacking import xframe_options_exempt
from functools import lru_cache
from types import SimpleNamespace
from weasyprint import HTML
import base64
import json
import os
import uuid as uuid_mod
from datetime import datetime
from pathlib import Path

from core import sync_service

from django.db.models import Prefetch, Max, Count, Q

from core.models import (
    Protocol, ProtocolColumn, ProtocolProduct, TemplateFolder,
    Client, Site, SiteContact, Tag,
    OneTimeTreatment, OneTimeTreatmentProduct,
    Product, Pest, NonChemicalMean, Worker, Company,
    AppSettings,
)
from core.forms import (
    ClientForm, SiteForm, SiteFormFull, SiteContactForm, TagForm,
    OneTimeTreatmentForm, ProductForm, CompanyForm, WorkerForm,
    PestForm, NonChemicalMeanForm,
)

# ─────────────────────────────────────────────────────────────────────────────
# Shared querysets
# ─────────────────────────────────────────────────────────────────────────────

def _clients_qs():
    active_contacts = SiteContact.objects.order_by('order', 'created_at')
    active_sites = (
        Site.objects
        .filter(deleted_at__isnull=True)
        .prefetch_related('tags', Prefetch('contacts', queryset=active_contacts))
        .order_by('name')
    )
    return (
        Client.objects
        .filter(deleted_at__isnull=True)
        .prefetch_related(Prefetch('sites', queryset=active_sites))
        .order_by('firm', 'name')
    )


def _sites_qs(client):
    active_contacts = SiteContact.objects.order_by('order', 'created_at')
    return (
        client.sites
        .filter(deleted_at__isnull=True)
        .prefetch_related('tags', Prefetch('contacts', queryset=active_contacts))
        .order_by('name')
    )


def _all_sites_qs():
    """Used by the standalone Обекти list page."""
    active_contacts = SiteContact.objects.order_by('order', 'created_at')
    return (
        Site.objects
        .filter(deleted_at__isnull=True)
        .select_related('client')
        .prefetch_related('tags', Prefetch('contacts', queryset=active_contacts))
        .order_by('client__firm', 'name')
    )


# ─────────────────────────────────────────────────────────────────────────────
# Existing unchanged views
# ─────────────────────────────────────────────────────────────────────────────

def dashboard(request):
    return render(request, "dashboard.html", {"active_nav": "dashboard"})


def _protocol_list_qs(request):
    """Return a filtered Protocol queryset based on GET params."""
    qs = (
        Protocol.objects
        .filter(is_preset=False, deleted_at__isnull=True)
        .select_related('client', 'site', 'executed_by')
        .prefetch_related('tags', 'columns__pests')
        .order_by('-date', '-created_at')
    )
    q = (request.GET.get('q') or '').strip()
    if q:
        # SQLite's default icontains only case-folds ASCII, so Cyrillic
        # searches are case-sensitive without the ICU extension. Do the
        # match in Python with .casefold() instead — dataset is small.
        qf = q.casefold()
        search_fields = (
            'pseudonym', 'client__firm', 'client__eik',
            'site__name', 'site__address', 'snapshot_company_name',
        )
        rows = qs.values('pk', *search_fields)
        matching_pks = [
            row['pk'] for row in rows
            if qf in ' '.join(str(row.get(f) or '') for f in search_fields).casefold()
        ]
        qs = qs.filter(pk__in=matching_pks)

    pest_ids = request.GET.getlist('pests')
    if pest_ids:
        qs = qs.filter(columns__pests__pk__in=pest_ids).distinct()

    tag_ids = request.GET.getlist('tags')
    if tag_ids:
        qs = qs.filter(tags__pk__in=tag_ids).distinct()

    return qs


def protocol_list(request):
    qs = _protocol_list_qs(request)
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    all_pests = list(Pest.objects.filter(deleted_at__isnull=True).order_by('category', 'name')
                     .values('id', 'name', 'category'))
    all_tags  = list(Tag.objects.filter(deleted_at__isnull=True).order_by('order', 'name')
                     .values('id', 'name', 'color'))

    return render(request, 'protocols/list.html', {
        'active_nav': 'protokoli',
        'page_obj':   page_obj,
        'all_pests':  all_pests,
        'all_tags':   all_tags,
        'active_q':      request.GET.get('q', ''),
        'active_pests':  request.GET.getlist('pests'),
        'active_tags':   request.GET.getlist('tags'),
    })


def protocol_list_body(request):
    """HTMX partial — returns only the protocol cards + pagination."""
    qs = _protocol_list_qs(request)
    paginator = Paginator(qs, 25)
    page_obj  = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'protocols/_list_body.html', {
        'page_obj': page_obj,
        'request':  request,
    })


def template_list(request, folder_id=None):
    current_folder = None
    if folder_id:
        current_folder = get_object_or_404(TemplateFolder, pk=folder_id)

    q = (request.GET.get('q') or '').strip()
    search_results = None
    subfolders = TemplateFolder.objects.none()
    templates_qs = Protocol.objects.none()

    if q:
        # Global search across the entire template library — folders are
        # not shown, only matching protocol templates with their location.
        # SQLite's icontains doesn't case-fold Cyrillic, so match in Python.
        qf = q.casefold()
        base_qs = (
            Protocol.objects
            .filter(is_preset=True, deleted_at__isnull=True)
            .select_related('client', 'site', 'folder')
            .prefetch_related('tags', 'columns__pests')
        )
        search_fields = (
            'pseudonym', 'preset_name', 'client__firm', 'client__name',
            'site__name', 'site__pseudonym', 'site__address',
        )
        rows = base_qs.values('pk', *search_fields)
        matching_pks = [
            row['pk'] for row in rows
            if qf in ' '.join(str(row.get(f) or '') for f in search_fields).casefold()
        ]
        search_results = list(
            base_qs.filter(pk__in=matching_pks).order_by('pseudonym', 'preset_name')
        )
        for tpl in search_results:
            tpl.folder_path = tpl.folder.get_breadcrumb() if tpl.folder else []
    else:
        subfolders = TemplateFolder.objects.filter(parent=current_folder).order_by('name')
        templates_qs = (
            Protocol.objects
            .filter(is_preset=True, folder=current_folder, deleted_at__isnull=True)
            .select_related('client', 'site')
            .prefetch_related('tags', 'columns__pests')
            .order_by('pseudonym', 'preset_name', '-created_at')
        )

    breadcrumb = current_folder.get_breadcrumb() if current_folder else []
    context = {
        'active_nav': 'shabloni',
        'current_folder': current_folder,
        'breadcrumb': breadcrumb,
        'subfolders': subfolders,
        'templates': templates_qs,
        'search_query': q,
        'search_results': search_results,
    }
    if request.headers.get('HX-Request'):
        return render(request, 'template_folders/_tpl_content.html', context)
    return render(request, 'template_folders/list.html', context)


@lru_cache(maxsize=8)
def _logo_data_uri(logo_path: str) -> str:
    from pathlib import Path
    if not logo_path:
        return ""
    p = Path(logo_path)
    if not p.exists():
        return ""
    encoded = base64.b64encode(p.read_bytes()).decode("ascii")
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{encoded}"


def _render_protocol_pdf_bytes(protocol, base_url):
    logo_path = ""
    if protocol.company_id and protocol.company.logo:
        logo_path = protocol.company.logo.path
    html = render_to_string(
        "protocol/protocol.html",
        {"protocol": protocol, "logo_data_uri": _logo_data_uri(logo_path)},
    )
    return HTML(string=html, base_url=base_url).write_pdf()


def protocol_pdf(request, pk):
    protocol = get_object_or_404(Protocol, pk=pk)
    pdf_bytes = _render_protocol_pdf_bytes(protocol, request.build_absolute_uri("/"))
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="protocol-{protocol.pk}.pdf"'
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Client views
# ─────────────────────────────────────────────────────────────────────────────

def client_list(request):
    return render(request, 'clients/list.html', {
        'active_nav': 'klienti',
        'clients': _clients_qs(),
    })


def client_create(request):
    """Create a client.

    Stage 2b adds a `?as=json` (or POST field `as=json`) mode used by the
    protocol editor's "+ Нов клиент" modal:
      * success → 200 JSON with the new client's fields (no HTML render).
      * validation failure → 422 JSON with form errors.
    Existing HTMX behaviour is preserved when `as` is absent.
    """
    as_json = request.GET.get('as') == 'json' or request.POST.get('as') == 'json'
    if request.method == 'POST':
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save()
            if as_json:
                return JsonResponse({
                    'ok': True,
                    'client': {
                        'id': str(client.pk),
                        'firm': client.firm,
                        'name': client.name,
                        'eik': client.eik,
                        'address': client.address,
                        'phone': client.phone,
                    },
                })
            response = render(request, 'clients/_list_body.html',
                              {'clients': _clients_qs()})
            response['HX-Retarget'] = '#client-list'
            response['HX-Reswap']   = 'innerHTML'
            response['HX-Trigger']  = 'closeModal'
            return response
        if as_json:
            return JsonResponse({'ok': False, 'errors': form.errors}, status=422)
        return render(request, 'clients/_client_form.html',
                      {'form': form, 'mode': 'create'})
    return render(request, 'clients/_client_form.html',
                  {'form': ClientForm(), 'mode': 'create'})


def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk, deleted_at__isnull=True)
    if request.method == 'POST':
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            form.save()
            response = render(request, 'clients/_list_body.html',
                              {'clients': _clients_qs()})
            response['HX-Retarget'] = '#client-list'
            response['HX-Reswap']   = 'innerHTML'
            response['HX-Trigger']  = 'closeModal'
            return response
        return render(request, 'clients/_client_form.html',
                      {'form': form, 'mode': 'edit', 'client': client})
    return render(request, 'clients/_client_form.html',
                  {'form': ClientForm(instance=client), 'mode': 'edit', 'client': client})


@require_http_methods(["DELETE"])
def client_delete(request, pk):
    client = get_object_or_404(Client, pk=pk, deleted_at__isnull=True)
    client.deleted_at = timezone.now()
    client.save()
    return HttpResponse('')


# ─────────────────────────────────────────────────────────────────────────────
# Site views
# ─────────────────────────────────────────────────────────────────────────────

def sites_section(request, pk):
    """HTMX partial: re-render a client's sites section after contacts change."""
    client = get_object_or_404(Client, pk=pk, deleted_at__isnull=True)
    return render(request, 'clients/_sites_section.html', {
        'client': client,
        'sites': _sites_qs(client),
    })


def site_list(request):
    return render(request, 'sites/list.html', {
        'active_nav': 'obekti',
        'sites': _all_sites_qs(),
    })


def site_list_body(request):
    """HTMX partial: re-render the sites list (after contacts change on Обекти page)."""
    return render(request, 'sites/_list_body.html', {
        'sites': _all_sites_qs(),
    })


def site_create(request, client_pk):
    """Create a site from the Клиенти accordion (client is fixed)."""
    client = get_object_or_404(Client, pk=client_pk, deleted_at__isnull=True)
    if request.method == 'POST':
        form = SiteForm(request.POST)
        if form.is_valid():
            site = form.save(commit=False)
            site.client = client
            site.save()
            form.save_m2m()
            response = render(request, 'clients/_sites_section.html',
                              {'client': client, 'sites': _sites_qs(client)})
            response['HX-Retarget'] = f'#sites-section-{client.pk}'
            response['HX-Reswap']   = 'innerHTML'
            response['HX-Trigger']  = 'closeModal'
            return response
        return render(request, 'clients/_site_form.html',
                      {'form': form, 'client': client, 'mode': 'create', 'ctx': 'clients'})
    return render(request, 'clients/_site_form.html',
                  {'form': SiteForm(), 'client': client, 'mode': 'create', 'ctx': 'clients'})


def site_create_full(request):
    """Create a site from the Обекти page (client is chosen in the form).

    Stage 2b adds a `?as=json` (or POST field `as=json`) mode used by the
    protocol editor's "+ Нов обект" modal:
      * success → 200 JSON with the new site's fields.
      * validation failure → 422 JSON with form errors.
    Existing HTMX behaviour is preserved when `as` is absent.
    """
    as_json = request.GET.get('as') == 'json' or request.POST.get('as') == 'json'
    if request.method == 'POST':
        form = SiteFormFull(request.POST)
        if form.is_valid():
            site = form.save()
            if as_json:
                return JsonResponse({
                    'ok': True,
                    'site': {
                        'id': str(site.pk),
                        'client_id': str(site.client_id),
                        'pseudonym': site.pseudonym,
                        'name': site.name,
                        'address': site.address,
                        'area_m2': site.area_m2,
                    },
                })
            response = render(request, 'sites/_list_body.html',
                              {'sites': _all_sites_qs()})
            response['HX-Retarget'] = '#site-list'
            response['HX-Reswap']   = 'innerHTML'
            response['HX-Trigger']  = 'closeModal'
            return response
        if as_json:
            return JsonResponse({'ok': False, 'errors': form.errors}, status=422)
        return render(request, 'clients/_site_form.html',
                      {'form': form, 'mode': 'create', 'ctx': 'sites', 'show_client': True})
    return render(request, 'clients/_site_form.html',
                  {'form': SiteFormFull(), 'mode': 'create', 'ctx': 'sites', 'show_client': True})


def site_edit(request, pk):
    site = get_object_or_404(Site, pk=pk, deleted_at__isnull=True)
    client = site.client
    ctx = request.GET.get('ctx', 'clients')  # persisted via hidden field on POST

    if request.method == 'POST':
        ctx = request.POST.get('_ctx', 'clients')
        form = SiteForm(request.POST, instance=site)
        if form.is_valid():
            form.save()
            if ctx == 'sites':
                response = render(request, 'sites/_list_body.html',
                                  {'sites': _all_sites_qs()})
                response['HX-Retarget'] = '#site-list'
            else:
                response = render(request, 'clients/_sites_section.html',
                                  {'client': client, 'sites': _sites_qs(client)})
                response['HX-Retarget'] = f'#sites-section-{client.pk}'
            response['HX-Reswap']  = 'innerHTML'
            response['HX-Trigger'] = 'closeModal'
            return response
        return render(request, 'clients/_site_form.html',
                      {'form': form, 'site': site, 'client': client, 'mode': 'edit', 'ctx': ctx})
    return render(request, 'clients/_site_form.html',
                  {'form': SiteForm(instance=site), 'site': site,
                   'client': client, 'mode': 'edit', 'ctx': ctx})


@require_http_methods(["DELETE"])
def site_delete(request, pk):
    site = get_object_or_404(Site, pk=pk, deleted_at__isnull=True)
    client = site.client
    site.deleted_at = timezone.now()
    site.save()
    # HX-Target tells us which page triggered the delete
    hx_target = request.headers.get('HX-Target', '')
    if hx_target.startswith('site-row-'):
        return HttpResponse('')   # Обекти page: remove the <tr> via outerHTML swap
    return render(request, 'clients/_sites_section.html',
                  {'client': client, 'sites': _sites_qs(client)})


# ─────────────────────────────────────────────────────────────────────────────
# Site contact views
# ─────────────────────────────────────────────────────────────────────────────

def site_contacts(request, site_pk):
    site = get_object_or_404(Site, pk=site_pk, deleted_at__isnull=True)
    return render(request, 'clients/_contacts_modal.html', {
        'site': site,
        'contacts': site.contacts.order_by('order', 'created_at'),
        'form': SiteContactForm(),
    })


def site_contact_create(request, site_pk):
    site = get_object_or_404(Site, pk=site_pk, deleted_at__isnull=True)
    if request.method == 'POST':
        form = SiteContactForm(request.POST)
        if form.is_valid():
            contact = form.save(commit=False)
            contact.site = site
            max_order = site.contacts.aggregate(m=Max('order'))['m']
            contact.order = (max_order or 0) + 1
            contact.save()
            return render(request, 'clients/_contacts_list.html', {
                'site': site,
                'contacts': site.contacts.order_by('order', 'created_at'),
            })
        return render(request, 'clients/_contacts_modal.html', {
            'site': site,
            'contacts': site.contacts.order_by('order', 'created_at'),
            'form': form,
        })
    return render(request, 'clients/_contacts_modal.html', {
        'site': site,
        'contacts': site.contacts.order_by('order', 'created_at'),
        'form': SiteContactForm(),
    })


@require_http_methods(["DELETE"])
def site_contact_delete(request, pk):
    contact = get_object_or_404(SiteContact, pk=pk)
    site = contact.site
    contact.delete()
    return render(request, 'clients/_contacts_list.html', {
        'site': site,
        'contacts': site.contacts.order_by('order', 'created_at'),
    })


@require_http_methods(["POST"])
def site_contact_move(request, pk, direction):
    contact = get_object_or_404(SiteContact, pk=pk)
    site = contact.site
    contacts = list(site.contacts.order_by('order', 'created_at'))
    for i, c in enumerate(contacts):
        c.order = i
    SiteContact.objects.bulk_update(contacts, ['order'])
    idx = next((i for i, c in enumerate(contacts) if c.pk == contact.pk), None)
    if idx is not None:
        if direction == 'up' and idx > 0:
            contacts[idx].order, contacts[idx - 1].order = (
                contacts[idx - 1].order, contacts[idx].order)
            contacts[idx].save()
            contacts[idx - 1].save()
        elif direction == 'down' and idx < len(contacts) - 1:
            contacts[idx].order, contacts[idx + 1].order = (
                contacts[idx + 1].order, contacts[idx].order)
            contacts[idx].save()
            contacts[idx + 1].save()
    return render(request, 'clients/_contacts_list.html', {
        'site': site,
        'contacts': site.contacts.order_by('order', 'created_at'),
    })

# ─────────────────────────────────────────────────────────────────────────────
# Tag (Етикети) views
# ─────────────────────────────────────────────────────────────────────────────

def _tags_qs():
    return Tag.objects.filter(deleted_at__isnull=True).order_by('order', 'name')


def tag_list(request):
    return render(request, 'tags/list.html', {
        'active_nav': 'etiketi',
        'tags': _tags_qs(),
    })


def tag_create(request):
    if request.method == 'POST':
        form = TagForm(request.POST)
        if form.is_valid():
            max_order = Tag.objects.filter(deleted_at__isnull=True).aggregate(
                m=Max('order'))['m']
            tag = form.save(commit=False)
            tag.order = (max_order or 0) + 1
            tag.save()
            response = render(request, 'tags/_list_body.html', {'tags': _tags_qs()})
            response['HX-Retarget'] = '#tag-list'
            response['HX-Reswap'] = 'innerHTML'
            response['HX-Trigger'] = 'closeModal'
            return response
        return render(request, 'tags/_tag_form.html', {'form': form, 'mode': 'create'})
    return render(request, 'tags/_tag_form.html', {'form': TagForm(), 'mode': 'create'})


def tag_edit(request, pk):
    tag = get_object_or_404(Tag, pk=pk, deleted_at__isnull=True)
    if request.method == 'POST':
        form = TagForm(request.POST, instance=tag)
        if form.is_valid():
            form.save()
            response = render(request, 'tags/_list_body.html', {'tags': _tags_qs()})
            response['HX-Retarget'] = '#tag-list'
            response['HX-Reswap'] = 'innerHTML'
            response['HX-Trigger'] = 'closeModal'
            return response
        return render(request, 'tags/_tag_form.html',
                      {'form': form, 'mode': 'edit', 'tag': tag})
    return render(request, 'tags/_tag_form.html',
                  {'form': TagForm(instance=tag), 'mode': 'edit', 'tag': tag})


def tag_delete_confirm(request, pk):
    tag = get_object_or_404(Tag, pk=pk, deleted_at__isnull=True)
    return render(request, 'tags/_tag_confirm_delete.html', {'tag': tag})


@require_http_methods(["DELETE"])
def tag_delete(request, pk):
    tag = get_object_or_404(Tag, pk=pk, deleted_at__isnull=True)
    tag.deleted_at = timezone.now()
    tag.save()
    response = render(request, 'tags/_list_body.html', {'tags': _tags_qs()})
    response['HX-Trigger'] = 'closeModal'
    return response


@require_http_methods(["POST"])
def tag_reorder(request):
    order_str = request.POST.get('order', '')
    ids = [i.strip() for i in order_str.split(',') if i.strip()]
    for i, tag_id in enumerate(ids):
        Tag.objects.filter(pk=tag_id, deleted_at__isnull=True).update(order=i)
    return HttpResponse(status=204)

# ─────────────────────────────────────────────────────────────────────────────
# Еднократни обработки
# ─────────────────────────────────────────────────────────────────────────────

def _one_time_qs():
    return (
        OneTimeTreatment.objects
        .filter(deleted_at__isnull=True)
        .prefetch_related('pests', 'executed_by', 'tags', 'products__product')
        .order_by('-date', '-created_at')
    )


def _save_treatment_products(request, treatment):
    treatment.products.all().delete()
    product_ids    = request.POST.getlist('product_id')
    concentrations = request.POST.getlist('concentration')
    quantities     = request.POST.getlist('quantity_text')
    for i, pid in enumerate(product_ids):
        if not pid:
            continue
        try:
            product = Product.objects.get(pk=pid)
        except Product.DoesNotExist:
            continue
        OneTimeTreatmentProduct.objects.create(
            treatment=treatment,
            product=product,
            quantity_text=quantities[i]     if i < len(quantities)     else '',
            concentration=concentrations[i] if i < len(concentrations) else '',
            order=i,
        )


def one_time_list(request):
    q = request.GET.get('q', '').strip()
    pest_ids = request.GET.getlist('pests')
    tag_ids  = request.GET.getlist('tags')

    qs = _one_time_qs()
    if q:
        qs = qs.filter(
            Q(pseudonym__icontains=q) |
            Q(address__icontains=q) |
            Q(contact_name__icontains=q)
        )
    if pest_ids:
        qs = qs.filter(pests__pk__in=pest_ids).distinct()
    if tag_ids:
        qs = qs.filter(tags__pk__in=tag_ids).distinct()

    all_pests = list(Pest.objects.filter(deleted_at__isnull=True).order_by('category', 'name')
                     .values('id', 'name', 'category'))
    all_tags  = list(Tag.objects.filter(deleted_at__isnull=True).order_by('order', 'name')
                     .values('id', 'name', 'color'))

    ctx = {
        'treatments':    qs,
        'q':             q,
        'active_pests':  pest_ids,
        'active_tags':   tag_ids,
        'all_pests':     all_pests,
        'all_tags':      all_tags,
        'active_nav':    'ednokratni',
    }
    if request.headers.get('HX-Request'):
        return render(request, 'one_time/_list_body.html', ctx)
    return render(request, 'one_time/list.html', ctx)


def one_time_create(request):
    if request.method == 'POST':
        form = OneTimeTreatmentForm(request.POST)
        if form.is_valid():
            treatment = form.save()
            _save_treatment_products(request, treatment)
            response = render(request, 'one_time/_list_body.html',
                              {'treatments': _one_time_qs()})
            response['HX-Retarget'] = '#treatment-list'
            response['HX-Reswap']   = 'innerHTML'
            response['HX-Trigger']  = 'closeModal'
            return response
        # form invalid — re-render form with errors
        return render(request, 'one_time/_form.html', _form_ctx(request, form, 'create'))

    form = OneTimeTreatmentForm()
    return render(request, 'one_time/_form.html', _form_ctx(request, form, 'create'))


def one_time_edit(request, pk):
    treatment = get_object_or_404(OneTimeTreatment, pk=pk, deleted_at__isnull=True)
    if request.method == 'POST':
        form = OneTimeTreatmentForm(request.POST, instance=treatment)
        if form.is_valid():
            treatment = form.save()
            _save_treatment_products(request, treatment)
            response = render(request, 'one_time/_list_body.html',
                              {'treatments': _one_time_qs()})
            response['HX-Retarget'] = '#treatment-list'
            response['HX-Reswap']   = 'innerHTML'
            response['HX-Trigger']  = 'closeModal'
            return response
        return render(request, 'one_time/_form.html', _form_ctx(request, form, 'edit', treatment))

    form = OneTimeTreatmentForm(instance=treatment)
    return render(request, 'one_time/_form.html',
                  _form_ctx(request, form, 'edit', treatment))


def one_time_delete_confirm(request, pk):
    treatment = get_object_or_404(OneTimeTreatment, pk=pk, deleted_at__isnull=True)
    return render(request, 'one_time/_confirm_delete.html', {'treatment': treatment})


@require_http_methods(["DELETE"])
def one_time_delete(request, pk):
    treatment = get_object_or_404(OneTimeTreatment, pk=pk, deleted_at__isnull=True)
    treatment.deleted_at = timezone.now()
    treatment.save()
    response = render(request, 'one_time/_list_body.html',
                      {'treatments': _one_time_qs()})
    response['HX-Retarget'] = '#treatment-list'
    response['HX-Reswap']   = 'innerHTML'
    response['HX-Trigger']  = 'closeModal'
    return response


def _form_ctx(request, form, mode, treatment=None):
    existing_products = []
    if form.is_bound:
        selected_pest_ids   = set(form.data.getlist('pests'))
        selected_worker_ids = set(form.data.getlist('executed_by'))
        selected_tag_ids    = set(form.data.getlist('tags'))
    elif treatment and treatment.pk:
        selected_pest_ids   = set(str(pk) for pk in treatment.pests.values_list('id', flat=True))
        selected_worker_ids = set(str(pk) for pk in treatment.executed_by.values_list('id', flat=True))
        selected_tag_ids    = set(str(pk) for pk in treatment.tags.values_list('id', flat=True))
        existing_products   = list(treatment.products.select_related('product').order_by('order'))
    else:
        selected_pest_ids   = set()
        selected_worker_ids = set()
        selected_tag_ids    = set()
    return {
        'form':               form,
        'mode':               mode,
        'treatment':          treatment,
        'all_products':       Product.objects.filter(deleted_at__isnull=True).order_by('category', 'name'),
        'existing_products':  existing_products,
        'selected_pest_ids':  selected_pest_ids,
        'selected_worker_ids': selected_worker_ids,
        'selected_tag_ids':   selected_tag_ids,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2b — Protocol editor
#
# The editor is a single Alpine.js-driven page (templates/protocols/editor.html)
# bootstrapped with one JSON blob built by _build_editor_bootstrap().  Every
# action (Save / Print / Download / Save-as-template) POSTs the full editor
# payload to protocol_save_action and is handled by _save_or_rewrite_protocol —
# idempotent via the client-generated UUID.
# ─────────────────────────────────────────────────────────────────────────────

_SERVICES = ("disinsection", "deratization", "disinfection")


def _build_editor_bootstrap():
    """Build the JSON blob the editor's Alpine instance reads on init.

    Single-user app, data volume is tiny — we just dump every relevant catalog
    upfront instead of paginating / lazy-loading.
    """
    companies = list(
        Company.objects
        .filter(is_active=True, deleted_at__isnull=True)
        .order_by('-is_default', 'name')
        .values('id', 'name', 'eik', 'address', 'phone', 'slogan', 'is_default')
    )
    clients = list(
        Client.objects
        .filter(deleted_at__isnull=True)
        .order_by('firm', 'name')
        .values('id', 'firm', 'name', 'eik', 'address', 'phone')
    )
    sites = list(
        Site.objects
        .filter(deleted_at__isnull=True)
        .order_by('client__firm', 'name')
        .values('id', 'client_id', 'pseudonym', 'name', 'address', 'area_m2')
    )

    products = {svc: [] for svc in _SERVICES}
    for p in Product.objects.filter(deleted_at__isnull=True).order_by('category', 'name'):
        if p.category in products:
            products[p.category].append({
                'id': str(p.pk),
                'name': p.name,
                'authorization_no':     p.authorization_no,
                'formulation':          p.formulation,
                'active_substances':    p.active_substances,
                'working_solution':     p.working_solution,
                'action_time':          p.action_time,
                'antidote':             p.antidote,
                'safety_instructions':  p.safety_instructions,
                'access_info':          p.access_info,
                'surfaces_to_wipe':     p.surfaces_to_wipe,
                'bait_descriptor':      p.bait_descriptor,
            })

    pests = {svc: [] for svc in _SERVICES}
    for pest in Pest.objects.filter(deleted_at__isnull=True).order_by('category', 'created_at'):
        if pest.category in pests:
            pests[pest.category].append({'id': str(pest.pk), 'name': pest.name})

    ncm = {svc: [] for svc in _SERVICES}
    for m in NonChemicalMean.objects.filter(deleted_at__isnull=True).order_by('category', 'name'):
        if m.category in ncm:
            ncm[m.category].append({'id': str(m.pk), 'name': m.name})

    workers = list(
        Worker.objects
        .filter(is_active=True, deleted_at__isnull=True)
        .order_by('name')
        .values('id', 'name', 'is_default_supervisor', 'is_default_executor')
    )

    folders = list(
        TemplateFolder.objects
        .filter(deleted_at__isnull=True)
        .order_by('parent_id', 'name')
        .values('id', 'name', 'parent_id')
    )

    tags = list(
        Tag.objects
        .filter(deleted_at__isnull=True)
        .order_by('order', 'name')
        .values('id', 'name', 'color')
    )

    methods = [
        {'value': v, 'label': l}
        for v, l in ProtocolColumn.TreatmentMethod.choices
    ]

    default_company  = next((c['id'] for c in companies if c['is_default']), None)
    default_prepared = next((w['id'] for w in workers if w['is_default_supervisor']), None)
    default_executed = next((w['id'] for w in workers if w['is_default_executor']), None)

    return {
        'companies':         _stringify_uuids(companies),
        'clients':           _stringify_uuids(clients),
        'sites':             _stringify_uuids(sites),
        'products':          products,
        'pests':             pests,
        'non_chem_means':    ncm,
        'workers':           _stringify_uuids(workers),
        'treatment_methods': methods,
        'folders':           _stringify_uuids(folders),
        'tags':              _stringify_uuids(tags),
        'defaults': {
            'company_id':     str(default_company) if default_company else None,
            'prepared_by_id': str(default_prepared) if default_prepared else None,
            'executed_by_id': str(default_executed) if default_executed else None,
            'prepared_date':  timezone.localdate().isoformat(),
        },
        'prefill': None,  # populated by _build_prefill_from_protocol() for edit/copy flows
    }


def _build_prefill_from_protocol(protocol, *, include_pk=True):
    """Serialise an existing Protocol into the same shape as the editor's
    draft / save-payload so _applyDraft() can hydrate the form fields."""
    svc_map = {
        'disinsection': 'dis',
        'deratization': 'der',
        'disinfection':  'dinf',
    }
    columns = {}
    for col in protocol.columns.select_related().prefetch_related(
        'pests', 'non_chemical_means',
        'protocol_products__product',
    ):
        products_data = []
        for pp in col.protocol_products.all().order_by('order'):
            if pp.product_id:
                products_data.append({'id': str(pp.product_id)})
        columns[col.service] = {
            'is_active':          col.is_active,
            'pest_ids':           [str(p.pk) for p in col.pests.all()],
            'pests_other':        col.pests_other or '',
            'treated_area_m2':    str(col.treated_area_m2) if col.treated_area_m2 else '',
            'surface_description': col.surface_description or '',
            'treatment_methods':  list(col.treatment_methods or []),
            'ncm_ids':            [str(m.pk) for m in col.non_chemical_means.all()],
            'total_used':         col.total_used or '',
            'safety_other':       col.safety_other or '',
            'recommendations':    col.recommendations or '',
            'corrections':        col.corrections or '',
            'products':           products_data,
        }

    prefill = {
        'company_id':           str(protocol.company_id) if protocol.company_id else None,
        'client_id':            str(protocol.client_id)  if protocol.client_id  else None,
        'site_id':              str(protocol.site_id)    if protocol.site_id    else None,
        'prepared_by_id':       str(protocol.prepared_by_id) if protocol.prepared_by_id else None,
        'executed_by_id':       str(protocol.executed_by_id) if protocol.executed_by_id else None,
        'date':                 protocol.date.isoformat() if protocol.date else '',
        'prepared_date':        protocol.prepared_date.isoformat() if protocol.prepared_date else '',
        'time_from':            str(protocol.time_from)  if protocol.time_from  else '',
        'time_to':              str(protocol.time_to)    if protocol.time_to    else '',
        'client_signatory':     protocol.client_signatory or '',
        'is_long_term_contract': protocol.is_long_term_contract,
        'pseudonym':            protocol.pseudonym or '',
        'notes':                protocol.notes or '',
        'price':                str(protocol.price) if protocol.price else '',
        'tag_ids':              [str(t.pk) for t in protocol.tags.all()],
        'source_template_id':  str(protocol.source_template_id) if protocol.source_template_id else None,
        'columns':              columns,
    }
    if include_pk:
        prefill['client_uuid'] = str(protocol.pk)
    return prefill


def _stringify_uuids(rows):
    """JSON-safe: UUIDs → strings, dates → iso strings."""
    out = []
    for r in rows:
        d = {}
        for k, v in r.items():
            if isinstance(v, uuid_mod.UUID):
                d[k] = str(v)
            else:
                d[k] = v
        out.append(d)
    return out


def _parse_payload(request):
    """Read the JSON body of an editor POST. Returns ({}, error_response) tuple."""
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (ValueError, UnicodeDecodeError):
        return None, JsonResponse({'ok': False, 'error': 'invalid_json'}, status=400)
    return payload, None


def _safe_uuid(value):
    """Return UUID(value) or None — never raise."""
    if not value:
        return None
    try:
        return uuid_mod.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _safe_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _safe_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%H:%M').time()
    except (ValueError, TypeError):
        return None


def _safe_decimal(value):
    """Parse a price-like value into Decimal, or return None if blank/invalid."""
    if value in (None, '', 0):
        return None if value in (None, '') else 0
    try:
        from decimal import Decimal
        return Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        return None


@transaction.atomic
def _save_or_rewrite_protocol(payload, *, is_preset=False,
                              preset_name='', folder_id=None):
    """Idempotent persistence for the editor.

    `payload['client_uuid']` is generated by the editor on page load and used as
    the Protocol PK.  Subsequent saves with the same UUID rewrite the existing
    record in place — no duplicates.  Returns (protocol, created).
    """
    client_uuid = _safe_uuid(payload.get('client_uuid')) or uuid_mod.uuid4()

    client_id  = _safe_uuid(payload.get('client_id'))
    site_id    = _safe_uuid(payload.get('site_id'))
    company_id = _safe_uuid(payload.get('company_id'))
    if not (client_id and site_id):
        # Client + site are required for any save.
        raise ValueError('client_id and site_id are required')

    defaults = {
        'client_id':  client_id,
        'site_id':    site_id,
        'company_id': company_id,
        'date':       _safe_date(payload.get('date')),
        'prepared_date': _safe_date(payload.get('prepared_date')),
        'time_from':  _safe_time(payload.get('time_from')),
        'time_to':    _safe_time(payload.get('time_to')),
        'is_long_term_contract': bool(payload.get('is_long_term_contract', False)),
        'prepared_by_id':  _safe_uuid(payload.get('prepared_by_id')),
        'executed_by_id':  _safe_uuid(payload.get('executed_by_id')),
        'client_signatory': (payload.get('client_signatory') or '')[:255],
        'pseudonym':       (payload.get('pseudonym') or '')[:255],
        'notes':           payload.get('notes') or '',
        'price':           _safe_decimal(payload.get('price')),
        'is_preset':       bool(is_preset),
        'preset_name':     (preset_name or '')[:255],
        'folder_id':       _safe_uuid(folder_id),
        'source_template_id': _safe_uuid(payload.get('source_template_id')),
        # snapshot_* fields are recomputed by Protocol.save() when company is set.
        'snapshot_company_name':    '',
        'snapshot_company_eik':     '',
        'snapshot_company_address': '',
        'snapshot_company_phone':   '',
    }

    protocol, created = Protocol.objects.update_or_create(
        pk=client_uuid, defaults=defaults,
    )
    # Force a fresh company snapshot on every rewrite (in case company changed).
    protocol.refresh_company_snapshot()
    protocol.save()

    # Tags M2M
    tag_ids = [_safe_uuid(t) for t in (payload.get('tag_ids') or [])]
    protocol.tags.set([t for t in tag_ids if t])

    # Columns — Protocol.save() ensures the 3 rows exist; we update in place.
    columns_payload = payload.get('columns') or {}
    existing = {c.service: c for c in protocol.columns.all()}
    for svc in _SERVICES:
        col = existing.get(svc)
        if col is None:
            col = ProtocolColumn.objects.create(protocol=protocol, service=svc)
        col_data = columns_payload.get(svc) or {}

        col.is_active           = bool(col_data.get('is_active', False))
        col.pests_other         = (col_data.get('pests_other') or '')[:255]
        col.treated_area_m2     = col_data.get('treated_area_m2') or None
        col.surface_description = col_data.get('surface_description') or ''
        col.treatment_methods   = [
            m for m in (col_data.get('treatment_methods') or [])
            if m in dict(ProtocolColumn.TreatmentMethod.choices)
        ]
        col.total_used          = col_data.get('total_used') or ''
        col.safety_other        = col_data.get('safety_other') or ''
        col.recommendations     = col_data.get('recommendations') or ''
        col.corrections         = col_data.get('corrections') or ''
        col.save()

        # M2Ms
        pest_ids = [_safe_uuid(p) for p in (col_data.get('pest_ids') or [])]
        col.pests.set([p for p in pest_ids if p])
        ncm_ids = [_safe_uuid(m) for m in (col_data.get('ncm_ids') or [])]
        col.non_chemical_means.set([m for m in ncm_ids if m])

        # Products — snapshots are frozen at insert, so rewrite from scratch.
        col.protocol_products.all().delete()
        for i, prod in enumerate(col_data.get('products') or []):
            pid = _safe_uuid(prod.get('id'))
            if not pid:
                continue
            try:
                product = Product.objects.get(pk=pid)
            except Product.DoesNotExist:
                continue
            ProtocolProduct.objects.create(
                column=col, product=product, order=i,
            )

    return protocol, created


def _build_preview_protocol(payload):
    """Build a SimpleNamespace tree that quacks like a Protocol — used to
    render protocol/_protocol_front.html and _protocol_back.html for the
    preview page WITHOUT persisting anything to the database.

    The attribute shape must mirror what those partials read; the property
    names match Protocol / ProtocolColumn so the same templates work.
    """
    methods_map = dict(ProtocolColumn.TreatmentMethod.choices)

    # ── Header data ─────────────────────────────────────────────────────────
    company  = Company.objects.filter(pk=_safe_uuid(payload.get('company_id'))).first()
    client_o = Client .objects.filter(pk=_safe_uuid(payload.get('client_id'))).first()
    site_o   = Site   .objects.filter(pk=_safe_uuid(payload.get('site_id'))).first()
    prep_o   = Worker .objects.filter(pk=_safe_uuid(payload.get('prepared_by_id'))).first()
    exec_o   = Worker .objects.filter(pk=_safe_uuid(payload.get('executed_by_id'))).first()

    # ── Per-service columns ────────────────────────────────────────────────
    cols_payload = payload.get('columns') or {}
    columns = {}
    for svc in _SERVICES:
        c = cols_payload.get(svc) or {}
        pest_ids = [_safe_uuid(p) for p in (c.get('pest_ids') or [])]
        ncm_ids  = [_safe_uuid(m) for m in (c.get('ncm_ids')  or [])]

        pests_qs = list(Pest.objects.filter(pk__in=[p for p in pest_ids if p]))
        ncm_qs   = list(NonChemicalMean.objects.filter(pk__in=[m for m in ncm_ids if m]))

        prod_objs = []
        for i, prod in enumerate(c.get('products') or []):
            pid = _safe_uuid(prod.get('id'))
            p = Product.objects.filter(pk=pid).first() if pid else None
            if not p:
                continue
            prod_objs.append(SimpleNamespace(
                snapshot_name=p.name,
                snapshot_authorization_no=p.authorization_no,
                snapshot_formulation=p.formulation,
                snapshot_active_substances=p.active_substances,
                snapshot_working_solution=p.working_solution,
                snapshot_action_time=p.action_time,
                snapshot_antidote=p.antidote,
                snapshot_safety_instructions=p.safety_instructions,
                snapshot_access_info=p.access_info,
                snapshot_surfaces_to_wipe=p.surfaces_to_wipe,
                snapshot_bait_descriptor=p.bait_descriptor,
            ))

        all_pests_cat = list(Pest.objects.filter(category=svc).order_by('created_at'))
        sel_set = {p.id for p in pests_qs}
        with_status = [(pest, pest.id in sel_set) for pest in all_pests_cat]

        treatment_methods = c.get('treatment_methods') or []
        treatment_display = ', '.join(methods_map.get(m, m) for m in treatment_methods)

        columns[svc] = SimpleNamespace(
            service=svc,
            is_active=bool(c.get('is_active', False)),
            pests=SimpleNamespace(all=lambda qs=pests_qs: qs),
            pests_other=c.get('pests_other') or '',
            treated_area_m2=c.get('treated_area_m2'),
            surface_description=c.get('surface_description') or '',
            treatment_methods=treatment_methods,
            treatment_methods_display=treatment_display,
            non_chemical_means=SimpleNamespace(all=lambda qs=ncm_qs: qs),
            protocol_products=SimpleNamespace(all=lambda qs=prod_objs: qs),
            total_used=c.get('total_used') or '',
            safety_other=c.get('safety_other') or '',
            recommendations=c.get('recommendations') or '',
            corrections=c.get('corrections') or '',
            all_pests_with_status=with_status,
        )

    # ── Build pest_grid_rows the same way Protocol.pest_grid_rows does ─────
    def _pest_rows(cols_dict):
        def make_entries(code, with_other, lower):
            col = cols_dict[code]
            out = [
                {'sel': sel, 'name': pest.name.lower() if lower else pest.name}
                for pest, sel in col.all_pests_with_status
            ]
            if with_other:
                other = col.pests_other
                out.append({'sel': True, 'name': other} if other
                           else {'sel': False, 'name': 'други (опишете)'})
            return out

        dis  = make_entries('disinsection', with_other=True,  lower=True)
        der  = make_entries('deratization', with_other=True,  lower=False)
        dinf = make_entries('disinfection', with_other=False, lower=True)

        dis_normal, dis_other = dis[:-1], dis[-1]
        dis_rows = []
        for i in range(0, len(dis_normal), 2):
            right = dis_normal[i + 1] if i + 1 < len(dis_normal) else None
            dis_rows.append({'kind': 'pairs', 'left': dis_normal[i], 'right': right})
        dis_rows.append({'kind': 'other', 'entry': dis_other})

        dinf_rows = [{'kind': 'pest', 'entry': e} for e in dinf]

        der_normal, der_other = der[:-1], der[-1]
        n = max(len(dis_rows), len(der_normal) + 1, len(dinf_rows))

        der_rows = [{'kind': 'pest', 'entry': e} for e in der_normal]
        der_rows.append({'kind': 'other', 'entry': der_other,
                         'rowspan': n - len(der_normal)})
        der_rows += [{'kind': 'covered'}] * (n - len(der_rows))

        dis_rows  += [{'kind': 'empty'}] * (n - len(dis_rows))
        dinf_rows += [{'kind': 'empty'}] * (n - len(dinf_rows))

        return [
            {'dis': dis_rows[i], 'der': der_rows[i], 'dinf': dinf_rows[i]}
            for i in range(n)
        ]

    pest_grid_rows = _pest_rows(columns)

    # ── Row-11 / row-10 flags (same logic as Protocol model) ───────────────
    row11_show_total = columns['disinsection'].is_active or columns['disinfection'].is_active
    row11_show_baits = columns['deratization'].is_active

    def column_volume(code):
        return sum(len(pp.snapshot_working_solution or '')
                   for pp in columns[code].protocol_products.all())
    row10_on_back = max(column_volume(c) for c in _SERVICES) > 155

    # ── Deratization bait text (row 11b) ───────────────────────────────────
    descriptors = [
        pp.snapshot_bait_descriptor
        for pp in columns['deratization'].protocol_products.all()
        if pp.snapshot_bait_descriptor
    ]
    if not descriptors:
        bait_text = ''
    elif len(descriptors) == 1:
        bait_text = f"...бр. {descriptors[0]}"
    else:
        bait_text = "....бр. комбинирани примамки - " + " + ".join(descriptors)

    return SimpleNamespace(
        company=company or SimpleNamespace(slogan=''),
        snapshot_company_name=(company.name if company else ''),
        snapshot_company_eik=(company.eik if company else ''),
        snapshot_company_address=(company.address if company else ''),
        snapshot_company_phone=(company.phone if company else ''),
        client=client_o or SimpleNamespace(firm='', name='', eik='', address='', phone=''),
        site=site_o   or SimpleNamespace(name='', address='', area_m2=None),
        is_long_term_contract=bool(payload.get('is_long_term_contract', False)),
        prepared_by=prep_o or SimpleNamespace(name=''),
        executed_by=exec_o or SimpleNamespace(name=''),
        client_signatory=payload.get('client_signatory') or '',
        date=_safe_date(payload.get('date')),
        prepared_date=_safe_date(payload.get('prepared_date')),
        created_at=timezone.now(),
        columns_by_service=columns,
        pest_grid_rows=pest_grid_rows,
        row10_on_back=row10_on_back,
        row11_show_total=row11_show_total,
        row11_show_baits=row11_show_baits,
        deratization_bait_text=bait_text,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Editor page (GET)
# ─────────────────────────────────────────────────────────────────────────────

def protocol_create(request):
    """Render the new-protocol editor."""
    bootstrap = _build_editor_bootstrap()
    return render(request, 'protocols/editor.html', {
        'active_nav':     'protokoli',
        'editor_mode':    'create',
        'bootstrap_json': json.dumps(bootstrap, ensure_ascii=False, default=str),
    })


def protocol_edit_view(request, pk):
    """Load an existing protocol into the editor for in-place editing."""
    protocol = get_object_or_404(Protocol, pk=pk, deleted_at__isnull=True)
    bootstrap = _build_editor_bootstrap()
    bootstrap['prefill'] = _build_prefill_from_protocol(protocol, include_pk=True)
    return render(request, 'protocols/editor.html', {
        'active_nav':     'protokoli',
        'editor_mode':    'edit',
        'protocol_pk':    str(protocol.pk),
        'bootstrap_json': json.dumps(bootstrap, ensure_ascii=False, default=str),
    })


def protocol_create_from(request, pk):
    """Open the editor pre-filled from an existing protocol but save as a new record."""
    source = get_object_or_404(Protocol, pk=pk, deleted_at__isnull=True)
    bootstrap = _build_editor_bootstrap()
    prefill = _build_prefill_from_protocol(source, include_pk=False)
    # Use today's date for the new protocol
    prefill['date'] = timezone.localdate().isoformat()
    # Record provenance only when duplicating an actual template.
    prefill['source_template_id'] = str(source.pk) if source.is_preset else None
    bootstrap['prefill'] = prefill
    return render(request, 'protocols/editor.html', {
        'active_nav':     'protokoli',
        'editor_mode':    'create_from',
        'bootstrap_json': json.dumps(bootstrap, ensure_ascii=False, default=str),
    })


@xframe_options_exempt
def protocol_view(request, pk):
    """Read-only view of a saved protocol, rendered in the editor layout."""
    protocol = get_object_or_404(
        Protocol.objects.select_related('source_template'),
        pk=pk, deleted_at__isnull=True,
    )
    bootstrap = _build_editor_bootstrap()
    bootstrap['prefill'] = _build_prefill_from_protocol(protocol, include_pk=True)
    return render(request, 'protocols/editor.html', {
        'active_nav':     'protokoli',
        'editor_mode':    'view',
        'protocol_pk':    str(protocol.pk),
        'protocol':       protocol,
        'embed':          request.GET.get('embed') == '1',
        'bootstrap_json': json.dumps(bootstrap, ensure_ascii=False, default=str),
    })


@require_http_methods(['DELETE'])
def protocol_delete(request, pk):
    """Soft-delete a protocol and remove its card from the list."""
    protocol = get_object_or_404(Protocol, pk=pk, deleted_at__isnull=True)
    protocol.deleted_at = timezone.now()
    protocol.save(update_fields=['deleted_at'])
    return HttpResponse(status=200)


# ─────────────────────────────────────────────────────────────────────────────
# Preview page (POST from editor — does NOT save)
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
def protocol_preview(request):
    """POST from the editor → render preview page.

    Accepts either:
      • JSON body (legacy fetch-based path, kept as fallback), or
      • A form-POST with a single hidden field `payload` whose value is
        the JSON-encoded editor state.

    The form-POST path is the one the editor uses now, because it triggers
    a real browser navigation (Alpine cleanly re-initialises on the new
    page) instead of a half-broken document.write() swap.

    We DO NOT save here — save only happens when the user clicks one of
    the action buttons on the preview page.
    """
    if request.content_type == 'application/json':
        payload, err = _parse_payload(request)
        if err:
            return err
    else:
        # Form POST from the editor's hidden <form> — payload is a JSON string
        # in the 'payload' field.
        try:
            payload = json.loads(request.POST.get('payload', '') or '{}')
        except (ValueError, TypeError):
            return JsonResponse({'ok': False, 'error': 'invalid_payload'}, status=400)

    try:
        preview_protocol = _build_preview_protocol(payload)
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)

    # Echo payload back so the preview page can re-POST it on action.
    return render(request, 'protocols/preview.html', {
        'active_nav': 'protokoli',
        'preview_protocol': preview_protocol,
        'logo_data_uri': _logo_data_uri(
            preview_protocol.company.logo.path
            if getattr(preview_protocol.company, 'logo', None) else ''
        ),
        'payload_json': json.dumps(payload, ensure_ascii=False),
        # Folder tree for the "Save as template" picker
        'folders_json': json.dumps(
            list(TemplateFolder.objects
                 .filter(deleted_at__isnull=True)
                 .order_by('parent_id', 'name')
                 .values('id', 'name', 'parent_id')),
            ensure_ascii=False, default=str,
        ),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Save action (POST from preview — idempotent rewrite)
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
def protocol_save_action(request):
    """Single endpoint for Save / Print / Download / Save-as-template.

    Body: full editor JSON payload + `action` + `client_uuid`.
    Behaviour: idempotent rewrite via _save_or_rewrite_protocol.
    Returns: JSON with `protocol_id`, `created`, and an action-specific
    `redirect_url` the editor JS uses to navigate the browser.
    """
    payload, err = _parse_payload(request)
    if err:
        return err

    action = (payload.get('action') or 'save').lower()
    if action not in ('save', 'print', 'download', 'save_as_template'):
        return JsonResponse({'ok': False, 'error': 'unknown_action'}, status=400)

    is_preset = action == 'save_as_template'
    preset_name = (payload.get('preset_name') or '') if is_preset else ''
    folder_id   = payload.get('folder_id') if is_preset else None

    try:
        protocol, created = _save_or_rewrite_protocol(
            payload,
            is_preset=is_preset,
            preset_name=preset_name,
            folder_id=folder_id,
        )
    except ValueError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=422)
    except Exception as e:
        return JsonResponse({'ok': False, 'error': 'save_failed', 'detail': str(e)},
                            status=500)

    pid = str(protocol.pk)

    # save-as-template: redirect to the folder we actually saved into so the
    # user lands where the new template is visible — not on the root template
    # list (which only shows folder=None records).
    if action == 'save_as_template' and protocol.folder_id:
        template_redirect = reverse(
            'core:template_folder',
            kwargs={'folder_id': str(protocol.folder_id)},
        )
    else:
        template_redirect = reverse('core:template_list')

    redirect_map = {
        'save':              reverse('core:protocol_list'),
        'save_as_template':  template_redirect,
        'print':             reverse('core:protocol_print', kwargs={'pk': pid})
                             + '?fmt=' + (payload.get('format') or 'a5'),
        'download':          reverse('core:protocol_pdf',   kwargs={'pk': pid}),
    }
    return JsonResponse({
        'ok': True,
        'protocol_id': pid,
        'created':     created,
        'action':      action,
        'is_preset':   protocol.is_preset,
        'folder_id':   str(protocol.folder_id) if protocol.folder_id else None,
        'redirect_url': redirect_map[action],
    })


# ─────────────────────────────────────────────────────────────────────────────
# Print page — opens browser print dialog on load
# ─────────────────────────────────────────────────────────────────────────────

def protocol_print(request, pk):
    """Render the protocol HTML in the same template the PDF uses, plus a tiny
    `onload="window.print()"` shim that opens the browser print dialog.
    Returns user to the protocol list when the dialog closes.

    Critical: Cache-Control: no-store is set so Safari (and other browsers)
    don't re-use a stale copy of this page when the popup is reopened.
    """
    protocol = get_object_or_404(Protocol, pk=pk, deleted_at__isnull=True)
    logo_path = ''
    if protocol.company_id and protocol.company.logo:
        logo_path = protocol.company.logo.path
    response = render(request, 'protocols/print_render.html', {
        'protocol':      protocol,
        'logo_data_uri': _logo_data_uri(logo_path),
        'fmt':           request.GET.get('fmt', 'a5'),
        'return_url':    reverse('core:protocol_list'),
    })
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma']        = 'no-cache'
    response['Expires']       = '0'
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Print-format chooser for a saved protocol (view-mode popup → Печат)
# ─────────────────────────────────────────────────────────────────────────────

def protocol_print_choose(request, pk):
    """Minimal print-format chooser for an already-saved protocol.

    Shows the same paper preview as the editor's preview page, but with
    only a format switcher, a "Печат" button (→ protocol_print) and a
    "Назад" button back to the read-only view page.
    """
    protocol = get_object_or_404(Protocol, pk=pk, deleted_at__isnull=True)
    logo_path = ''
    if protocol.company_id and protocol.company.logo:
        logo_path = protocol.company.logo.path
    return render(request, 'protocols/print_choose.html', {
        'active_nav':    'protokoli',
        'protocol':      protocol,
        'logo_data_uri': _logo_data_uri(logo_path),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Save-as-template (copy) — from the view-mode popup of a saved protocol
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
def protocol_save_as_template(request, pk):
    """Save a copy of an existing (saved) protocol as a new template.

    The original protocol record is left untouched — a new is_preset=True
    record is created in the chosen folder, built from a fresh prefill
    (include_pk=False generates a new client_uuid → new row).
    """
    source = get_object_or_404(Protocol, pk=pk, deleted_at__isnull=True)

    payload, err = _parse_payload(request)
    if err:
        return err

    preset_name = (payload.get('preset_name') or '').strip()
    folder_id   = payload.get('folder_id')
    if not preset_name:
        return JsonResponse({'ok': False, 'error': 'preset_name_required'}, status=422)

    prefill = _build_prefill_from_protocol(source, include_pk=False)

    try:
        protocol, created = _save_or_rewrite_protocol(
            prefill,
            is_preset=True,
            preset_name=preset_name,
            folder_id=folder_id,
        )
    except ValueError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=422)
    except Exception as e:
        return JsonResponse({'ok': False, 'error': 'save_failed', 'detail': str(e)},
                            status=500)

    if protocol.folder_id:
        redirect_url = reverse('core:template_folder', kwargs={'folder_id': str(protocol.folder_id)})
    else:
        redirect_url = reverse('core:template_list')

    return JsonResponse({
        'ok': True,
        'protocol_id': str(protocol.pk),
        'redirect_url': redirect_url,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Препарати (Products) — Stage 3a
# ─────────────────────────────────────────────────────────────────────────────

def _products_qs():
    return Product.objects.filter(deleted_at__isnull=True).order_by('category', 'pseudonym', 'name')


def product_list(request):
    return render(request, 'products/list.html', {
        'active_nav': 'preparati',
        'products': _products_qs(),
    })


def product_list_body(request):
    return render(request, 'products/_list_body.html', {'products': _products_qs()})


def product_create(request):
    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            form.save()
            from django.http import HttpResponse as _HR
            r = _HR(status=204)
            r['HX-Trigger'] = 'productsChanged'
            return r
    else:
        form = ProductForm()
    return render(request, 'products/_form.html', {'form': form, 'product': None})


def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk, deleted_at__isnull=True)
    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            from django.http import HttpResponse as _HR
            r = _HR(status=204)
            r['HX-Trigger'] = 'productsChanged'
            return r
    else:
        form = ProductForm(instance=product)
    return render(request, 'products/_form.html', {'form': form, 'product': product})


@require_http_methods(['DELETE'])
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk, deleted_at__isnull=True)
    product.deleted_at = timezone.now()
    product.save(update_fields=['deleted_at'])
    return render(request, 'products/_list_body.html', {'products': _products_qs()})


# ─────────────────────────────────────────────────────────────────────────────
# Фирми (Companies) — Stage 3b
# ─────────────────────────────────────────────────────────────────────────────

def _companies_qs():
    return Company.objects.filter(is_active=True, deleted_at__isnull=True)


def company_list(request):
    return render(request, 'companies/list.html', {
        'active_nav': 'firmi',
        'companies': _companies_qs(),
    })


def company_cards(request):
    return render(request, 'companies/_cards.html', {'companies': _companies_qs()})


def company_create(request):
    if request.method == 'POST':
        form = CompanyForm(request.POST, request.FILES)
        if form.is_valid():
            company = form.save()
            # Place at end of order
            if company.order == 0:
                max_order = Company.objects.filter(
                    is_active=True, deleted_at__isnull=True
                ).exclude(pk=company.pk).count()
                company.order = max_order
                company.save(update_fields=['order'])
            from django.http import HttpResponse as _HR
            r = _HR(status=204)
            r['HX-Trigger'] = 'companiesChanged'
            return r
    else:
        form = CompanyForm()
    return render(request, 'companies/_form.html', {'form': form, 'company': None})


def company_edit(request, pk):
    company = get_object_or_404(Company, pk=pk, deleted_at__isnull=True)
    if request.method == 'POST':
        form = CompanyForm(request.POST, request.FILES, instance=company)
        if form.is_valid():
            obj = form.save(commit=False)
            # FileInput doesn't send the existing value — preserve logo if no new file
            if not request.FILES.get('logo'):
                obj.logo = company.logo
            obj.save()
            from django.http import HttpResponse as _HR
            r = _HR(status=204)
            r['HX-Trigger'] = 'companiesChanged'
            return r
    else:
        form = CompanyForm(instance=company)
    return render(request, 'companies/_form.html', {'form': form, 'company': company})


@require_POST
def company_set_default(request, pk):
    company = get_object_or_404(Company, pk=pk, deleted_at__isnull=True)
    company.is_default = True
    company.save()  # model.save() clears is_default on all others
    return render(request, 'companies/_cards.html', {'companies': _companies_qs()})


@require_POST
def company_reorder(request):
    order_ids = request.POST.getlist('order[]')
    for idx, raw_id in enumerate(order_ids):
        try:
            Company.objects.filter(pk=raw_id).update(order=idx)
        except Exception:
            pass
    from django.http import HttpResponse as _HR
    return _HR(status=204)


@require_http_methods(['DELETE'])
def company_delete(request, pk):
    company = get_object_or_404(Company, pk=pk, deleted_at__isnull=True)
    company.is_active = False
    company.deleted_at = timezone.now()
    company.save(update_fields=['is_active', 'deleted_at'])
    return render(request, 'companies/_cards.html', {'companies': _companies_qs()})


# ─────────────────────────────────────────────────────────────────────────────
# Работници (Workers) — Stage 3b
# ─────────────────────────────────────────────────────────────────────────────

def _workers_qs():
    return Worker.objects.filter(deleted_at__isnull=True).order_by('-is_active', 'name')


def worker_list(request):
    return render(request, 'workers/list.html', {
        'active_nav': 'rabotnici',
        'workers': _workers_qs(),
    })


def worker_list_body(request):
    return render(request, 'workers/_list_body.html', {'workers': _workers_qs()})


def worker_create(request):
    if request.method == 'POST':
        form = WorkerForm(request.POST)
        if form.is_valid():
            form.save()
            from django.http import HttpResponse as _HR
            r = _HR(status=204)
            r['HX-Trigger'] = 'workersChanged'
            return r
    else:
        form = WorkerForm()
    return render(request, 'workers/_form.html', {'form': form, 'worker': None})


def worker_edit(request, pk):
    worker = get_object_or_404(Worker, pk=pk, deleted_at__isnull=True)
    if request.method == 'POST':
        form = WorkerForm(request.POST, instance=worker)
        if form.is_valid():
            form.save()
            from django.http import HttpResponse as _HR
            r = _HR(status=204)
            r['HX-Trigger'] = 'workersChanged'
            return r
    else:
        form = WorkerForm(instance=worker)
    return render(request, 'workers/_form.html', {'form': form, 'worker': worker})


@require_http_methods(['DELETE'])
def worker_delete(request, pk):
    worker = get_object_or_404(Worker, pk=pk, deleted_at__isnull=True)
    worker.deleted_at = timezone.now()
    worker.save(update_fields=['deleted_at'])
    return render(request, 'workers/_list_body.html', {'workers': _workers_qs()})


# ─────────────────────────────────────────────────────────────────────────────
# Вредители (Pests) — Stage 3c
# ─────────────────────────────────────────────────────────────────────────────

def _pests_qs():
    return Pest.objects.filter(deleted_at__isnull=True).order_by('category', 'name')


def pest_list(request):
    return render(request, 'pests/list.html', {
        'active_nav': 'vrediteli',
        'pests': _pests_qs(),
    })


def pest_list_body(request):
    return render(request, 'pests/_list_body.html', {'pests': _pests_qs()})


def pest_create(request):
    if request.method == 'POST':
        form = PestForm(request.POST)
        if form.is_valid():
            form.save()
            from django.http import HttpResponse as _HR
            r = _HR(status=204)
            r['HX-Trigger'] = 'pestsChanged'
            return r
    else:
        form = PestForm()
    return render(request, 'pests/_form.html', {'form': form, 'pest': None})


def pest_edit(request, pk):
    pest = get_object_or_404(Pest, pk=pk, deleted_at__isnull=True)
    if request.method == 'POST':
        form = PestForm(request.POST, instance=pest)
        if form.is_valid():
            form.save()
            from django.http import HttpResponse as _HR
            r = _HR(status=204)
            r['HX-Trigger'] = 'pestsChanged'
            return r
    else:
        form = PestForm(instance=pest)
    return render(request, 'pests/_form.html', {'form': form, 'pest': pest})


@require_http_methods(['DELETE'])
def pest_delete(request, pk):
    pest = get_object_or_404(Pest, pk=pk, deleted_at__isnull=True)
    pest.deleted_at = timezone.now()
    pest.save(update_fields=['deleted_at'])
    return render(request, 'pests/_list_body.html', {'pests': _pests_qs()})


# ─────────────────────────────────────────────────────────────────────────────
# Нехимични средства (NonChemicalMeans) — Stage 3c
# ─────────────────────────────────────────────────────────────────────────────

def _nonchemical_qs():
    return NonChemicalMean.objects.filter(deleted_at__isnull=True).order_by('category', 'name')


def nonchemical_list(request):
    return render(request, 'nonchemical/list.html', {
        'active_nav': 'nehim',
        'means': _nonchemical_qs(),
    })


def nonchemical_list_body(request):
    return render(request, 'nonchemical/_list_body.html', {'means': _nonchemical_qs()})


def nonchemical_create(request):
    if request.method == 'POST':
        form = NonChemicalMeanForm(request.POST)
        if form.is_valid():
            form.save()
            from django.http import HttpResponse as _HR
            r = _HR(status=204)
            r['HX-Trigger'] = 'nonchemicalChanged'
            return r
    else:
        form = NonChemicalMeanForm()
    return render(request, 'nonchemical/_form.html', {'form': form, 'mean': None})


def nonchemical_edit(request, pk):
    mean = get_object_or_404(NonChemicalMean, pk=pk, deleted_at__isnull=True)
    if request.method == 'POST':
        form = NonChemicalMeanForm(request.POST, instance=mean)
        if form.is_valid():
            form.save()
            from django.http import HttpResponse as _HR
            r = _HR(status=204)
            r['HX-Trigger'] = 'nonchemicalChanged'
            return r
    else:
        form = NonChemicalMeanForm(instance=mean)
    return render(request, 'nonchemical/_form.html', {'form': form, 'mean': mean})


@require_http_methods(['DELETE'])
def nonchemical_delete(request, pk):
    mean = get_object_or_404(NonChemicalMean, pk=pk, deleted_at__isnull=True)
    mean.deleted_at = timezone.now()
    mean.save(update_fields=['deleted_at'])
    return render(request, 'nonchemical/_list_body.html', {'means': _nonchemical_qs()})


# ─────────────────────────────────────────────────────────────────────────────
# Настройки (Settings) — Stage 4
# ─────────────────────────────────────────────────────────────────────────────

def settings_view(request):
    settings = AppSettings.get()
    return render(request, 'settings/settings.html', {
        'active_nav': 'nastroiki',
        'settings': settings,
        'themes': AppSettings.Theme.choices,
        'formats': AppSettings.ProtocolFormat.choices,
    })


@require_POST
def settings_save(request):
    settings = AppSettings.get()
    theme  = request.POST.get('theme', settings.theme)
    fmt    = request.POST.get('default_protocol_format', settings.default_protocol_format)
    if theme in dict(AppSettings.Theme.choices):
        settings.theme = theme
    if fmt in dict(AppSettings.ProtocolFormat.choices):
        settings.default_protocol_format = fmt
    settings.save(update_fields=['theme', 'default_protocol_format'])
    from django.http import HttpResponse as _HR
    return _HR(status=204)


# ─────────────────────────────────────────────────────────────────────────────
# База данни — OneDrive/backup sync (Stage 6a/6b)
# ─────────────────────────────────────────────────────────────────────────────

def _backups_for_template(backups):
    """Newest first, with a parsed datetime for display."""
    return [
        {'name': p.name, 'mtime': datetime.fromtimestamp(p.stat().st_mtime)}
        for p in reversed(backups)
    ]


def database_view(request):
    app_settings = AppSettings.get()
    status = sync_service.get_status(app_settings)
    last_sync_dt = None
    if status['last_sync_at']:
        try:
            last_sync_dt = datetime.fromisoformat(status['last_sync_at'])
        except ValueError:
            pass
    return render(request, 'database/database.html', {
        'active_nav': 'baza',
        'settings': app_settings,
        'status': status,
        'last_sync_dt': last_sync_dt,
        'backups': _backups_for_template(status['backups']),
        'interval_choices': AppSettings.SYNC_INTERVAL_CHOICES,
    })


@require_POST
def database_save(request):
    app_settings = AppSettings.get()
    path = request.POST.get('sync_folder_path', '').strip()
    interval_raw = request.POST.get('sync_interval_minutes', '').strip()

    if path:
        folder = Path(path)
        if not folder.is_dir():
            return JsonResponse({'ok': False, 'error': 'Папката не съществува.'}, status=400)
        if not os.access(folder, os.W_OK):
            return JsonResponse({'ok': False, 'error': 'Няма права за запис в тази папка.'}, status=400)

    valid_intervals = dict(AppSettings.SYNC_INTERVAL_CHOICES)
    try:
        interval_val = int(interval_raw)
    except (TypeError, ValueError):
        interval_val = app_settings.sync_interval_minutes
    if interval_val not in valid_intervals:
        interval_val = app_settings.sync_interval_minutes

    app_settings.sync_folder_path = path
    app_settings.sync_interval_minutes = interval_val
    app_settings.sync_auto_enabled = request.POST.get('sync_auto_enabled') == 'on'
    app_settings.save(update_fields=[
        'sync_folder_path', 'sync_interval_minutes', 'sync_auto_enabled',
    ])
    return JsonResponse({'ok': True})


@require_POST
def database_sync_now(request):
    if sync_service.local_data_changed():
        result = sync_service.push()
    else:
        result = {"status": "no_changes"}
    status = sync_service.get_status()
    return JsonResponse({
        'result': result,
        'status': {
            'configured': status['configured'],
            'reachable': status['reachable'],
            'conflict': status['conflict'],
            'last_sync_at': status['last_sync_at'],
            'last_sync_status': status['last_sync_status'],
            'backups': _backups_for_template_json(status['backups']),
        },
    })


def _backups_for_template_json(backups):
    return [
        {'name': p.name, 'mtime': datetime.fromtimestamp(p.stat().st_mtime).isoformat()}
        for p in reversed(backups)
    ]


def sync_conflict(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'keep_local':
            sync_service.push()
        elif action == 'pull_remote':
            sync_service.pull()
        from core.middleware import SyncStartupMiddleware
        SyncStartupMiddleware._conflict = False
        return redirect('core:dashboard')

    app_settings = AppSettings.get()
    status = sync_service.get_status(app_settings)
    backup_info = None
    if status['backups']:
        latest = status['backups'][-1]
        backup_info = {
            'name': latest.name,
            'mtime': datetime.fromtimestamp(latest.stat().st_mtime),
        }
    return render(request, 'sync/conflict.html', {
        'settings': app_settings,
        'status': status,
        'backup_info': backup_info,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Шаблони — Folder CRUD (Stage current batch)
# ─────────────────────────────────────────────────────────────────────────────

def _folders_json():
    return json.dumps(
        list(TemplateFolder.objects
             .filter(deleted_at__isnull=True)
             .order_by('parent_id', 'name')
             .values('id', 'name', 'parent_id')),
        ensure_ascii=False, default=str,
    )


def folder_create(request):
    if request.method == 'POST':
        name      = (request.POST.get('name') or '').strip()
        parent_id = request.POST.get('parent_id') or None
        if not name:
            return JsonResponse({'ok': False, 'error': 'Името е задължително.'}, status=422)
        parent = None
        if parent_id:
            parent = get_object_or_404(TemplateFolder, pk=parent_id, deleted_at__isnull=True)
        TemplateFolder.objects.create(name=name, parent=parent)
        from django.http import HttpResponse as _HR
        r = _HR(status=204)
        r['HX-Trigger'] = 'foldersChanged'
        return r
    return render(request, 'template_folders/_folder_form.html', {
        'folder': None,
        'folders_json': _folders_json(),
    })


def folder_edit(request, pk):
    folder = get_object_or_404(TemplateFolder, pk=pk, deleted_at__isnull=True)
    if request.method == 'POST':
        name      = (request.POST.get('name') or '').strip()
        parent_id = request.POST.get('parent_id') or None
        if not name:
            return JsonResponse({'ok': False, 'error': 'Името е задължително.'}, status=422)
        parent = None
        if parent_id:
            parent = get_object_or_404(TemplateFolder, pk=parent_id, deleted_at__isnull=True)
            # Prevent moving a folder into itself or its own descendants
            if str(parent.pk) == str(folder.pk):
                return JsonResponse({'ok': False, 'error': 'Папката не може да е в себе си.'}, status=422)
        folder.name   = name
        folder.parent = parent
        folder.save(update_fields=['name', 'parent'])
        from django.http import HttpResponse as _HR
        r = _HR(status=204)
        r['HX-Trigger'] = 'foldersChanged'
        return r
    return render(request, 'template_folders/_folder_form.html', {
        'folder': folder,
        'folders_json': _folders_json(),
    })


@require_http_methods(['DELETE'])
def folder_delete(request, pk):
    folder = get_object_or_404(TemplateFolder, pk=pk, deleted_at__isnull=True)
    folder.deleted_at = timezone.now()
    folder.save(update_fields=['deleted_at'])
    from django.http import HttpResponse as _HR
    r = _HR(status=204)
    r['HX-Trigger'] = 'foldersChanged'
    return r


# ─────────────────────────────────────────────────────────────────────────────
# Шаблони — Template actions (Stage current batch)
# ─────────────────────────────────────────────────────────────────────────────

def template_use(request, pk):
    """Open editor pre-filled from a template — creates a new protocol."""
    source = get_object_or_404(Protocol, pk=pk, is_preset=True, deleted_at__isnull=True)
    bootstrap = _build_editor_bootstrap()
    prefill = _build_prefill_from_protocol(source, include_pk=False)
    prefill['date'] = timezone.localdate().isoformat()
    prefill['source_template_id'] = str(source.pk)
    bootstrap['prefill'] = prefill
    return render(request, 'protocols/editor.html', {
        'active_nav':     'shabloni',
        'editor_mode':    'create_from',
        'bootstrap_json': json.dumps(bootstrap, ensure_ascii=False, default=str),
    })


def template_edit_view(request, pk):
    """Open the template in the editor for in-place editing."""
    template = get_object_or_404(Protocol, pk=pk, is_preset=True, deleted_at__isnull=True)
    bootstrap = _build_editor_bootstrap()
    bootstrap['prefill'] = _build_prefill_from_protocol(template, include_pk=True)
    return render(request, 'protocols/editor.html', {
        'active_nav':     'shabloni',
        'editor_mode':    'edit',
        'protocol_pk':    str(template.pk),
        'is_template':    True,
        'bootstrap_json': json.dumps(bootstrap, ensure_ascii=False, default=str),
    })


def template_move(request, pk):
    """Open or process the move-to-folder picker for a template."""
    template = get_object_or_404(Protocol, pk=pk, is_preset=True, deleted_at__isnull=True)
    if request.method == 'POST':
        folder_id = request.POST.get('folder_id') or None
        folder = None
        if folder_id:
            folder = get_object_or_404(TemplateFolder, pk=folder_id, deleted_at__isnull=True)
        template.folder = folder
        template.save(update_fields=['folder'])
        from django.http import HttpResponse as _HR
        r = _HR(status=204)
        r['HX-Trigger'] = 'templatesChanged'
        return r
    return render(request, 'template_folders/_template_move.html', {
        'template': template,
        'folders_json': _folders_json(),
    })


@require_http_methods(['DELETE'])
def template_delete(request, pk):
    template = get_object_or_404(Protocol, pk=pk, is_preset=True, deleted_at__isnull=True)
    template.deleted_at = timezone.now()
    template.save(update_fields=['deleted_at'])
    from django.http import HttpResponse as _HR
    r = _HR(status=204)
    r['HX-Trigger'] = 'templatesChanged'
    return r