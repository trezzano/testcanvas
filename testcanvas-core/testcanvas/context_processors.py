"""Template context processors for the TestCanvas app."""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.conf import settings
from django.urls import NoReverseMatch, reverse


# Session key under which the user's preferred traceability view is stored.
TRACEABILITY_SESSION_KEY = "traceability_view"

# Allowed traceability modes and the URL name each one resolves to. Centralised
# here so both the view (that writes the session) and this processor (that reads
# it) agree on the exact same set of values.
TRACEABILITY_URL_NAMES = {
    "graph": "testcanvas:flow_node_traceability",
    "matrix": "testcanvas:flow_node_traceability_matrix",
}

# Default view used until the user explicitly picks one.
DEFAULT_TRACEABILITY_MODE = "graph"


def app_context(request):
    """Build the full shared template context for TestCanvas pages.

    This function is the single entry point registered in Django settings. It
    composes the app-wide context by merging the outputs of focused context
    processors in a deterministic order.

    Args:
        request: The incoming HTTP request.

    Returns:
        A merged context dictionary for shared templates.
    """
    context: dict[str, Any] = {}
    context.update(traceability_view(request))
    context.update(branding_settings(request))
    context.update(plugin_flags(request))
    context.update(plugin_navbar(request))
    return context


def traceability_view(request):
    """Expose the preferred traceability view URL name to every template.

    The choice (``"graph"`` or ``"matrix"``) lives in the session so that every
    "Back to traceability" link and node entry point resolves to the same view
    until the user changes it. Templates use ``traceability_url_name`` as the
    target of ``{% url %}``. The choice is written by ``set_traceability_view``.

    Args:
        request: The incoming HTTP request.

    Returns:
        A context dict with ``traceability_url_name`` (the URL name to reverse
        for the currently preferred view).
    """
    # ``request.session`` is always present thanks to SessionMiddleware, but we
    # guard with getattr to stay safe in edge cases (e.g. bare test requests).
    session = getattr(request, "session", None)
    mode = DEFAULT_TRACEABILITY_MODE
    if session is not None:
        mode = session.get(TRACEABILITY_SESSION_KEY, DEFAULT_TRACEABILITY_MODE)

    return {
        "traceability_url_name": TRACEABILITY_URL_NAMES.get(
            mode, TRACEABILITY_URL_NAMES[DEFAULT_TRACEABILITY_MODE]
        ),
    }


def plugin_flags(request) -> dict[str, set[str]]:
    """Expose which apps are installed so templates can guard plugin slots.

    Some core templates may want to show or hide a section depending on whether
    an optional plugin is installed (for example a plugin-provided sidebar).
    Exposing the raw set of installed app labels keeps the core plugin-agnostic:
    it never hardcodes a specific plugin name, while templates can still guard
    with ``{% if "testcanvas_test_execution" in installed_app_labels %}``.

    Args:
        request: The incoming HTTP request.

    Returns:
        A context dict with ``installed_app_labels`` (the set of app labels).
    """
    return {"installed_app_labels": {config.label for config in apps.get_app_configs()}}




def plugin_navbar(request) -> dict:
    """Collect navbar links declared by every installed app.

    Scans each ``AppConfig`` for a ``nav_items`` list or a
    ``get_nav_items(request)`` method, resolves each ``url_name`` defensively,
    computes the active state from the current URL namespace, and returns the
    sorted list under ``nav_links``. Running on every render, it stays cheap:
    it only calls ``reverse()`` on a handful of declared links.

    Args:
        request: The incoming HTTP request.

    Returns:
        A context dict with ``nav_links``: a list of
        ``{"label", "url", "icon", "active"}`` dicts ready for the template.
    """
    # The navbar is only shown to authenticated users, so skip the work otherwise.
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"nav_links": []}

    # Current namespace (e.g. "stats") used to highlight the active section.
    match = getattr(request, "resolver_match", None)
    current_namespace = match.namespace if match else ""

    app_order_map = getattr(settings, "NAVBAR_APP_ORDER", {}) or {}

    links: list[dict] = []
    for config in apps.get_app_configs():
        app_label = getattr(config, "label", "") or getattr(config, "name", "")
        raw_items = _items_for_config(config, request)
        for item in raw_items:
            link = _normalize_item(item, app_label, request)
            if link is not None:  # None => unresolved URL or missing permission
                configured_order = app_order_map.get(app_label)
                link["configured"] = isinstance(configured_order, int)
                link["effective_order"] = configured_order if isinstance(configured_order, int) else None
                link["app_label"] = app_label
                namespace = link["url_name"].split(":", 1)[0] if ":" in link["url_name"] else ""
                link["active"] = bool(namespace) and namespace == current_namespace
                links.append(link)

    # Stable ordering: settings overrides first, then alphabetical fallback.
    links.sort(
        key=lambda link: (
            0 if link["configured"] else 1,
            link["effective_order"] if link["effective_order"] is not None else 0,
            link["app_label"].lower(),
            link["label"].lower(),
        )
    )

    return {
        "nav_links": [
            {
                "label": link["label"],
                "url": link["url"],
                "icon": link["icon"],
                "active": link["active"],
            }
            for link in links
        ]
    }


def _items_for_config(config, request) -> list[dict]:
    """Return the raw nav items a single app config declares.

    A ``get_nav_items(request)`` method takes precedence over the static
    ``nav_items`` attribute so a plugin can compute request-aware links.

    Args:
        config: The ``AppConfig`` being inspected.
        request: The incoming HTTP request.

    Returns:
        The list of raw nav-item dicts (empty when the app declares none).
    """
    getter = getattr(config, "get_nav_items", None)
    if callable(getter):
        return getter(request) or []
    return list(getattr(config, "nav_items", []) or [])



def branding_settings(request):
    """Expose global UI branding values to every template.

    Args:
        request: The incoming HTTP request.

    Returns:
        A context dict containing global branding values used by shared layout
        templates.
    """
    return {
        "navbar_logo_text": getattr(settings, "NAVBAR_LOGO_TEXT", "Test Canvas"),
    }


def _normalize_item(item: dict[str, Any], app_label: str, request) -> dict[str, Any] | None:
    """Validate and normalize a raw menu item.

    Args:
        item: The raw menu item declared by an app. Requires ``url_name``;
            optional ``label``, ``icon``, ``args``, ``kwargs`` and
            ``permission``.
        app_label: Label of the app that owns the item.
        request: The incoming HTTP request.

    Returns:
        A normalized dictionary, or ``None`` when the item must be skipped.
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
        # Defensive behavior keeps the chrome robust when an app is removed.
        return None

    return {
        "label": item.get("label") or app_label,
        "icon": item.get("icon", ""),
        "url_name": url_name,
        "url": url,
    }

