"""Template tags to render globally-enabled optional fields on detail pages."""

from __future__ import annotations

from django import template

from testcanvas.utilities.optional_fields import (
    get_optional_field_specs,
    get_visible_optional_field_names,
)

register = template.Library()


@register.inclusion_tag("testcanvas/slots/_optional_fields.html")
def render_optional_fields(obj) -> dict:
    """Render the optional fields enabled globally.

    Reads which optional fields are visible globally and builds label/value rows
    using the human-readable choice display when available. Hidden fields produce
    no rows, so the slot renders nothing.

    Args:
        obj: A core instance (typically a ``TestCase``).

    Returns:
        A context dict with ``rows``: a list of ``{"label", "value"}`` dicts.
    """
    model_name = obj.__class__.__name__
    names = get_visible_optional_field_names(model_name)
    specs = {spec.name: spec for spec in get_optional_field_specs(model_name)}

    rows = []
    for name in names:
        # Prefer the human-readable label for choice fields.
        display_getter = getattr(obj, f"get_{name}_display", None)
        value = display_getter() if callable(display_getter) else getattr(obj, name)
        rows.append({"label": specs[name].label, "value": value})

    return {"rows": rows}

