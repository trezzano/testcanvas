"""Resolve a compact UID to the core TestCanvas artefact that owns it.

Every artefact of the ISTQB chain (``ApplicationMap``, ``FlowNode``,
``UserStory``, ``AcceptanceCriterion``, ``TestCase``) stores its compact,
globally unique identifier in a field named ``uid``, so reading it is simply
``obj.uid`` and filtering is simply ``Model.objects.filter(uid=...)``.

Important:
    A UID is treated as an opaque string: the code never parses its prefix.
    UIDs are assumed unique across all the artefact tables (each ``uid`` field
    is unique in its own table and the generator makes cross-table collisions
    negligible, but no database constraint enforces it).
"""

from __future__ import annotations

from typing import Any

from django.db.models import Model

from testcanvas.models import (
    AcceptanceCriterion,
    ApplicationMap,
    FlowNode,
    TestCase,
    UserStory,
)

#: Every model carrying a ``uid`` field, in lookup order (top of the ISTQB
#: chain first). Should two tables ever share a UID, the first one wins.
UID_MODELS: tuple[type[Model], ...] = (
    ApplicationMap,
    FlowNode,
    UserStory,
    AcceptanceCriterion,
    TestCase,
)


def find_model_object_by_uid(uid: Any) -> Model | None:
    """Return the artefact whose ``uid`` matches, or ``None``.

    Each table of ``UID_MODELS`` is queried in turn on its indexed ``uid``
    column (at most 5 fast queries). This function does **not** check
    permissions: user-facing callers must use
    :func:`testcanvas.utilities.permissions.get_object_by_uid_for_user`.

    Args:
        uid: The UID to resolve. Leading/trailing whitespace is ignored.

    Returns:
        The matching artefact, or ``None`` when nothing matches or when
        ``uid`` is not a non-blank string.
    """
    # Invalid input is simply "not found", exactly like an unknown UID.
    if not isinstance(uid, str) or not uid.strip():
        return None
    uid = uid.strip()

    for model in UID_MODELS:
        obj = model.objects.filter(uid=uid).first()
        if obj is not None:
            return obj
    return None


__all__ = [
    "UID_MODELS",
    "find_model_object_by_uid",
]

