from django import template

register = template.Library()

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