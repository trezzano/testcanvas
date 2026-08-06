"""Template context processors for the TestCanvas app."""


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


def traceability_view(request):
    """Expose the preferred traceability view to every template.

    The choice (``"graph"`` or ``"matrix"``) lives in the session so that every
    "Back to traceability" link and node entry point resolves to the same view
    until the user changes it. Templates use ``traceability_url_name`` as the
    target of ``{% url %}`` and ``traceability_mode`` to highlight the toggle.

    Args:
        request: The incoming HTTP request.

    Returns:
        A context dict with ``traceability_mode`` (the raw choice) and
        ``traceability_url_name`` (the URL name to reverse for that choice).
    """
    # ``request.session`` is always present thanks to SessionMiddleware, but we
    # guard with getattr to stay safe in edge cases (e.g. bare test requests).
    session = getattr(request, "session", None)
    mode = DEFAULT_TRACEABILITY_MODE
    if session is not None:
        mode = session.get(TRACEABILITY_SESSION_KEY, DEFAULT_TRACEABILITY_MODE)

    return {
        "traceability_mode": mode,
        "traceability_url_name": TRACEABILITY_URL_NAMES.get(
            mode, TRACEABILITY_URL_NAMES[DEFAULT_TRACEABILITY_MODE]
        ),
    }

