"""Plugin extension points for enriching core objects with UI widgets.

This module is the core's side of a one-way extension contract: installed
Django apps (plugins) may contribute small, ordered pieces of UI — **widgets** —
attached to a specific core object such as an ``ApplicationMap``, ``FlowNode``,
``UserStory`` or ``AcceptanceCriterion``.

The mechanism mirrors the navbar collector in
``testcanvas.context_processors``: the core iterates over every installed
``AppConfig`` and, if it declares the expected hook method, asks it for its
contributions. The core never imports a plugin, so a plugin can be installed or
removed by editing ``INSTALLED_APPS`` alone.

Contract summary:
    A plugin declares, on its ``AppConfig``, this optional method::

        def get_object_widgets(self, object_type, obj, request) -> list[dict]:
            ...

    ``object_type`` is one of :data:`OBJECT_TYPES`. ``obj`` is the concrete core
    instance being rendered. The method returns a list of plain widget
    dictionaries (never HTML). Each dict carries a ``type`` key (one of
    :data:`WIDGET_TYPES`) plus the fields that type expects. **Widgets are
    rendered in list order**, so a plugin controls the layout by ordering them.

Why typed widgets instead of raw HTML:
    A plugin declares *what* to show (structured data); the core decides *how*
    to render it. This keeps URL reversing, permission checks, HTML escaping and
    Bootstrap styling in the core, exactly where the project rules want them. A
    plugin that needs full markup freedom uses Django's native per-path template
    override instead (a separate, complementary mechanism).

Design rules:
    * Providers that raise are skipped, so a faulty plugin can never break the
      core render.
    * Unknown widget types are skipped, so a plugin can never inject markup the
      core does not understand.
    * Plugins should reference core objects through their stable ``*_uid`` when
      they persist data, keeping them decoupled from the core primary keys.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.urls import NoReverseMatch, reverse


# Canonical set of object families a plugin can attach to. Kept here so the
# core views and the plugins agree on the exact same vocabulary.
OBJECT_TYPES = (
    "application_map",
    "flow_node",
    "user_story",
    "acceptance_criterion",
)


def collect_object_widgets(object_type: str, obj: Any, request) -> list[dict[str, Any]]:
    """Collect ordered UI widgets declared by installed plugins.

    Iterates over every installed ``AppConfig`` and, when it exposes a
    ``get_object_widgets(object_type, obj, request)`` method, asks it for the
    widgets it wants to show on ``obj``. Each raw widget is dispatched by its
    ``type`` to the matching normaliser (which reverses URLs, enforces
    permissions and fills styling defaults) and paired with the core partial
    that renders it.

    The relative order of widgets is preserved: widgets from earlier-installed
    apps come first, and within one plugin they keep the order of the returned
    list. This lets a plugin lay out its own section (e.g. a progress bar, a
    divider, then a button) simply by ordering the list.

    Args:
        object_type: The object family, one of :data:`OBJECT_TYPES`.
        obj: The concrete core instance being rendered.
        request: The current HTTP request (used for permission checks).

    Returns:
        A list of render-ready widgets, each a dict with ``template`` (the core
        partial to include) and ``data`` (the normalised widget payload).
    """
    widgets: list[dict[str, Any]] = []
    for config in apps.get_app_configs():
        getter = getattr(config, "get_object_widgets", None)
        if not callable(getter):
            continue
        try:
            raw_items = getter(object_type, obj, request) or []
        except Exception:
            # A broken provider contributes nothing; the core keeps rendering.
            continue
        for item in raw_items:
            widget = _normalize_widget(item=item, request=request)
            if widget is not None:
                widgets.append(widget)
    return widgets


def _normalize_widget(item: dict[str, Any], request) -> dict[str, Any] | None:
    """Dispatch a raw widget to its typed normaliser.

    Looks up ``item["type"]`` in :data:`WIDGET_TYPES` and, when known, runs the
    matching normaliser. The result is wrapped together with the core partial
    that renders that widget type.

    Args:
        item: The raw widget dictionary from a plugin. Must carry a ``type``
            key among :data:`WIDGET_TYPES`.
        request: The current HTTP request, forwarded to normalisers that need it
            (e.g. the button permission check).

    Returns:
        A dict ``{"template": ..., "data": ...}`` ready to render, or ``None``
        when the type is unknown or the normaliser rejected the payload.
    """
    spec = WIDGET_TYPES.get(item.get("type"))
    if spec is None:
        # Unknown widget type: skip instead of guessing how to render it.
        return None

    data = spec["normalize"](item=item, request=request)
    if data is None:
        return None

    return {"template": spec["template"], "data": data}


# --------------------------------------------------------------------------- #
# Widget normalisers
#
# Each normaliser validates one raw widget dict and returns a template-ready
# ``data`` dict (or ``None`` to skip it). They never emit HTML: the paired
# partial under ``templates/testcanvas/slots/widgets/`` does the rendering with
# Bootstrap classes, so escaping and styling stay in the core.
# --------------------------------------------------------------------------- #

# Bootstrap contextual tokens a plugin may pass through ``class_type``. The core
# composes the final class (e.g. ``btn-{token}``) so a plugin can only pick a
# known, safe Bootstrap variant and never inject an arbitrary class string.
BOOTSTRAP_CONTEXTS = (
    "primary",
    "secondary",
    "success",
    "danger",
    "warning",
    "info",
    "light",
    "dark",
    "muted",  # valid for text-* utilities only
)


def _clean_context(value: Any, default: str) -> str:
    """Return a safe Bootstrap contextual token or a fallback.

    Args:
        value: The raw ``class_type`` supplied by the plugin.
        default: The token to use when ``value`` is missing or not allowed.

    Returns:
        A whitelisted Bootstrap contextual token (never arbitrary CSS).
    """
    token = str(value or "").strip()
    return token if token in BOOTSTRAP_CONTEXTS else default


def _normalize_progress(item: dict[str, Any], request) -> dict[str, Any] | None:
    """Validate a progress-bar widget (a bar with an optional comment).

    Args:
        item: Raw widget dict. Keys: ``value`` (required, current amount);
            optional ``max`` (defaults to ``100``), ``label`` (the comment shown
            above the bar), ``class_type`` (Bootstrap context for the bar fill,
            defaults to ``primary``), ``show_value`` (print the percentage
            inside the bar, defaults ``True``) and ``title`` (tooltip).
        request: Unused; kept for a uniform normaliser signature.

    Returns:
        A data dict with ``label``, ``pct``, ``context``, ``show_value`` and
        ``title``, or ``None`` when ``value`` is not a usable number.
    """
    try:
        value = float(item.get("value"))
        maximum = float(item.get("max", 100))
    except (TypeError, ValueError):
        return None
    if maximum <= 0:
        return None

    # Clamp to the 0..100 range so a stray value can never overflow the bar.
    pct = max(0, min(100, round(value * 100 / maximum)))

    return {
        "label": item.get("label", ""),
        "pct": pct,
        "context": _clean_context(item.get("class_type"), "primary"),
        "show_value": bool(item.get("show_value", True)),
        "title": item.get("title", ""),
    }


def _normalize_text(item: dict[str, Any], request) -> dict[str, Any] | None:
    """Validate a text widget (a short caption or note).

    Args:
        item: Raw widget dict. Keys: ``text`` (required); optional ``icon``,
            ``class_type`` (Bootstrap text context, defaults to ``muted``) and
            ``strong`` (render bold, defaults ``False``).
        request: Unused; kept for a uniform normaliser signature.

    Returns:
        A data dict with ``text``, ``icon``, ``context`` and ``strong``, or
        ``None`` when there is no text to show.
    """
    text = item.get("text", "")
    if not text:
        return None

    return {
        "text": text,
        "icon": item.get("icon", ""),
        "context": _clean_context(item.get("class_type"), "muted"),
        "strong": bool(item.get("strong", False)),
    }


def _normalize_divider(item: dict[str, Any], request) -> dict[str, Any]:
    """Validate a divider widget (a separator line, optionally labelled).

    A divider never has a required field, so it is always accepted; it is the
    simplest way for a plugin to group its widgets into tidy sections.

    Args:
        item: Raw widget dict. Optional key: ``label`` (a caption shown centered
            on the separator).
        request: Unused; kept for a uniform normaliser signature.

    Returns:
        A data dict with ``label``.
    """
    return {"label": item.get("label", "")}


def _normalize_button(item: dict[str, Any], request) -> dict[str, Any] | None:
    """Validate a button widget (an action link styled as a Bootstrap button).

    The core reverses the URL server-side, so templates never build URLs, and
    enforces an optional Django permission before the button is shown.

    Args:
        item: Raw widget dict. Keys: ``label`` and ``url_name`` (required);
            optional ``args``, ``kwargs``, ``icon``, ``class_type`` (Bootstrap
            button context, defaults to ``secondary``), ``htmx`` (render as an
            ``hx-get`` link), ``target`` (``hx-target`` selector) and
            ``permission`` (Django permission required to see the button).
        request: The current HTTP request, used to enforce ``permission``.

    Returns:
        A data dict with ``label``, ``url``, ``icon``, ``context``, ``htmx`` and
        ``target``, or ``None`` when the permission check fails or the URL name
        is missing/unreversible.
    """
    permission = item.get("permission")
    if permission and not request.user.has_perm(permission):
        return None

    url_name = item.get("url_name", "")
    if not url_name:
        return None

    try:
        url = reverse(url_name, args=item.get("args", []), kwargs=item.get("kwargs"))
    except NoReverseMatch:
        # Defensive: keep the slot robust if a plugin route is missing/renamed.
        return None

    return {
        "label": item.get("label", ""),
        "url": url,
        "icon": item.get("icon", ""),
        "context": _clean_context(item.get("class_type"), "secondary"),
        "htmx": bool(item.get("htmx", False)),
        "target": item.get("target", ""),
    }


# Registry mapping each widget ``type`` to its normaliser and the core partial
# that renders it. Adding a new widget type is a two-step change: add an entry
# here and ship the matching partial. Plugins never touch this table.
WIDGET_TYPES: dict[str, dict[str, Any]] = {
    "progress": {
        "normalize": _normalize_progress,
        "template": "testcanvas/slots/widgets/_progress.html",
    },
    "text": {
        "normalize": _normalize_text,
        "template": "testcanvas/slots/widgets/_text.html",
    },
    "divider": {
        "normalize": _normalize_divider,
        "template": "testcanvas/slots/widgets/_divider.html",
    },
    "button": {
        "normalize": _normalize_button,
        "template": "testcanvas/slots/widgets/_button.html",
    },
}

