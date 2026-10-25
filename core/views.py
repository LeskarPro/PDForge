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
from decimal import Decimal
from pathlib import Path
from core import sync_service

from django.db.models import Prefetch, Max, Count, Q, Exists, OuterRef

from core.models import (
    Protocol, ProtocolColumn, ProtocolProduct, TemplateFolder,
    Client, Site, Firm, SiteFirm, Contact, Tag,
    OneTimeTreatment, OneTimeTreatmentProduct, OneTimeTreatmentContact,
    Product, Pest, NonChemicalMean, Worker, Company,
    AppSettings, _first_of_this_month, DocumentStatus,
    PriceCatalogItem, ProtocolLineItem, OneTimeTreatmentLineItem, PaymentType,
)
from core.notes_html import sanitize_notes_html
from core.forms import (
    ClientForm, FirmForm, SiteFirmForm, SiteForm, SiteFormFull, ContactForm, TagForm,
    OneTimeTreatmentForm, ProductForm, CompanyForm, WorkerForm,
    PestForm, NonChemicalMeanForm, PriceCatalogItemForm,
)

# ─────────────────────────────────────────────────────────────────────────────
# Month+year date inputs (2026-06-21) — pairs with the month_year_select
# template tag, which renders "<field>_month" / "<field>_year" <select>
# elements instead of <input type="month"> (inconsistent native support
# across browsers/webviews was silently breaking date validation). Call
# this to fold the two posted parts back into a single "YYYY-MM" string
# before constructing/validating the Django form.
# ─────────────────────────────────────────────────────────────────────────────

def _merge_month_year(post, *field_names):
    """Returns a NEW QueryDict-like dict (mutable copy of `post`) where each
    given field name's `_month`/`_year` POST keys are combined into a single
    'YYYY-MM' value under that field name. If neither split key is present
    for a given field (e.g. a caller — the protocol editor's Alpine modal —
    still posts that field as one pre-combined value directly), the
    original value is left untouched."""
    merged = post.copy()
    for name in field_names:
        if f'{name}_month' not in post and f'{name}_year' not in post:
            continue
        month = post.get(f'{name}_month', '')
        year = post.get(f'{name}_year', '')
        merged[name] = f'{year}-{month}' if month and year else ''
    return merged


def _merge_date_select(post, *field_names):
    """Returns a NEW QueryDict-like dict (mutable copy of `post`) where each
    given field name's `_day`/`_month`/`_year` POST keys are combined into a
    single 'YYYY-MM-DD' value under that field name.

    Mirrors _merge_month_year — pair with the date_select template tag that
    renders the three <select> elements in the form. <input type="date"> is
    unreliable in the pywebview WebKit webview (same class of bug as
    <input type="month">, which this pattern already fixed for Firm/Site dates)."""
    merged = post.copy()
    for name in field_names:
        if f'{name}_day' not in post:
            continue
        day   = post.get(f'{name}_day', '').zfill(2)
        month = post.get(f'{name}_month', '').zfill(2)
        year  = post.get(f'{name}_year', '')
        merged[name] = f'{year}-{month}-{day}' if day and month and year else ''
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# Shared querysets
# ─────────────────────────────────────────────────────────────────────────────

def _clients_qs():
    active_sites = (
        Site.objects
        .filter(deleted_at__isnull=True)
        .prefetch_related('tags', 'firm_links__firm')
        .order_by('name')
    )
    # Stage 8a (reworked): a client with no active Site is inactive — kept
    # in the list (greyed out, sorted to the bottom), not hidden.
    # has_active_site is an annotation (Client.is_active is a derived
    # property, not a DB column) so templates/ordering can use it without an
    # extra query per row.
    has_active_site = Site.objects.filter(
        client_id=OuterRef('pk'), is_active=True, deleted_at__isnull=True,
    )
    return (
        Client.objects
        .filter(deleted_at__isnull=True)
        .annotate(
            has_active_site=Exists(has_active_site),
            site_count=Count('sites', filter=Q(sites__deleted_at__isnull=True), distinct=True),
            active_site_count=Count(
                'sites', filter=Q(sites__is_active=True, sites__deleted_at__isnull=True), distinct=True,
            ),
        )
        .prefetch_related(Prefetch('sites', queryset=active_sites), 'contacts')
        .order_by('-has_active_site', 'name')
    )


def _client_card_client(client_pk):
    """Fetch a single client with the same annotations/prefetches as
    _clients_qs() — needed whenever a single client's card is re-rendered
    on its own (live refresh after a site/contact change) instead of the
    whole Клиенти list, since has_active_site/site_count/active_site_count
    are queryset annotations, not real model fields."""
    return get_object_or_404(_clients_qs(), pk=client_pk)


def _oob_client_card(request, client_pk):
    """Rendered '<div ... hx-swap-oob>' for one client's card — appended to
    a response whose own hx-target is something else (e.g. a contacts modal),
    so the Клиенти list row behind it refreshes too without a page reload."""
    return render_to_string('clients/_client_card.html',
                            {'client': _client_card_client(client_pk), 'oob': True},
                            request=request)


def _sites_qs(client):
    return (
        client.sites
        .filter(deleted_at__isnull=True)
        .prefetch_related('tags')
        .order_by('-is_active', 'name')
    )


def _all_sites_qs(status=None):
    """Used by the standalone Обекти list page.

    Stage 8b: `status` filters to 'active' / 'inactive'; left unfiltered
    (None / anything else) shows both, with inactive sites sorted to the
    bottom rather than hidden.
    """
    qs = (
        Site.objects
        .filter(deleted_at__isnull=True)
        .select_related('client')
        .prefetch_related('tags')
    )
    if status == 'active':
        qs = qs.filter(is_active=True)
    elif status == 'inactive':
        qs = qs.filter(is_active=False)
    return qs.order_by('-is_active', 'client__name', 'name')


# ─────────────────────────────────────────────────────────────────────────────
# Existing unchanged views
# ─────────────────────────────────────────────────────────────────────────────

def dashboard(request):
    # TEMPORARY (Stage 6, price module) — helps Kiril find every protocol/
    # template/one-time treatment that still carries the migration's
    # catch-all "Други" line item, so he can go through and itemize each
    # one properly. Self-clearing: a record drops off this list the moment
    # its "Други" line is renamed/removed and resaved — no extra
    # bookkeeping. Safe to delete this whole block (and the matching
    # section in dashboard.html) once the cleanup is done; it's not part
    # of the planned Stage 12a Табло design.
    other_protocols = (
        Protocol.objects
        .filter(deleted_at__isnull=True, is_preset=False, line_items__snapshot_name='Други')
        .distinct()
        .select_related('client', 'site')
        .order_by('-date', '-created_at')
    )
    other_templates = (
        Protocol.objects
        .filter(deleted_at__isnull=True, is_preset=True, line_items__snapshot_name='Други')
        .distinct()
        .order_by('preset_name')
    )
    other_treatments = (
        OneTimeTreatment.objects
        .filter(deleted_at__isnull=True, line_items__snapshot_name='Други')
        .distinct()
        .order_by('-date', '-created_at')
    )
    other_total = other_protocols.count() + other_templates.count() + other_treatments.count()
    return render(request, "dashboard.html", {
        "active_nav": "dashboard",
        "other_protocols":  other_protocols,
        "other_templates":  other_templates,
        "other_treatments": other_treatments,
        "other_total":      other_total,
    })


def _split_other_pests(text):
    """Split a comma-separated free-text 'other pest' value into trimmed,
    non-empty, capitalized-first-letter parts. Server-side counterpart of
    the `split_pests_other` template filter — used for filter-menu option
    collection and for matching the `pests_other` GET param (matching is
    casefold-based, so the capitalization here doesn't affect it), never
    for anything rendered onto the actual protocol PDF (which reads
    pests_other as typed, untouched)."""
    if not text:
        return []
    out = []
    for p in text.split(','):
        p = p.strip()
        if p:
            out.append(p[0].upper() + p[1:])
    return out


def _protocol_other_pest_options():
    """Distinct 'other' pest values typed across non-deleted, non-template
    protocols, case-insensitively deduped (first-seen casing wins) for the
    filter menu — e.g. 'молци' and 'Молци' collapse into one chip."""
    texts = (
        ProtocolColumn.objects
        .filter(protocol__is_preset=False, protocol__deleted_at__isnull=True)
        .exclude(pests_other='')
        .values_list('pests_other', flat=True)
    )
    seen = {}
    for text in texts:
        for part in _split_other_pests(text):
            key = part.casefold()
            if key not in seen:
                seen[key] = part
    return sorted(seen.values(), key=str.casefold)


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
            # snapshot_firm_* (Stage 8a) rather than a site__firm_links__*
            # join — searches what's actually printed on this protocol, not
            # the site's whole firm history, and avoids row fan-out.
            'pseudonym', 'snapshot_firm_name', 'snapshot_firm_eik',
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

    other_vals = request.GET.getlist('pests_other')
    if other_vals:
        wanted = {v.strip().casefold() for v in other_vals if v.strip()}
        if wanted:
            rows = (
                ProtocolColumn.objects
                .filter(protocol__in=qs)
                .exclude(pests_other='')
                .values_list('protocol_id', 'pests_other')
            )
            matching_pks = {
                pid for pid, text in rows
                if wanted & {p.casefold() for p in _split_other_pests(text)}
            }
            qs = qs.filter(pk__in=matching_pks)

    return qs


