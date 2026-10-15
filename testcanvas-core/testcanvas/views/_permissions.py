"""HTTP adapters over the pure permission domain API.

``testcanvas.utilities.permissions`` is intentionally HTTP-agnostic (see its
module docstring): it raises :class:`~testcanvas.utilities.permissions.AccessDenied`,
a plain ``PermissionDenied`` subclass, and lets the caller decide how to react.

TestCanvas web views always want the same reaction:

* an unreadable object must answer **404** (never reveal that it exists);
* a readable-but-read-only object must answer **403**.

These two thin wrappers implement that policy once, so views stay as simple as
``ensure_can_read(request.user, obj)``. External plugins are free to call the
domain API directly (``require_read`` / ``require_write`` / ``access_level``)
and choose a different policy.
"""

from __future__ import annotations

from typing import Any

from django.http import Http404

from testcanvas.utilities.permissions import AccessDenied, AccessLevel, require_read, require_write


def ensure_can_read(user: Any, obj: Any) -> None:
    """Abort a view with a 404 when ``user`` cannot read ``obj``.

    Args:
        user: The requesting user.
        obj: A collection or any artefact of the ISTQB chain.

    Raises:
        Http404: If reading is not allowed.
    """
    try:
        require_read(user, obj)
    except AccessDenied as exc:
        raise Http404("Object not found.") from exc


def ensure_can_write(user: Any, obj: Any) -> None:
    """Abort a view when ``user`` cannot write ``obj``.

    Unreadable objects raise 404 (no disclosure); readable but read-only
    objects raise 403.

    Args:
        user: The requesting user.
        obj: A collection or any artefact of the ISTQB chain.

    Raises:
        Http404: If the object is not even readable.
        AccessDenied: If the object is readable but not writable (results in a
            403 response, since it is a ``PermissionDenied`` subclass).
    """
    try:
        require_write(user, obj)
    except AccessDenied as exc:
        if exc.level is AccessLevel.NONE:
            raise Http404("Object not found.") from exc
        raise

