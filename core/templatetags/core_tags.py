from datetime import date as _date

from django import template
from django.utils.safestring import mark_safe

from core.notes_html import (
    sanitize_notes_html,
    truncate_notes_html,
    plain_text_from_notes_html,
)

register = template.Library()


# ── Stage 10e: minimal-HTML rich notes ─────────────────────────────────────
@register.filter
def richtruncate(value, length=60):
    """
    Truncate stored minimal-HTML notes (<b>/<i>/<u>/<br> only) to `length`
    visible characters, closing any open tag and appending an ellipsis.
    Marked safe: re-sanitizes defensively before truncating, so the output
    is guaranteed to only ever contain the whitelisted tags.
    Use with |safe is NOT needed — this filter already returns safe markup.
    """
    if not value:
        return ''
    try:
        length = int(length)
    except (TypeError, ValueError):
        length = 60
    clean = sanitize_notes_html(value)
    return mark_safe(truncate_notes_html(clean, length))


@register.filter
def notes_safe(value):
    """Mark a stored (already-sanitized) notes value safe for rendering.
    Re-sanitizes defensively, so this is safe to use even if the stored
    value somehow predates the sanitizer."""
    if not value:
        return ''
    return mark_safe(sanitize_notes_html(value))


@register.filter
def plaintext_notes(value):
    """Plain, unescaped text from a notes HTML value — for contexts that
    can't render markup (e.g. a title="" tooltip attribute). Do NOT mark
    safe: let the template engine's normal auto-escaping handle it."""
    return plain_text_from_notes_html(value)

# ── Bulgarian month abbreviations ──────────────────────────────────────────
_MONTHS_BG = {
    1: 'ЯНУ', 2: 'ФЕВ', 3:  'МАР', 4:  'АПР',
    5: 'МАЙ', 6: 'ЮНИ', 7:  'ЮЛИ', 8:  'АВГ',
    9: 'СЕП', 10: 'ОКТ', 11: 'НОЕ', 12: 'ДЕК',
}


@register.filter
def month_abbr_bg(date_value):
    """Return 3-letter Bulgarian month abbreviation (uppercase) for a date."""
    if not date_value:
        return ''
    return _MONTHS_BG.get(date_value.month, '')


# ── Protocol service → pest pill CSS class ────────────────────────────────
_SERVICE_CSS = {
    'disinsection': 'pest-di',
    'deratization': 'pest-dr',
    'disinfection':  'pest-dn',
}


@register.filter
def service_css(service):
    """Map a service code to its pest pill CSS class."""
    return _SERVICE_CSS.get(service, 'pest-di')


# ── Tag colour → inline style ─────────────────────────────────────────────
@register.filter
def tag_style(color):
    """
    Given a hex colour string (e.g. '#3B82F6'), return an inline style string
    that produces a lightly tinted pill — same visual language as the mockup.
    Falls back to the muted palette colour if the value is missing or malformed.
    """
    if not color or len(color.lstrip('#')) != 6:
        color = '#aa767c'
    hex_val = color.lstrip('#')
    try:
        r, g, b = int(hex_val[0:2], 16), int(hex_val[2:4], 16), int(hex_val[4:6], 16)
    except ValueError:
        r, g, b = 170, 118, 124
    return (
        f"background:rgba({r},{g},{b},.12);"
        f"color:{color};"
        f"border:1px solid rgba({r},{g},{b},.3);"
    )

@register.filter
def split(value, arg):
    return value.split(arg)


# ── Pest / service category → Bulgarian label ─────────────────────────────
_CATEGORY_BG = {
    'disinsection': 'Дезинсекция',
    'deratization': 'Дератизация',
    'disinfection':  'Дезинфекция',
}


@register.filter
def category_bg(value):
    """Map a service/category code to its Bulgarian display name."""
    return _CATEGORY_BG.get(value, value)


# ── Month+year date picker (2026-06-21) ────────────────────────────────────
# Replaces <input type="month"> everywhere — native support for that input
# type is inconsistent (notably in WebKit-based webviews used by the
# packaged desktop app), so a value typed into a non-functioning native
# picker could silently fail the strict server-side "%Y-%m" validation,
# making the whole form look like it just "reset" with no clear reason.
# Two plain <select> elements work identically everywhere. Pair with
# core.views._merge_month_year() in the view to recombine the two posted
# values ("<field>_month" / "<field>_year") into a single "YYYY-MM" string
# before handing it to the Django form.
_MONTHS_FULL_BG = {
    1: 'Януари', 2: 'Февруари', 3: 'Март', 4: 'Април',
    5: 'Май', 6: 'Юни', 7: 'Юли', 8: 'Август',
    9: 'Септември', 10: 'Октомври', 11: 'Ноември', 12: 'Декември',
}


@register.inclusion_tag('core/_month_year_select.html')
def month_year_select(field_name, value=None, default_today=True, years_back=5, years_forward=2):
    """`value` is a date (or None). When `value` is None and `default_today`
    is True, defaults to the current month — matching the "defaults to
    creation month, editable" rule agreed for Firm/Site *start* dates. Pass
    `default_today=False` for fields like end_date that should start blank
    until the user actively sets them."""
    today = _date.today()
    # `value` can be a non-date (e.g. a raw invalid string) when re-rendering
    # a form that failed validation — fall through to the default in that case
    # rather than erroring on .month/.year.
    if value is not None and not hasattr(value, 'month'):
        value = None
    if value:
        sel_month, sel_year = value.month, value.year
    elif default_today:
        sel_month, sel_year = today.month, today.year
    else:
        sel_month, sel_year = None, None
    current_year = today.year
    years = list(range(current_year + years_forward, current_year - years_back - 1, -1))
    months = [(i, _MONTHS_FULL_BG[i]) for i in range(1, 13)]
    return {
        'field_name': field_name,
        'months': months,
        'years': years,
        'sel_month': sel_month,
        'sel_year': sel_year,
    }


@register.inclusion_tag('core/_date_select.html')
def date_select(field_name, value=None, years_back=5, years_forward=2):
    """Render day/month/year <select> elements for a date field.

    `value` can be a datetime.date object, an ISO string 'YYYY-MM-DD', or None.
    None defaults to today's date (same behaviour as the date model default).
    Pair with core.views._merge_date_select() to recombine the three posted
    values ('<field>_day' / '<field>_month' / '<field>_year') into a single
    'YYYY-MM-DD' string before passing to the Django form — same pattern as
    month_year_select / _merge_month_year."""
    import datetime as _dt
    today = _date.today()
    sel_day = sel_month = sel_year = None

    if value is not None:
        if hasattr(value, 'day'):
            sel_day, sel_month, sel_year = value.day, value.month, value.year
        elif isinstance(value, str) and len(value) == 10 and value[4] == '-':
            try:
                d = _dt.date.fromisoformat(value)
                sel_day, sel_month, sel_year = d.day, d.month, d.year
            except ValueError:
                pass

    if sel_day is None:
        sel_day, sel_month, sel_year = today.day, today.month, today.year

    current_year = today.year
    years = list(range(current_year + years_forward, current_year - years_back - 1, -1))
    months = [(i, _MONTHS_FULL_BG[i]) for i in range(1, 13)]
    days = list(range(1, 32))
    return {
        'field_name': field_name,
        'days': days,
        'months': months,
        'years': years,
        'sel_day': sel_day,
        'sel_month': sel_month,
        'sel_year': sel_year,
    }