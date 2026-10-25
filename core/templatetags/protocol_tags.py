from django import template
from django.utils.html import format_html_join
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def dedup_snapshots(col, field_name):
    """Numbered, de-duplicated snapshot text for one column.

    If every product in the column shares the same value, show it once
    (no numbering). If they differ, number each distinct value.
    `field_name` is the snapshot attribute, e.g. "snapshot_safety_instructions".
    """
    if not col or not hasattr(col, "protocol_products"):
        return ""

    seen = []
    for pp in col.protocol_products.all():
        value = (getattr(pp, field_name, "") or "").strip()
        if value and value not in seen:
            seen.append(value)

    if not seen:
        return ""
    if len(seen) == 1:
        return seen[0]                     # one shared value → no numbering

    return format_html_join(
        mark_safe("<br>"),
        "{}. {}",
        ((i, text) for i, text in enumerate(seen, start=1)),
    )


@register.filter
def ncm_count(col, ncm):
    counts = getattr(col, "ncm_counts", None) or {}
    return counts.get(str(getattr(ncm, "pk", ncm)), "")
