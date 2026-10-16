"""Private support helpers for :mod:`testcanvas.utilities.permissions`.

This module hosts the internal machinery (model registry, tree expansion,
"not found" handling) used by the public permission API. It is NOT part of
the public plugin API: plugins and views must only import from
:mod:`testcanvas.utilities.permissions`.

Circular imports:
    ``permissions`` imports this module at load time, so every reference back
    to ``permissions`` (public types and checks) is imported lazily inside the
    functions that need it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# Attribute name used to cache the computed access sets on the user object.
_CACHE_ATTR = "_testcanvas_collection_access"

# --------------------------------------------------------------------------- #
# Model registry (core models + plugin extensions)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _ModelSpec:
    """How to reach the governing collection from a model.

    Attributes:
        collection_path: ORM lookup from the model to the collection id
            (e.g. ``"application_map__collection_id"``), used by querysets.
        resolve_map: Callable returning the owning ``ApplicationMap`` of an
            instance, used by single-object checks. ``None`` for models that
            are collections or maps themselves.
    """

    collection_path: str
    resolve_map: Callable[[Any], Any] | None


#: Registry ``model class -> _ModelSpec``, filled lazily with the core models
#: and extended by plugins through ``register_permission_model``.
_REGISTRY: dict[type, _ModelSpec] = {}


def _register_core_models() -> None:
    """Register the core TestCanvas models (called lazily, once).

    ``setdefault`` is used so that a plugin registering a core model before
    the lazy initialization is never overwritten.
    """
    # Local import avoids a circular import (models -> utilities -> models).
    from testcanvas.models import (
        AcceptanceCriterion,
        ApplicationMap,
        ApplicationMapsCollection,
        FlowNode,
        TestCase,
        UserStory,
    )

    _REGISTRY.setdefault(ApplicationMapsCollection, _ModelSpec("pk", None))
    _REGISTRY.setdefault(ApplicationMap, _ModelSpec("collection_id", None))
    _REGISTRY.setdefault(FlowNode, _ModelSpec(
        "application_map__collection_id",
        lambda o: o.application_map,
    ))
    _REGISTRY.setdefault(UserStory, _ModelSpec(
        "flow_node__application_map__collection_id",
        lambda o: o.flow_node.application_map,
    ))
    _REGISTRY.setdefault(AcceptanceCriterion, _ModelSpec(
        "user_story__flow_node__application_map__collection_id",
        lambda o: o.user_story.flow_node.application_map,
    ))
    _REGISTRY.setdefault(TestCase, _ModelSpec(
        "acceptance_criterion__user_story__flow_node__application_map__collection_id",
        lambda o: o.acceptance_criterion.user_story.flow_node.application_map,
    ))


def _spec_for(model: type) -> _ModelSpec | None:
    """Return the registry entry of ``model`` (or of one of its bases).

    Args:
        model: A model class.

    Returns:
        The matching :class:`_ModelSpec`, or ``None`` if not registered.
    """
    if not _REGISTRY:
        _register_core_models()
    # Walk the MRO so subclasses (e.g. proxy models) inherit the spec.
    for klass in model.__mro__:
        if klass in _REGISTRY:
            return _REGISTRY[klass]
    return None


# --------------------------------------------------------------------------- #
# Access computation helpers
# --------------------------------------------------------------------------- #


def _expand_descendants(root_ids: set[int], children_by_parent: dict[int | None, list[int]]) -> set[int]:
    """Return ``root_ids`` plus every descendant id in the collection tree.

    Args:
        root_ids: Collection ids that hold a direct grant.
        children_by_parent: Adjacency map ``parent_id -> [child ids]``.

    Returns:
        The set of granted ids extended with all their descendants.
    """
    result: set[int] = set()
    stack = list(root_ids)
    while stack:
        current = stack.pop()
        # Guard against cycles or already-visited branches.
        if current in result:
            continue
        result.add(current)
        stack.extend(children_by_parent.get(current, []))
    return result


# --------------------------------------------------------------------------- #
# "Not found" handling
# --------------------------------------------------------------------------- #


def _not_found(identifier: Any):
    """Build the single "not found" error used for unknown AND unreadable objects.

    The message is a constant (the identifier is not echoed), so both cases
    produce exactly the same text and never disclose whether an unreadable
    object exists.

    Args:
        identifier: The UID or id requested by the caller, kept on the
            exception as ``identifier`` for logging purposes.

    Returns:
        A ready-to-raise ``ObjectNotFound``.
    """
    from testcanvas.utilities.permissions import OBJECT_NOT_FOUND_MESSAGE, ObjectNotFound

    exc = ObjectNotFound(OBJECT_NOT_FOUND_MESSAGE)
    exc.identifier = identifier
    return exc


def _enforce(user: Any, obj: Any, required: Any, identifier: Any) -> None:
    """Check ``required`` access, hiding unreadable objects behind ObjectNotFound.

    Args:
        user: The user to evaluate.
        obj: The object (or collection / ``None``) to check.
        required: The minimum ``AccessLevel``.
        identifier: The requested UID or id, used in the error message.

    Raises:
        ObjectNotFound: If the user cannot even read ``obj``.
        AccessDenied: If ``obj`` is readable but ``required`` is higher.
    """
    from testcanvas.utilities.permissions import AccessDenied, AccessLevel, require

    try:
        require(user, obj, required)
    except AccessDenied as exc:
        # NONE means the object is invisible: report it as missing.
        if exc.level == AccessLevel.NONE:
            raise _not_found(identifier) from None
        raise

