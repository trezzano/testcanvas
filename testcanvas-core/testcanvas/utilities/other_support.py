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

from django.db.models import Model, Count

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


def get_object_url(uid: str) -> str:
    """Return the stable TestCanvas URL that opens the artefact with ``uid``.

    The URL points to the core UID resolver, which finds the artefact and
    redirects to the right page. No lookup or permission check happens here:
    the resolver enforces permissions when the link is opened (unknown or
    unreadable UIDs answer 404), so plugins can store and render links without
    touching the linked object.

    Args:
        uid: The artefact UID (opaque string).

    Returns:
        The absolute path of the resolver for ``uid``.
    """
    # Local import keeps this module importable before the URLconf is loaded.
    from django.urls import reverse

    return reverse("testcanvas:dynamic_show_by_uid", args=[uid])


def check_acceptance_criteria_coverage(app_map_uid: str) -> dict:
    """Quick coverage check: are all AC of the given flow covered by TestCases?

    Args:
        app_map_uid: ApplicationMap UID (e.g., "AMU-abc123def456g").

    Returns:
        {
            "covered": bool,              # True if all AC have >= 1 TC
            "coverage_percentage": float, # 0-100
            "covered_criteria": int,      # AC with TC
            "total_criteria": int         # Total AC
        }
    """
    app_map = ApplicationMap.objects.get(uid=app_map_uid)

    # Single query: get all AC with test case count
    criteria = list(
        AcceptanceCriterion.objects.filter(
            user_story__flow_node__application_map=app_map
        ).annotate(tc_count=Count('test_cases')).values_list('tc_count')
    )

    total = len(criteria)
    covered = sum(1 for (tc_count,) in criteria if tc_count > 0)
    percentage = (covered / total * 100) if total > 0 else 100.0

    return {
        "covered": covered == total,
        "coverage_percentage": round(percentage, 2),
        "covered_criteria": covered,
        "total_criteria": total,
    }




__all__ = [
    "UID_MODELS",
    "find_model_object_by_uid",
    "check_acceptance_criteria_coverage"
]