def protocol_list(request):
    qs = _protocol_list_qs(request)
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    all_pests = list(Pest.objects.filter(deleted_at__isnull=True).order_by('category', 'name')
                     .values('id', 'name', 'category'))
    all_tags  = list(Tag.objects.filter(deleted_at__isnull=True).order_by('order', 'name')
                     .values('id', 'name', 'color'))
    all_pests_other = _protocol_other_pest_options()

    return render(request, 'protocols/list.html', {
        'active_nav': 'protokoli',
        'page_obj':   page_obj,
        'all_pests':  all_pests,
        'all_tags':   all_tags,
        'all_pests_other': all_pests_other,
        'active_q':      request.GET.get('q', ''),
        'active_pests':  request.GET.getlist('pests'),
        'active_tags':   request.GET.getlist('tags'),
        'active_pests_other': request.GET.getlist('pests_other'),
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
    show_deleted = (request.GET.get('mode') == 'deleted')

    current_folder = None
    if folder_id:
        if show_deleted:
            current_folder = get_object_or_404(TemplateFolder, pk=folder_id)
        else:
            current_folder = get_object_or_404(TemplateFolder, pk=folder_id, deleted_at__isnull=True)

    q = (request.GET.get('q') or '').strip()
    search_results = None
    subfolders     = TemplateFolder.objects.none()
    templates_qs   = Protocol.objects.none()

    if q:
        # Global search across the entire template library.
        # SQLite's icontains doesn't case-fold Cyrillic, so match in Python.
        qf = q.casefold()
        base_qs = (
            Protocol.objects
            .filter(is_preset=True, deleted_at__isnull=(not show_deleted))
            .select_related('client', 'site', 'folder')
            .prefetch_related('tags', 'columns__pests')
        )
        search_fields = (
            'pseudonym', 'preset_name', 'snapshot_firm_name', 'client__name',
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
    elif show_deleted:
        if current_folder:
            # Inside a deleted folder: show ALL children regardless of their own
            # deleted_at — pre-cascade data may have children with deleted_at=None.
            subfolders = (
                TemplateFolder.objects
                .filter(parent=current_folder)
                .annotate(
                    deleted_sub_count=Count('subfolders', distinct=True),
                    deleted_tpl_count=Count(
                        'templates',
                        filter=Q(templates__is_preset=True),
                        distinct=True,
                    ),
                )
                .order_by('name')
            )
            templates_qs = (
                Protocol.objects
                .filter(is_preset=True, folder=current_folder)
                .select_related('client', 'site')
                .prefetch_related('tags', 'columns__pests')
                .order_by('pseudonym', 'preset_name', '-created_at')
            )
        else:
            # Archive root: only top-level deleted items.
            subfolders = (
                TemplateFolder.objects
                .filter(parent__isnull=True, deleted_at__isnull=False)
                .annotate(
                    deleted_sub_count=Count('subfolders', distinct=True),
                    deleted_tpl_count=Count(
                        'templates',
                        filter=Q(templates__is_preset=True),
                        distinct=True,
                    ),
                )
                .order_by('name')
            )
            templates_qs = (
                Protocol.objects
                .filter(is_preset=True, folder__isnull=True, deleted_at__isnull=False)
                .select_related('client', 'site')
                .prefetch_related('tags', 'columns__pests')
                .order_by('pseudonym', 'preset_name', '-created_at')
            )
    else:
        subfolders = (
            TemplateFolder.objects
            .filter(parent=current_folder, deleted_at__isnull=True)
            .order_by('name')
        )
        templates_qs = (
            Protocol.objects
            .filter(is_preset=True, folder=current_folder, deleted_at__isnull=True)
            .select_related('client', 'site')
            .prefetch_related('tags', 'columns__pests')
            .order_by('pseudonym', 'preset_name', '-created_at')
        )

    # Badge count for the toggle button (total deleted items across the whole bin)
    deleted_count = (
        TemplateFolder.objects.filter(deleted_at__isnull=False).count()
        + Protocol.objects.filter(is_preset=True, deleted_at__isnull=False).count()
    )

    breadcrumb = current_folder.get_breadcrumb() if current_folder else []
    context = {
        'active_nav':     'shabloni',
        'current_folder': current_folder,
        'breadcrumb':     breadcrumb,
        'subfolders':     subfolders,
        'templates':      templates_qs,
        'search_query':   q,
        'search_results': search_results,
        'show_deleted':   show_deleted,
        'deleted_count':  deleted_count,
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


def _save_new_client_contacts(request, client):
    """Create Contact rows staged on the client-create form (Stage 10c-2).

    Only used at creation time, when the client is guaranteed to have no
    contacts yet — unlike `_save_treatment_contacts` this does NOT delete
    existing contacts first, so it must never be called from client_edit
    (that would risk wiping Contact<->Site links managed by the separate
    contacts UI). The protocol editor's own "+ Нов клиент" modal posts
    contacts one-by-one to a different endpoint, so these lists are simply
    empty/absent there — this is a no-op in that flow.
    """
    names     = request.POST.getlist('contact_name')
    phones    = request.POST.getlist('contact_phone')
    positions = request.POST.getlist('contact_position')
    for i, name in enumerate(names):
        name = name.strip()
        if not name:
            continue
        Contact.objects.create(
            client=client,
            name=name,
            phone=phones[i].strip()    if i < len(phones)    else '',
            position=positions[i].strip() if i < len(positions) else '',
            order=i,
        )


def client_create(request):
    """Create a client.

    Stage 2b adds a `?as=json` (or POST field `as=json`) mode used by the
    protocol editor's "+ Нов клиент" modal:
      * success → 200 JSON with the new client's fields (no HTML render).
      * validation failure → 422 JSON with form errors.
    Existing HTMX behaviour is preserved when `as` is absent.

    Stage 10c-2 adds optional staged `contact_name`/`contact_phone`/
    `contact_position` repeated POST fields (Клиенти page create form only)
    — see `_save_new_client_contacts`.

    Stage 8a (reworked 2026-06-19): Firm no longer attaches to Client at
    all (it attaches to Site, via SiteFirm) — Client creation is back to
    just name + notes, no firm bundling.
    """
    as_json = request.GET.get('as') == 'json' or request.POST.get('as') == 'json'
    if request.method == 'POST':
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save()
            _save_new_client_contacts(request, client)
            if as_json:
                return JsonResponse({
                    'ok': True,
                    'client': {
                        'id': str(client.pk),
                        'name': client.name,
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
    contacts = client.contacts.order_by('order', 'created_at')
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
                      {'form': form, 'mode': 'edit', 'client': client, 'contacts': contacts})
    return render(request, 'clients/_client_form.html',
                  {'form': ClientForm(instance=client), 'mode': 'edit', 'client': client, 'contacts': contacts})


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
    status = request.GET.get('status')
    return render(request, 'sites/list.html', {
        'active_nav': 'obekti',
        'sites': _all_sites_qs(status),
        'status': status or 'all',
    })


def site_list_body(request):
    """HTMX partial: re-render the sites list (after contacts change, or the
    active/inactive filter changes, on the Обекти page)."""
    status = request.GET.get('status')
    return render(request, 'sites/_list_body.html', {
        'sites': _all_sites_qs(status),
    })


def site_create(request, client_pk):
    """Create a site from the Клиенти accordion (client is fixed).

    Stage 10c-2 adds an optional `contacts` POST list (repeated field, contact
    PKs) — mirrors site_create_full's Stage 10c logic, scoped to this client
    so a stray/foreign id can't link a contact across clients. The form's
    "Контактни лица" checklist is rendered server-side since the client is
    already known here.
    """
    client = get_object_or_404(Client, pk=client_pk, deleted_at__isnull=True)
    client_contacts = client.contacts.order_by('order', 'created_at')
    if request.method == 'POST':
        form = SiteForm(_merge_month_year(request.POST, 'start_date', 'end_date'))
        if form.is_valid():
            site = form.save(commit=False)
            site.client = client
            site.save()
            form.save_m2m()
            _process_site_firm_from_post(request, site)
            contact_ids = request.POST.getlist('contacts')
            if contact_ids:
                site.contacts.set(
                    Contact.objects.filter(pk__in=contact_ids, client=client)
                )
            response = render(request, 'clients/_client_card.html',
                              {'client': _client_card_client(client.pk)})
            response['HX-Retarget'] = f'#card-{client.pk}'
            response['HX-Reswap']   = 'outerHTML'
            response['HX-Trigger']  = 'closeModal'
            return response
        selected_contact_ids = set(request.POST.getlist('contacts'))
        return render(request, 'clients/_site_form.html',
                      {'form': form, 'client': client, 'mode': 'create', 'ctx': 'clients',
                       'client_contacts': client_contacts,
                       'selected_contact_ids': selected_contact_ids})
    return render(request, 'clients/_site_form.html',
                  {'form': SiteForm(initial={'start_date': _first_of_this_month()}),
                   'client': client, 'mode': 'create', 'ctx': 'clients',
                   'client_contacts': client_contacts, 'selected_contact_ids': set()})


def _site_form_all_clients():
    """Client list for the type-to-filter client picker in the standalone
    Обекти site-creation/edit form (Stage: task 3 customer feedback).
    Pseudonym (name) only — Client has no firm/address of its own since the
    8a rework. json_script (used in the template) handles the UUID id via
    DjangoJSONEncoder, no manual str() needed here."""
    return list(
        Client.objects.filter(deleted_at__isnull=True)
        .order_by('name').values('id', 'name')
    )


def site_create_full(request):
    """Create a site from the Обекти page (client is chosen in the form).

    Stage 2b adds a `?as=json` (or POST field `as=json`) mode used by the
    protocol editor's "+ Нов обект" modal:
      * success → 200 JSON with the new site's fields.
      * validation failure → 422 JSON with form errors.
    Existing HTMX behaviour is preserved when `as` is absent.

    Stage 10c adds an optional `contacts` POST list (repeated field, contact
    PKs) — used by the protocol editor's new-site modal to link zero-to-many
    of the chosen client's existing contacts at creation time. Scoped to the
    site's own client so a stray/foreign id can't link a contact across
    clients. The standalone Обекти page form doesn't send this field, so its
    behaviour is unchanged.
    """
    as_json = request.GET.get('as') == 'json' or request.POST.get('as') == 'json'
    if request.method == 'POST':
        form = SiteFormFull(_merge_month_year(request.POST, 'start_date', 'end_date'))
        if form.is_valid():
            site = form.save(commit=False)
            if as_json:
                # Protocol editor's quick "+ Нов обект" modal doesn't show
                # the active/inactive toggle (Stage 8b) — a site created this
                # way is always active; start_date still comes from the
                # modal's own date field (defaults to this month, editable).
                site.is_active = True
                site.end_date = None
            site.save()
            form.save_m2m()
            _process_site_firm_from_post(request, site)
            contact_ids = request.POST.getlist('contacts')
            if contact_ids:
                site.contacts.set(
                    Contact.objects.filter(pk__in=contact_ids, client=site.client)
                )
            if as_json:
                return JsonResponse({
                    'ok': True,
                    'site': {
                        'id': str(site.pk),
                        'client_id': str(site.client_id),
                        'client_name': site.client.name,
                        'pseudonym': site.pseudonym,
                        'name': site.name,
                        'address': site.address,
                        'area_m2': site.area_m2,
                        'is_active': site.is_active,
                        # Brand new — no firm linked yet (done from the 9b
                        # site popup afterwards).
                        'firm': '', 'eik': '', 'firm_address': '', 'phone': '',
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
        ctx = {'form': form, 'mode': 'create', 'ctx': 'sites', 'show_client': True,
               'all_clients': _site_form_all_clients()}
        chosen_client_id = request.POST.get('client')
        if chosen_client_id:
            ctx['client_contacts'] = Contact.objects.filter(
                client_id=chosen_client_id).order_by('order', 'created_at')
            ctx['selected_contact_ids'] = set(request.POST.getlist('contacts'))
            ctx['selected_client'] = Client.objects.filter(
                pk=chosen_client_id, deleted_at__isnull=True).first()
        return render(request, 'clients/_site_form.html', ctx)
    return render(request, 'clients/_site_form.html',
                  {'form': SiteFormFull(initial={'start_date': _first_of_this_month()}),
                   'all_clients': _site_form_all_clients(),
                   'mode': 'create', 'ctx': 'sites', 'show_client': True})


def site_edit(request, pk):
    """Edit a site. Stage 8a (further reworked 2026-06-21): uses
    SiteFormFull (not the plain SiteForm) so the client itself is also
    reassignable here, not just at creation."""
    site = get_object_or_404(Site, pk=pk, deleted_at__isnull=True)
    client = site.client
    ctx = request.GET.get('ctx', 'clients')  # persisted via hidden field on POST

    if request.method == 'POST':
        ctx = request.POST.get('_ctx', 'clients')
        form = SiteFormFull(_merge_month_year(request.POST, 'start_date', 'end_date'), instance=site)
        if form.is_valid():
            form.save()
            _process_site_firm_from_post(request, site)
            if ctx == 'sites':
                response = render(request, 'sites/_list_body.html',
                                  {'sites': _all_sites_qs()})
                response['HX-Retarget'] = '#site-list'
                response['HX-Reswap']  = 'innerHTML'
            else:
                response = render(request, 'clients/_client_card.html',
                                  {'client': _client_card_client(client.pk)})
                response['HX-Retarget'] = f'#card-{client.pk}'
                response['HX-Reswap']  = 'outerHTML'
            response['HX-Trigger'] = 'closeModal'
            return response
        return render(request, 'clients/_site_form.html',
                      {'form': form, 'site': site, 'client': client, 'mode': 'edit',
                       'ctx': ctx, 'show_client': True, 'current_firm': site.active_firm,
                       'all_clients': _site_form_all_clients(), 'selected_client': client})
    return render(request, 'clients/_site_form.html',
                  {'form': SiteFormFull(instance=site), 'site': site,
                   'client': client, 'mode': 'edit', 'ctx': ctx,
                   'show_client': True, 'current_firm': site.active_firm,
                   'all_clients': _site_form_all_clients(), 'selected_client': client})


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
    response = render(request, 'clients/_client_card.html',
                      {'client': _client_card_client(client.pk)})
    response['HX-Retarget'] = f'#card-{client.pk}'
    response['HX-Reswap']  = 'outerHTML'
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Site popup (9b) + Firm management (Stage 8a, reworked 2026-06-19 — Firm
# attaches to Site via SiteFirm, not to Client). The client popup (9a) was
# removed 2026-06-21 per Kiril — client management (contacts, etc.) now
# lives directly on the client create/edit form instead.
# ─────────────────────────────────────────────────────────────────────────────

def site_popup(request, pk):
    """9b — full site detail popup: the site's own status, and the
    firm-link archive scoped to this site."""
    site = get_object_or_404(Site, pk=pk, deleted_at__isnull=True)
    firm_links = (
        site.firm_links
        .filter(deleted_at__isnull=True)
        .select_related('firm')
        .order_by('-is_active', '-start_date')
    )
    return render(request, 'sites/_popup.html', {
        'site': site,
        'client': site.client,
        'firm_links': firm_links,
    })


@require_POST
def firm_create_inline(request):
    """AJAX: create a standalone Firm record on its own (2026-06-21) — used
    by the site create/edit form's "Нова фирма" tab so clicking "Запази
    фирмата" stages it immediately (visible confirmation) without waiting
    for the whole site form to submit. The site doesn't need to exist yet
    for this — Firm is standalone; the SiteFirm *link* is only created once
    the site itself saves (see _process_site_firm_from_post)."""
    form = FirmForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': form.errors}, status=422)
    firm = form.save()
    return JsonResponse({'ok': True, 'id': str(firm.pk), 'name': firm.name, 'eik': firm.eik})


def firm_search(request, site_pk=None):
    """JSON: search reusable Firm records by name/EIK — used by the site
    popup's "+ Свържи фирма" tab (site_pk set) and by the site create/edit
    form's own embedded Firm section (site_pk=None, no site exists yet at
    creation time — see firm_search_generic in urls.py)."""
    if site_pk:
        get_object_or_404(Site, pk=site_pk, deleted_at__isnull=True)
    q = (request.GET.get('q') or '').strip()
    qs = Firm.objects.filter(deleted_at__isnull=True)
    if q:
        # SQLite's default icontains doesn't case-fold Cyrillic — match in
        # Python instead, same pattern used elsewhere in this file.
        qf = q.casefold()
        rows = qs.values('id', 'name', 'eik')
        matching_ids = [r['id'] for r in rows if qf in f"{r['name']} {r['eik']}".casefold()]
        qs = qs.filter(pk__in=matching_ids)
    results = [
        {
            'id': str(f.pk), 'name': f.name, 'eik': f.eik, 'address': f.address,
            'site_count': f.site_links.filter(deleted_at__isnull=True)
                           .values('site_id').distinct().count(),
        }
        for f in qs.order_by('name')[:20]
    ]
    return JsonResponse({'results': results})


@require_POST
def site_firm_link_create(request, site_pk):
    """"+ Свържи фирма" in the 9b popup — links this site to either an
    existing reusable Firm (`firm_id` in POST) or a brand-new one (firm
    fields in POST), then creates the SiteFirm link."""
    site = get_object_or_404(Site, pk=site_pk, deleted_at__isnull=True)
    firm_id = request.POST.get('firm_id')
    if firm_id:
        firm = get_object_or_404(Firm, pk=firm_id, deleted_at__isnull=True)
    else:
        firm_form = FirmForm(request.POST)
        if not firm_form.is_valid():
            return render(request, 'sites/_firm_link_errors.html',
                          {'errors': firm_form.errors}, status=422)
        firm = firm_form.save()

    merged = _merge_month_year(request.POST, 'start_date')
    link_form = SiteFirmForm(data={
        'is_active': True,
        'start_date': merged.get('start_date', ''),
    })
    if not link_form.is_valid():
        return render(request, 'sites/_firm_link_errors.html',
                      {'errors': link_form.errors}, status=422)
    link = link_form.save(commit=False)
    link.site = site
    link.firm = firm
    link.save()

    response = render(request, 'sites/_firm_links_section.html', {
        'site': site, 'firm_links': _site_firm_links_qs(site),
    })
    response['HX-Trigger'] = 'closeFirmLinkForm'
    return response


def _site_firm_links_qs(site):
    return (
        site.firm_links
        .filter(deleted_at__isnull=True)
        .select_related('firm')
        .order_by('-is_active', '-start_date')
    )


def _process_site_firm_from_post(request, site):
    """Optional Firm select/create section embedded directly in the site
    create/edit form (2026-06-21) — leaving it blank means "don't touch the
    site's current firm link". Mirrors site_firm_link_create's logic but
    is called from the site form's own save path instead of the 9b popup's
    dedicated endpoint.
    """
    firm_id = request.POST.get('firm_id')
    firm_name = (request.POST.get('firm_name') or '').strip()
    if not firm_id and not firm_name:
        return
    if firm_id:
        firm = Firm.objects.filter(pk=firm_id, deleted_at__isnull=True).first()
        if not firm:
            return
    else:
        firm_form = FirmForm(data={
            'name': firm_name,
            'eik': request.POST.get('firm_eik', ''),
            'address': request.POST.get('firm_address', ''),
            'phone': request.POST.get('firm_phone', ''),
        })
        if not firm_form.is_valid():
            return
        firm = firm_form.save()

    merged = _merge_month_year(request.POST, 'firm_start_date')
    link_form = SiteFirmForm(data={
        'is_active': True,
        'start_date': merged.get('firm_start_date', ''),
    })
    if not link_form.is_valid():
        return
    link = link_form.save(commit=False)
    link.site = site
    link.firm = firm
    link.save()


@require_POST
def site_firm_link_toggle(request, pk):
    """Sliding toggle switch in the 9b popup — flips a SiteFirm link's
    is_active. Turning it back on auto-clears end_date and (per
    SiteFirm.save()) auto-ends any other active link for the same site."""
    link = get_object_or_404(SiteFirm, pk=pk, deleted_at__isnull=True)
    link.is_active = not link.is_active
    if not link.is_active and not link.end_date:
        link.end_date = timezone.localdate().replace(day=1)
    link.save()
    return render(request, 'sites/_firm_links_section.html', {
        'site': link.site, 'firm_links': _site_firm_links_qs(link.site),
    })


@require_http_methods(["DELETE"])
def site_firm_link_delete(request, pk):
    """Delete button on every firm-link row in the 9b popup (active or
    inactive — Kiril asked for delete on all rows, not just ended ones)."""
    link = get_object_or_404(SiteFirm, pk=pk, deleted_at__isnull=True)
    site = link.site
    link.deleted_at = timezone.now()
    link.save()
    return render(request, 'sites/_firm_links_section.html', {
        'site': site, 'firm_links': _site_firm_links_qs(site),
    })


def _firmi_qs():
    firms = list(
        Firm.objects.filter(deleted_at__isnull=True)
        .prefetch_related(
            Prefetch(
                'site_links',
                queryset=SiteFirm.objects.filter(deleted_at__isnull=True)
                .select_related('site', 'site__client').order_by('-is_active', 'site__pseudonym'),
            ),
        )
        .order_by('name')
    )
    for firm in firms:
        links = list(firm.site_links.all())
        firm.links = links
        # Distinct client names, in first-seen order — a firm can in theory
        # be linked to sites under more than one client.
        seen = []
        for link in links:
            name = link.site.client.name
            if name not in seen:
                seen.append(name)
        firm.client_names = seen
    return firms


def firmi_list(request):
    """Top-level Фирми page (after Обекти in the nav)."""
    return render(request, 'firmi/list.html', {
        'active_nav': 'firmi',
        'firms': _firmi_qs(),
    })


def firmi_list_body(request):
    return render(request, 'firmi/_list_body.html', {'firms': _firmi_qs()})


def firm_edit(request, pk):
    """Edit a Firm directly from the Фирми page — it's a standalone reusable
    record, so this updates the data everywhere the firm is linked."""
    firm = get_object_or_404(Firm, pk=pk, deleted_at__isnull=True)
    if request.method == 'POST':
        form = FirmForm(request.POST, instance=firm)
        if form.is_valid():
            form.save()
            r = HttpResponse(status=204)
            r['HX-Trigger'] = 'firmsChanged'
            return r
    else:
        form = FirmForm(instance=firm)
    return render(request, 'firmi/_form.html', {'form': form, 'firm': firm})


def firm_delete_confirm(request, pk):
    """Confirm-delete modal for a Firm — the delete itself is permanent and
    hard (see firm_delete below), so this warns explicitly and lists every
    site whose link to this firm will be wiped, before the delete button
    becomes clickable (gated by a required checkbox in the template)."""
    firm = get_object_or_404(Firm, pk=pk, deleted_at__isnull=True)
    links = (
        firm.site_links
        .filter(deleted_at__isnull=True)
        .select_related('site', 'site__client')
        .order_by('-is_active', 'site__pseudonym')
    )
    return render(request, 'firmi/_confirm_delete.html', {'firm': firm, 'links': links})


@require_http_methods(['DELETE'])
def firm_delete(request, pk):
    """Hard-delete a Firm. CASCADE on SiteFirm.firm removes all link rows
    automatically, so deleted firms can never block site lookups or reuse
    of the same EIK for a new firm. Protocols are unaffected — their
    snapshot_firm_* fields are frozen text with no FK back to Firm."""
    firm = get_object_or_404(Firm, pk=pk, deleted_at__isnull=True)
    firm.delete()
    response = render(request, 'firmi/_list_body.html', {'firms': _firmi_qs()})
    response['HX-Trigger'] = 'closeModal'
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Contact views  (client-level contacts + site M2M assignment)
# ─────────────────────────────────────────────────────────────────────────────

def client_contacts(request, client_pk):
    """HTMX: open the client contacts management modal."""
    client = get_object_or_404(Client, pk=client_pk, deleted_at__isnull=True)
    return render(request, 'clients/_client_contacts_modal.html', {
        'client': client,
        'contacts': client.contacts.order_by('order', 'created_at'),
        'form': ContactForm(),
    })


def contact_create(request, client_pk):
    """HTMX POST: add a contact to a client."""
    client = get_object_or_404(Client, pk=client_pk, deleted_at__isnull=True)
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            contact = form.save(commit=False)
            contact.client = client
            max_order = client.contacts.aggregate(m=Max('order'))['m']
            contact.order = (max_order or 0) + 1
            contact.save()
            html = render_to_string('clients/_client_contacts_list.html', {
                'client': client,
                'contacts': client.contacts.order_by('order', 'created_at'),
            }, request=request)
            return HttpResponse(html + _oob_client_card(request, client.pk))
        return render(request, 'clients/_client_contacts_modal.html', {
            'client': client,
            'contacts': client.contacts.order_by('order', 'created_at'),
            'form': form,
        })
    return render(request, 'clients/_client_contacts_modal.html', {
        'client': client,
        'contacts': client.contacts.order_by('order', 'created_at'),
        'form': ContactForm(),
    })


@require_http_methods(["DELETE"])
def contact_delete(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    client = contact.client
    contact.delete()
    html = render_to_string('clients/_client_contacts_list.html', {
        'client': client,
        'contacts': client.contacts.order_by('order', 'created_at'),
    }, request=request)
    return HttpResponse(html + _oob_client_card(request, client.pk))


@require_http_methods(["POST"])
def contact_move(request, pk, direction):
    contact = get_object_or_404(Contact, pk=pk)
    client = contact.client
    contacts = list(client.contacts.order_by('order', 'created_at'))
    for i, c in enumerate(contacts):
        c.order = i
    Contact.objects.bulk_update(contacts, ['order'])
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
    html = render_to_string('clients/_client_contacts_list.html', {
        'client': client,
        'contacts': client.contacts.order_by('order', 'created_at'),
    }, request=request)
    return HttpResponse(html + _oob_client_card(request, client.pk))


def contact_edit(request, pk):
    """HTMX: inline-edit a single contact row.

    GET  → re-render the list with this row swapped into edit-mode inputs.
    POST → validate + save, re-render the list back in display mode.
    """
    contact = get_object_or_404(Contact, pk=pk)
    client = contact.client
    if request.method == 'POST':
        form = ContactForm(request.POST, instance=contact)
        if form.is_valid():
            form.save()
            html = render_to_string('clients/_client_contacts_list.html', {
                'client': client,
                'contacts': client.contacts.order_by('order', 'created_at'),
            }, request=request)
            return HttpResponse(html + _oob_client_card(request, client.pk))
        return render(request, 'clients/_client_contacts_list.html', {
            'client': client,
            'contacts': client.contacts.order_by('order', 'created_at'),
            'editing_pk': contact.pk,
            'edit_form': form,
        })
    return render(request, 'clients/_client_contacts_list.html', {
        'client': client,
        'contacts': client.contacts.order_by('order', 'created_at'),
        'editing_pk': contact.pk,
    })


def client_contacts_list(request, client_pk):
    """HTMX: re-render the bare contacts list — used to cancel an inline edit."""
    client = get_object_or_404(Client, pk=client_pk, deleted_at__isnull=True)
    return render(request, 'clients/_client_contacts_list.html', {
        'client': client,
        'contacts': client.contacts.order_by('order', 'created_at'),
    })


def client_contacts_json(request, client_pk):
    """JSON: return all contacts for a client (used by site form + protocol editor)."""
    client = get_object_or_404(Client, pk=client_pk, deleted_at__isnull=True)
    data = [
        {
            'id': str(c.pk),
            'name': c.name,
            'phone': c.phone,
            'position': c.position,
        }
        for c in client.contacts.order_by('order', 'created_at')
    ]
    return JsonResponse({'contacts': data})


def site_contacts(request, site_pk):
    """HTMX: manage which of a client's contacts are linked to this site."""
    site = get_object_or_404(Site, pk=site_pk, deleted_at__isnull=True)
    client = site.client
    all_contacts = client.contacts.order_by('order', 'created_at')
    linked_ids = set(site.contacts.values_list('pk', flat=True))

    if request.method == 'POST':
        selected_ids = request.POST.getlist('contacts')
        site.contacts.set(
            Contact.objects.filter(pk__in=selected_ids, client=client)
        )
        linked_ids = set(site.contacts.values_list('pk', flat=True))
        # Return updated list so HTMX can swap it
        return render(request, 'clients/_contacts_modal.html', {
            'site': site,
            'client': client,
            'all_contacts': all_contacts,
            'linked_ids': linked_ids,
            'saved': True,
        })

    return render(request, 'clients/_contacts_modal.html', {
        'site': site,
        'client': client,
        'all_contacts': all_contacts,
        'linked_ids': linked_ids,
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


def tag_create_inline(request):
    """Lightweight JSON endpoint for inline tag creation from any picker."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    form = TagForm(request.POST)
    if form.is_valid():
        max_order = Tag.objects.filter(deleted_at__isnull=True).aggregate(m=Max('order'))['m']
        tag = form.save(commit=False)
        tag.order = (max_order or 0) + 1
        tag.save()
        return JsonResponse({'id': str(tag.pk), 'name': tag.name, 'color': tag.color})
    return JsonResponse({'errors': form.errors}, status=400)


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
        .prefetch_related('pests', 'executed_by', 'tags', 'products__product', 'contacts')
        .order_by('-date', '-created_at')
    )


def _one_time_other_pest_options():
    """Distinct 'other' pest values typed across non-deleted one-time
    treatments — same split/casefold-dedupe rules as
    _protocol_other_pest_options(), just against a single flat field
    instead of one per column."""
    texts = (
        OneTimeTreatment.objects
        .filter(deleted_at__isnull=True)
        .exclude(pests_other='')
        .values_list('pests_other', flat=True)
    )
    seen = {}
    for text in texts:
        for part in _split_other_pests(text):
            key = part.casefold()
            if key not in seen:
                seen[key] = part
    return sorted(seen.values(), key=str.casefold)


def _oob_other_pests_filter_one_time(request):
    """Rendered '<div id=ot-other-pests-filter ... hx-swap-oob>' with a
    freshly recomputed 'Други' chip list — appended to the
    create/edit/delete responses so a brand-new (or now-unused) typed
    'other' pest value appears/disappears from the filter panel right
    away, without needing a full page reload. Doesn't attempt to preserve
    whatever filter checkboxes were checked on the underlying list page —
    that state isn't visible to this request (the modal POST doesn't carry
    the list page's query string), so this always renders unchecked."""
    return render_to_string('one_time/_other_pests_filter.html', {
        'all_pests_other':    _one_time_other_pest_options(),
        'active_pests_other': [],
        'oob': True,
    }, request=request)


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


def _parse_line_items_from_querydict(data):
    """Shared by _save_treatment_line_items() and _form_ctx()'s error
    re-render, so a failed OneTimeTreatmentForm validation doesn't silently
    wipe out already-typed line items (products/contacts have this same
    limitation today — deliberately not fixing those here too, out of
    scope for the price module, but not worth reproducing for money data)."""
    catalog_ids = data.getlist('li_catalog_item_id')
    names       = data.getlist('li_name')
    item_types  = data.getlist('li_item_type')
    ncm_flags   = data.getlist('li_has_ncm_link')
    quantities  = data.getlist('li_quantity')
    prices      = data.getlist('li_price')
    out = []
    for i, name in enumerate(names):
        out.append({
            'catalog_item_id': catalog_ids[i] if i < len(catalog_ids) else '',
            'name':            name,
            'item_type':       item_types[i] if i < len(item_types) else 'service',
            'has_ncm_link':    (ncm_flags[i] if i < len(ncm_flags) else '') == '1',
            'quantity':        quantities[i] if i < len(quantities) else '0',
            'price':           prices[i] if i < len(prices) else '',
        })
    return out


def _save_treatment_line_items(request, treatment):
    """Snapshots are frozen at insert (same rewrite-from-scratch pattern as
    _save_treatment_products). `price` is then computed from these lines
    and written back onto the treatment row — same rule as Protocol
    (Stage 4): None when there are no lines at all, else the sum of
    qty*price across lines that actually have a price."""
    treatment.line_items.all().delete()
    rows = _parse_line_items_from_querydict(request.POST)
    net_total = None
    if rows:
        net_total = Decimal('0')
        for i, row in enumerate(rows):
            catalog_id = _safe_uuid(row['catalog_item_id'])
            catalog_item = (
                PriceCatalogItem.objects.filter(pk=catalog_id).first()
                if catalog_id else None
            )
            quantity = _safe_decimal(row['quantity'])
            if quantity is None:
                quantity = Decimal('0')
            price = _safe_decimal(row['price'])
            name = (
                row['name']
                or (catalog_item.name if catalog_item else '')
            )[:255]
            item_type = (
                row['item_type']
                or (catalog_item.item_type if catalog_item else PriceCatalogItem.ItemType.SERVICE)
            )
            OneTimeTreatmentLineItem.objects.create(
                treatment=treatment,
                catalog_item=catalog_item,
                quantity=quantity,
                price=price,
                order=i,
                snapshot_name=name,
                snapshot_item_type=item_type,
                snapshot_has_ncm_link=row['has_ncm_link'],
            )
            if price is not None:
                net_total += quantity * price

    treatment.price = net_total
    if treatment.tax_included and net_total is not None:
        # tax_rate_snapshot was already frozen (or re-confirmed) by the
        # form's own .save() call just before this runs — see Protocol's
        # identical rule in _save_or_rewrite_protocol.
        vat_percent = treatment.tax_rate_snapshot
        if vat_percent is None:
            vat_percent = AppSettings.get().vat_percent
        treatment.price_with_tax = (net_total * (1 + vat_percent / 100)).quantize(Decimal('0.01'))
    else:
        treatment.price_with_tax = None
    treatment.save()


def _save_treatment_contacts(request, treatment):
    treatment.contacts.all().delete()
    names     = request.POST.getlist('contact_name')
    phones    = request.POST.getlist('contact_phone')
    positions = request.POST.getlist('contact_position')
    for i, name in enumerate(names):
        name = name.strip()
        if not name:
            continue
        OneTimeTreatmentContact.objects.create(
            treatment=treatment,
            name=name,
            phone=phones[i].strip()    if i < len(phones)    else '',
            position=positions[i].strip() if i < len(positions) else '',
            order=i,
        )


def one_time_list(request):
    q = request.GET.get('q', '').strip()
    pest_ids = request.GET.getlist('pests')
    tag_ids  = request.GET.getlist('tags')

    qs = _one_time_qs()
    if q:
        # SQLite's default icontains only case-folds ASCII, so Cyrillic
        # searches were case-sensitive without the ICU extension — match in
        # Python with .casefold() instead, same pattern as protocol/client
        # search. contacts__name fans out one row per contact (LEFT OUTER
        # JOIN via the reverse FK), so a treatment with no contacts still
        # gets a row (contacts__name=None) and isn't dropped.
        qf = q.casefold()
        search_fields = ('pseudonym', 'address', 'contacts__name')
        rows = qs.values('pk', *search_fields)
        matching_pks = {
            row['pk'] for row in rows
            if qf in ' '.join(str(row.get(f) or '') for f in search_fields).casefold()
        }
        qs = qs.filter(pk__in=matching_pks)
    if pest_ids:
        qs = qs.filter(pests__pk__in=pest_ids).distinct()
    if tag_ids:
        qs = qs.filter(tags__pk__in=tag_ids).distinct()

    other_vals = request.GET.getlist('pests_other')
    if other_vals:
        wanted = {v.strip().casefold() for v in other_vals if v.strip()}
        if wanted:
            rows = (
                OneTimeTreatment.objects
                .filter(pk__in=qs.values('pk'))
                .exclude(pests_other='')
                .values_list('pk', 'pests_other')
            )
            matching_pks = {
                pid for pid, text in rows
                if wanted & {p.casefold() for p in _split_other_pests(text)}
            }
            qs = qs.filter(pk__in=matching_pks)

    all_pests = list(Pest.objects.filter(deleted_at__isnull=True).order_by('category', 'name')
                     .values('id', 'name', 'category'))
    all_tags  = list(Tag.objects.filter(deleted_at__isnull=True).order_by('order', 'name')
                     .values('id', 'name', 'color'))
    all_pests_other = _one_time_other_pest_options()

    ctx = {
        'treatments':    qs,
        'q':             q,
        'active_pests':  pest_ids,
        'active_tags':   tag_ids,
        'all_pests':     all_pests,
        'all_tags':      all_tags,
        'all_pests_other':    all_pests_other,
        'active_pests_other': other_vals,
        'active_nav':    'ednokratni',
    }
    if request.headers.get('HX-Request'):
        return render(request, 'one_time/_list_body.html', ctx)
    return render(request, 'one_time/list.html', ctx)


def one_time_create(request):
    if request.method == 'POST':
        form = OneTimeTreatmentForm(request.POST)
        if form.is_valid():
            treatment = form.save(commit=False)
            if not treatment.date:
                treatment.date = timezone.localdate()
            treatment.save()
            form.save_m2m()
            _save_treatment_products(request, treatment)
            _save_treatment_contacts(request, treatment)
            _save_treatment_line_items(request, treatment)
            html = render_to_string('one_time/_list_body.html',
                                    {'treatments': _one_time_qs()}, request=request)
            response = HttpResponse(html + _oob_other_pests_filter_one_time(request))
            response['HX-Trigger'] = 'closeModal'
            return response
        # form invalid — re-render inside the modal, not the list area
        err = render(request, 'one_time/_form.html', _form_ctx(request, form, 'create'))
        err['HX-Retarget'] = '#modal-content'
        err['HX-Reswap']   = 'innerHTML'
        return err

    form = OneTimeTreatmentForm()
    return render(request, 'one_time/_form.html', _form_ctx(request, form, 'create'))


def one_time_edit(request, pk):
    treatment = get_object_or_404(OneTimeTreatment, pk=pk, deleted_at__isnull=True)
    if request.method == 'POST':
        form = OneTimeTreatmentForm(request.POST, instance=treatment)
        if form.is_valid():
            treatment = form.save(commit=False)
            if not treatment.date:
                treatment.date = timezone.localdate()
            treatment.save()
            form.save_m2m()
            _save_treatment_products(request, treatment)
            _save_treatment_contacts(request, treatment)
            _save_treatment_line_items(request, treatment)
            html = render_to_string('one_time/_list_body.html',
                                    {'treatments': _one_time_qs()}, request=request)
            response = HttpResponse(html + _oob_other_pests_filter_one_time(request))
            response['HX-Trigger'] = 'closeModal'
            return response
        # form invalid — re-render inside the modal
        err = render(request, 'one_time/_form.html', _form_ctx(request, form, 'edit', treatment))
        err['HX-Retarget'] = '#modal-content'
        err['HX-Reswap']   = 'innerHTML'
        return err

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
    html = render_to_string('one_time/_list_body.html',
                            {'treatments': _one_time_qs()}, request=request)
    response = HttpResponse(html + _oob_other_pests_filter_one_time(request))
    response['HX-Retarget'] = '#treatment-list'
    response['HX-Reswap']   = 'innerHTML'
    response['HX-Trigger']  = 'closeModal'
    return response


def _form_ctx(request, form, mode, treatment=None):
    existing_products = []
    existing_contacts = []
    existing_line_items = []
    if form.is_bound:
        selected_pest_ids   = set(form.data.getlist('pests'))
        selected_worker_ids = set(form.data.getlist('executed_by'))
        selected_tag_ids    = set(form.data.getlist('tags'))
        # Preserve the submitted date string as-is so the template can set
        # value="..." on <input type="date"> without going through the date
        # filter (which silently returns '' when given a string, not a date).
        date_str = form.data.get('date', '')
        # Unlike products/contacts, line items ARE re-hydrated on a
        # validation-error re-render — see _parse_line_items_from_querydict.
        existing_line_items = _parse_line_items_from_querydict(form.data)
    elif treatment and treatment.pk:
        selected_pest_ids   = set(str(pk) for pk in treatment.pests.values_list('id', flat=True))
        selected_worker_ids = set(str(pk) for pk in treatment.executed_by.values_list('id', flat=True))
        selected_tag_ids    = set(str(pk) for pk in treatment.tags.values_list('id', flat=True))
        existing_products   = list(treatment.products.select_related('product').order_by('order'))
        existing_contacts   = list(treatment.contacts.order_by('order'))
        existing_line_items = [
            {
                'catalog_item_id': str(li.catalog_item_id) if li.catalog_item_id else '',
                'name':            li.snapshot_name,
                'item_type':       li.snapshot_item_type,
                'has_ncm_link':    li.snapshot_has_ncm_link,
                'quantity':        str(li.quantity),
                'price':           str(li.price) if li.price is not None else '',
            }
            for li in treatment.line_items.all().order_by('order')
        ]
        date_str = treatment.date.isoformat() if treatment.date else timezone.localdate().isoformat()
    else:
        selected_pest_ids   = set()
        selected_worker_ids = set()
        selected_tag_ids    = set()
        date_str = timezone.localdate().isoformat()
    price_catalog = list(
        PriceCatalogItem.objects
        .filter(deleted_at__isnull=True)
        .order_by('item_type', 'name')
        .values('id', 'name', 'item_type', 'non_chemical_mean_id', 'default_price')
    )
    all_ncm = list(
        NonChemicalMean.objects
        .filter(deleted_at__isnull=True)
        .order_by('category', 'name')
        .values('id', 'name')
    )
    return {
        'form':               form,
        'mode':               mode,
        'treatment':          treatment,
        'date_str':           date_str,
        'all_products':       Product.objects.filter(deleted_at__isnull=True).order_by('category', 'name'),
        'existing_products':  existing_products,
        'existing_contacts':  existing_contacts,
        'existing_line_items': existing_line_items,
        'selected_pest_ids':  selected_pest_ids,
        'selected_worker_ids': selected_worker_ids,
        'selected_tag_ids':   selected_tag_ids,
        # Price module (Stage 5) — json_script (used in the template)
        # handles UUID/Decimal via DjangoJSONEncoder, no manual str() needed.
        'price_catalog':      price_catalog,
        'all_ncm':             all_ncm,
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
    # Stage 8a (reworked 2026-06-19): Firm now attaches to Site, not Client
    # — the editor's search is site-first (see editor.html), and picking a
    # site auto-fills the firm panel from that site's active firm link.
    # Clients no longer need firm-based filtering.
    #
    # NOTE: this list intentionally includes INACTIVE sites too (unlike the
    # is_active=True filtering on the standalone Обекти page) — editor.html
    # hides them from the live search dropdown (filteredSites), but an old
    # protocol referencing a site that's since gone inactive must still be
    # able to restore that site's data on edit/view via allSites.find().
    clients = list(
        Client.objects
        .filter(deleted_at__isnull=True)
        .order_by('name')
        .values('id', 'name')
    )
    sites = []
    for s in (
        Site.objects
        .filter(deleted_at__isnull=True)
        .select_related('client')
        .prefetch_related('firm_links__firm')
        .order_by('client__name', 'name')
    ):
        firm = s.active_firm
        sites.append({
            'id': str(s.pk), 'client_id': str(s.client_id),
            'client_name': s.client.name,
            'pseudonym': s.pseudonym, 'name': s.name,
            'address': s.address, 'area_m2': s.area_m2,
            'is_active': s.is_active,
            'firm': firm.name if firm else '',
            'eik': firm.eik if firm else '',
            'firm_address': firm.address if firm else '',
            'phone': firm.phone if firm else '',
        })

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

    # Price module (Stage 4) — the full catalog, for the add-item dropdown
    # and the NCM-selection auto-add hook (see addNCM() in editor.html).
    # json_script (used in the template) handles UUID/Decimal via
    # DjangoJSONEncoder, no manual str() needed here.
    price_catalog = list(
        PriceCatalogItem.objects
        .filter(deleted_at__isnull=True)
        .order_by('item_type', 'name')
        .values('id', 'name', 'item_type', 'non_chemical_mean_id', 'default_price')
    )

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
        'price_catalog':     price_catalog,
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

    # Price module (Stage 4) — line items are always sent (edit AND
    # create-from/use-template flows) since they're not part of the frozen
    # firm/company identity snapshot; a template's line items are a normal
    # starting point the user is expected to edit, same as everything else
    # that gets copied when a protocol is created from a template.
    line_items = [
        {
            'catalog_item_id': str(li.catalog_item_id) if li.catalog_item_id else None,
            'name':            li.snapshot_name,
            'item_type':       li.snapshot_item_type,
            'has_ncm_link':    li.snapshot_has_ncm_link,
            'quantity':        str(li.quantity),
            'price':           str(li.price) if li.price is not None else None,
        }
        for li in protocol.line_items.all().order_by('order')
    ]

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
        'tax_included':         protocol.tax_included,
        'document_status':      protocol.document_status,
        'payment_type':         protocol.payment_type,
        'line_items':           line_items,
        'tag_ids':              [str(t.pk) for t in protocol.tags.all()],
        'source_template_id':  str(protocol.source_template_id) if protocol.source_template_id else None,
        'columns':              columns,
    }
    if include_pk:
        prefill['client_uuid'] = str(protocol.pk)
        # Frozen firm/company identity — only sent when restoring THIS SAME
        # protocol row in place (edit/view). The editor uses these to show
        # what's actually saved/printed instead of silently re-deriving
        # live current data from the site/company catalogs. Deliberately
        # NOT sent when include_pk=False (create-from/use-template/
        # save-as-preset flows) — those are building a brand-new record,
        # which should show live current data since that's what gets frozen
        # into it on first save anyway.
        prefill['snapshot_firm_name']       = protocol.snapshot_firm_name or ''
        prefill['snapshot_firm_eik']        = protocol.snapshot_firm_eik or ''
        prefill['snapshot_firm_address']    = protocol.snapshot_firm_address or ''
        prefill['snapshot_firm_phone']      = protocol.snapshot_firm_phone or ''
        prefill['snapshot_company_name']    = protocol.snapshot_company_name or ''
        prefill['snapshot_company_eik']     = protocol.snapshot_company_eik or ''
        prefill['snapshot_company_address'] = protocol.snapshot_company_address or ''
        prefill['snapshot_company_phone']   = protocol.snapshot_company_phone or ''
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
    """Parse a price-like value into Decimal, or return None if blank/invalid.
    Accepts a comma as the decimal separator (Bulgarian locale) — the editor
    normalizes this on blur client-side, but the server must not depend on
    that alone (e.g. a save triggered without ever blurring the field)."""
    if value in (None, '', 0):
        return None if value in (None, '') else 0
    try:
        return Decimal(str(value).replace(',', '.'))
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
        # Stage 10e-3 — no ModelForm sits in front of this payload, so
        # whitelist-sanitize the rich-HTML notes here, same rules as
        # ClientForm.clean_notes() etc.
        'notes':           sanitize_notes_html(payload.get('notes') or ''),
        # price / price_with_tax are NOT set here — Stage 4 (price module):
        # they're now computed from line_items below, after the protocol
        # row (and thus its pk) exists. tax_included stays user-controlled.
        'tax_included':    bool(payload.get('tax_included', False)),
        'document_status': (
            payload.get('document_status')
            if payload.get('document_status') in DocumentStatus.values
            else DocumentStatus.WITH_DOCUMENT
        ),
        'payment_type': (
            payload.get('payment_type')
            if payload.get('payment_type') in PaymentType.values
            else PaymentType.CASH
        ),
        'is_preset':       bool(is_preset),
        'preset_name':     (preset_name or '')[:255],
        'folder_id':       _safe_uuid(folder_id),
        'source_template_id': _safe_uuid(payload.get('source_template_id')),
        # snapshot_* fields are intentionally NOT listed here. Protocol.save()
        # only fills them in when they're still blank (i.e. on first save),
        # so re-saving an existing protocol never silently overwrites its
        # frozen company/firm data — see refresh_company_snapshot() /
        # refresh_firm_snapshot() and the explicit "⟳ Обнови данни за
        # фирма" action (protocol_refresh_snapshot view) for the deliberate
        # opt-in refresh path.
    }

    protocol, created = Protocol.objects.update_or_create(
        pk=client_uuid, defaults=defaults,
    )

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

    # Line items (Stage 4 — Price module) — snapshots are frozen at insert
    # (same rewrite-from-scratch pattern as ProtocolProduct above). `price`
    # is then computed from these lines and written back onto the protocol
    # row: None when there are no lines at all (nothing entered yet), else
    # the sum of qty*price across lines that actually have a price (a blank
    # line contributes nothing to the sum, same as the editor's live total).
    protocol.line_items.all().delete()
    line_items_payload = payload.get('line_items') or []
    net_total = None
    if line_items_payload:
        net_total = Decimal('0')
        for i, li in enumerate(line_items_payload):
            catalog_id = _safe_uuid(li.get('catalog_item_id'))
            catalog_item = (
                PriceCatalogItem.objects.filter(pk=catalog_id).first()
                if catalog_id else None
            )
            quantity = _safe_decimal(li.get('quantity'))
            if quantity is None:
                quantity = Decimal('0')
            price = _safe_decimal(li.get('price'))
            name = (
                li.get('name')
                or (catalog_item.name if catalog_item else '')
            )[:255]
            item_type = (
                li.get('item_type')
                or (catalog_item.item_type if catalog_item else PriceCatalogItem.ItemType.SERVICE)
            )
            ProtocolLineItem.objects.create(
                protocol=protocol,
                catalog_item=catalog_item,
                quantity=quantity,
                price=price,
                order=i,
                snapshot_name=name,
                snapshot_item_type=item_type,
                snapshot_has_ncm_link=bool(li.get('has_ncm_link')),
            )
            if price is not None:
                net_total += quantity * price

    protocol.price = net_total
    if protocol.tax_included and net_total is not None:
        # tax_rate_snapshot was already frozen (or re-confirmed) by the
        # update_or_create() save above, via _normalize_tax_fields() — use
        # THAT frozen rate, not the live AppSettings value, so re-saving an
        # old protocol never silently re-prices it at today's VAT rate.
        vat_percent = protocol.tax_rate_snapshot
        if vat_percent is None:  # defensive — should never happen once tax_included is True
            vat_percent = AppSettings.get().vat_percent
        protocol.price_with_tax = (net_total * (1 + vat_percent / 100)).quantize(Decimal('0.01'))
    else:
        protocol.price_with_tax = None
    # Protocol.save() re-runs _normalize_tax_fields() (freezes/clears
    # tax_rate_snapshot) — safe to call again here, same as every other
    # save() call in this codebase.
    protocol.save()

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

    site_firm = site_o.active_firm if site_o else None
    return SimpleNamespace(
        company=company or SimpleNamespace(slogan=''),
        snapshot_company_name=(company.name if company else ''),
        snapshot_company_eik=(company.eik if company else ''),
        snapshot_company_address=(company.address if company else ''),
        snapshot_company_phone=(company.phone if company else ''),
        client=client_o or SimpleNamespace(name=''),
        # Stage 8a (reworked) — preview has no saved Protocol row to
        # snapshot, so this mirrors what Protocol.refresh_firm_snapshot()
        # would freeze right now, computed live from the chosen site's
        # active Firm link.
        snapshot_firm_name=(site_firm.name if site_firm else ''),
        snapshot_firm_eik=(site_firm.eik if site_firm else ''),
        snapshot_firm_address=(site_firm.address if site_firm else ''),
        snapshot_firm_phone=(site_firm.phone if site_firm else ''),
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
        pk=pk,
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


@require_POST
def protocol_refresh_snapshot(request, pk):
    """Explicit, opt-in refresh of a protocol's frozen company/firm data.

    Protocol.save() only fills snapshot_* fields when they're blank, so a
    saved protocol's snapshot never drifts on its own. This is the deliberate
    escape hatch: pull the company's / site's-active-firm's CURRENT text
    identity into the snapshot, overwriting whatever was frozen before.
    """
    protocol = get_object_or_404(Protocol, pk=pk, deleted_at__isnull=True)
    protocol.refresh_company_snapshot()
    protocol.refresh_firm_snapshot()
    protocol.save(update_fields=[
        'snapshot_company_name', 'snapshot_company_eik',
        'snapshot_company_address', 'snapshot_company_phone',
        'snapshot_firm_name', 'snapshot_firm_eik',
        'snapshot_firm_address', 'snapshot_firm_phone',
    ])
    return JsonResponse({'ok': True})


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
    back_url = ''
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
        back_url = request.POST.get('back_url', '')

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
        'back_url': back_url,
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
# Return to editor from preview (POST — payload round-trip)
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
def protocol_return_to_editor(request):
    """POST from the preview page's '← Към редактиране' button.

    The preview page embeds the full editor payload in a hidden form and
    submits it here, so the editor re-opens pre-filled with exactly what
    the user was working on.  No session, no localStorage — data lives only
    in the HTTP round-trip.

    back_url is forwarded so the editor's own 'Отказ' button still works.
    """
    try:
        payload = json.loads(request.POST.get('payload', '') or '{}')
    except (ValueError, TypeError):
        payload = {}
    back_url = request.POST.get('back_url', '')
    bootstrap = _build_editor_bootstrap()
    bootstrap['prefill'] = payload
    return render(request, 'protocols/editor.html', {
        'active_nav':     'protokoli',
        'editor_mode':    'create',
        'bootstrap_json': json.dumps(bootstrap, ensure_ascii=False, default=str),
        'back_url':       back_url,
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

    # Only an explicit "save_as_template" click may turn a record INTO a
    # template. Any other action (plain Save / Print / Download) rewrites
    # the existing record in place and must carry forward whatever
    # is_preset/preset_name/folder it already had — otherwise editing an
    # existing template via the normal "Запази протокола" button silently
    # demoted it back to a regular protocol, which made it vanish from
    # Шаблони.
    is_preset = action == 'save_as_template'
    existing = None
    if not is_preset:
        existing_uuid = _safe_uuid(payload.get('client_uuid'))
        if existing_uuid:
            existing = Protocol.objects.filter(pk=existing_uuid).first()

    if is_preset:
        preset_name = (payload.get('preset_name') or '')
        folder_id   = payload.get('folder_id')
    elif existing is not None:
        is_preset    = existing.is_preset
        preset_name  = existing.preset_name
        folder_id    = existing.folder_id
    else:
        preset_name = ''
        folder_id   = None

    if action == 'save_as_template':
        # Templates must be a separate DB record from the editor draft.
        # Stripping client_uuid forces _save_or_rewrite_protocol to generate
        # a fresh UUID4, so a subsequent "Запази протокола" click on the same
        # preview page cannot overwrite (and erase) the saved template.
        payload = {k: v for k, v in payload.items() if k != 'client_uuid'}

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
        'active_nav': 'lichni_danni',
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
# Ценообразуване — price catalog (Price module, Stage 3)
# ─────────────────────────────────────────────────────────────────────────────

def _price_catalog_qs():
    return (
        PriceCatalogItem.objects
        .filter(deleted_at__isnull=True)
        .select_related('non_chemical_mean')
        .order_by('item_type', 'name')
    )


def price_catalog_list(request):
    return render(request, 'price_catalog/list.html', {
        'active_nav': 'cenoobrazuvane',
        'items': _price_catalog_qs(),
    })


def price_catalog_list_body(request):
    return render(request, 'price_catalog/_list_body.html', {'items': _price_catalog_qs()})


def price_catalog_create(request):
    if request.method == 'POST':
        form = PriceCatalogItemForm(request.POST)
        if form.is_valid():
            form.save()
            r = HttpResponse(status=204)
            r['HX-Trigger'] = 'priceCatalogChanged'
            return r
    else:
        form = PriceCatalogItemForm()
    return render(request, 'price_catalog/_form.html', {'form': form, 'item': None})


def price_catalog_edit(request, pk):
    item = get_object_or_404(PriceCatalogItem, pk=pk, deleted_at__isnull=True)
    if request.method == 'POST':
        form = PriceCatalogItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            r = HttpResponse(status=204)
            r['HX-Trigger'] = 'priceCatalogChanged'
            return r
    else:
        form = PriceCatalogItemForm(instance=item)
    return render(request, 'price_catalog/_form.html', {'form': form, 'item': item})


def price_catalog_create_inline(request):
    """Lightweight JSON endpoint for inline catalog-item creation from the
    protocol/one-time-treatment editors' '+ Нов елемент' form — same
    pattern as tag_create_inline()."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    form = PriceCatalogItemForm(request.POST)
    if form.is_valid():
        item = form.save()
        return JsonResponse({
            'id': str(item.pk),
            'name': item.name,
            'item_type': item.item_type,
            'non_chemical_mean_id': str(item.non_chemical_mean_id) if item.non_chemical_mean_id else None,
            'default_price': str(item.default_price) if item.default_price is not None else None,
        })
    return JsonResponse({'errors': form.errors}, status=400)


@require_http_methods(['DELETE'])
def price_catalog_delete(request, pk):
    """A genuine hard delete (per design decision) — not a soft delete like
    most other reference-data rows. Line items referencing this item keep
    their frozen snapshot_name/snapshot_item_type and just lose the FK
    (SET_NULL), so no historical protocol/treatment display breaks."""
    item = get_object_or_404(PriceCatalogItem, pk=pk)
    item.delete()
    return render(request, 'price_catalog/_list_body.html', {'items': _price_catalog_qs()})


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

    update_fields = ['theme', 'default_protocol_format']
    vat_raw = request.POST.get('vat_percent')
    if vat_raw is not None:
        from decimal import Decimal, InvalidOperation
        try:
            vat_val = Decimal(vat_raw.strip().replace(',', '.'))
            if 0 <= vat_val <= 100:
                settings.vat_percent = vat_val
                update_fields.append('vat_percent')
        except (InvalidOperation, ValueError, AttributeError):
            pass

    settings.save(update_fields=update_fields)
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
# Шаблони — Folder CRUD
# ─────────────────────────────────────────────────────────────────────────────

def _soft_delete_folder_tree(folder, ts):
    """Recursively soft-delete a folder, all its sub-folders, and its templates."""
    Protocol.objects.filter(
        is_preset=True, folder=folder, deleted_at__isnull=True
    ).update(deleted_at=ts)
    for child in TemplateFolder.objects.filter(parent=folder, deleted_at__isnull=True):
        _soft_delete_folder_tree(child, ts)
    folder.deleted_at = ts
    folder.save(update_fields=['deleted_at'])


def _restore_folder_tree(folder, move_to_root=False):
    """Recursively restore a soft-deleted folder and all its contents.
    If move_to_root is True the folder's parent FK is cleared first."""
    if move_to_root:
        folder.parent = None
    folder.deleted_at = None
    folder.save(update_fields=['deleted_at', 'parent'])
    Protocol.objects.filter(
        is_preset=True, folder=folder, deleted_at__isnull=False
    ).update(deleted_at=None)
    for child in TemplateFolder.objects.filter(parent=folder, deleted_at__isnull=False):
        _restore_folder_tree(child)


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
        folder = TemplateFolder.objects.create(name=name, parent=parent)
        # JSON body (id/name/parent_id) so callers that need the new folder's
        # PK right away (e.g. the protocol editor's inline "+ Нова папка")
        # don't have to re-fetch the folder list. The older HTMX-driven
        # caller (_folder_form.html) only checks `r.ok`, so this stays
        # backwards compatible with it.
        r = JsonResponse({
            'ok': True,
            'id': str(folder.pk),
            'name': folder.name,
            'parent_id': str(folder.parent_id) if folder.parent_id else None,
        })
        r['HX-Trigger'] = 'foldersChanged'
        return r
    # Preselect the folder the user was browsing when they clicked "Нова
    # папка" (passed as ?parent_id=... from template_folders/list.html),
    # instead of always defaulting to root — still changeable via the
    # picker in the form itself.
    initial_parent = None
    initial_parent_id = request.GET.get('parent_id')
    if initial_parent_id:
        initial_parent = TemplateFolder.objects.filter(
            pk=initial_parent_id, deleted_at__isnull=True,
        ).first()
    return render(request, 'template_folders/_folder_form.html', {
        'folder': None,
        'initial_parent': initial_parent,
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
    _soft_delete_folder_tree(folder, timezone.now())
    r = HttpResponse(status=204)
    r['HX-Trigger'] = 'foldersChanged'
    return r


@require_http_methods(['POST'])
def folder_restore(request, pk):
    folder = get_object_or_404(TemplateFolder, pk=pk, deleted_at__isnull=False)
    # If the parent is also deleted, move this folder to root on restore
    move_to_root = bool(
        folder.parent_id and
        TemplateFolder.objects.filter(pk=folder.parent_id, deleted_at__isnull=False).exists()
    )
    _restore_folder_tree(folder, move_to_root=move_to_root)
    r = HttpResponse(status=204)
    r['HX-Trigger'] = 'foldersChanged'
    return r


@require_http_methods(['POST'])
def template_restore(request, pk):
    tpl = get_object_or_404(Protocol, pk=pk, is_preset=True, deleted_at__isnull=False)
    # If the folder it was in is also deleted, move template to root
    if tpl.folder_id and TemplateFolder.objects.filter(pk=tpl.folder_id, deleted_at__isnull=False).exists():
        tpl.folder = None
    tpl.deleted_at = None
    tpl.save(update_fields=['deleted_at', 'folder'])
    r = HttpResponse(status=204)
    r['HX-Trigger'] = 'templatesChanged'
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
    back_url = (
        reverse('core:template_folder', kwargs={'folder_id': str(source.folder_id)})
        if source.folder_id else reverse('core:template_list')
    )
    return render(request, 'protocols/editor.html', {
        'active_nav':     'shabloni',
        'editor_mode':    'create_from',
        'bootstrap_json': json.dumps(bootstrap, ensure_ascii=False, default=str),
        'back_url':       back_url,
    })


def template_edit_view(request, pk):
    """Open the template in the editor for in-place editing."""
    template = get_object_or_404(Protocol, pk=pk, is_preset=True, deleted_at__isnull=True)
    bootstrap = _build_editor_bootstrap()
    bootstrap['prefill'] = _build_prefill_from_protocol(template, include_pk=True)
    back_url = (
        reverse('core:template_folder', kwargs={'folder_id': str(template.folder_id)})
        if template.folder_id else reverse('core:template_list')
    )
    return render(request, 'protocols/editor.html', {
        'active_nav':     'shabloni',
        'editor_mode':    'edit',
        'protocol_pk':    str(template.pk),
        'is_template':    True,
        'bootstrap_json': json.dumps(bootstrap, ensure_ascii=False, default=str),
        'back_url':       back_url,
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