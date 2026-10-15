"""Collection-based access control for TestCanvas (public plugin API).
Single source of truth for "who can see / modify what". Every view, form,
template and plugin must go through these helpers instead of re-implementing
the rules.
Rules:
    * Superusers are unrestricted: they see and modify everything, exactly as
      if no permission system existed.
    * Other users only get access through ``CollectionPermission`` grants,
      assigned to them directly or to one of their groups.
    * A grant on a collection cascades DOWN the tree: it applies to every
      nested sub-collection and to every ``ApplicationMap`` contained in them,
      including the whole ISTQB chain below each map (FlowNode → UserStory →
      AcceptanceCriterion → TestCase).
    * Write access implies read access.
    * Maps without a collection belong to a virtual "default collection" that
      only superusers can read or write.
Design:
    This module is a pure *domain* layer: it never raises HTTP-specific
    exceptions. Failed checks raise :class:`AccessDenied` (a subclass of
    Django's ``PermissionDenied``) carrying the access level the user actually
    has, so each caller decides how to react (404, 403, CLI error, JSON error…).
    Web views use the thin HTTP adapters in ``testcanvas.views._permissions``.
Extensibility:
    Plugin models linked to a flow can join the permission system either by
    implementing a ``get_permission_map()`` method returning their owning
    ``ApplicationMap``, or by calling :func:`register_permission_model` (which
    also enables :func:`filter_readable` on their querysets).
The computed access sets are cached on the user instance, which lives for a
single request (``request.user``), so the grant tables are queried at most
once per request. Use :func:`clear_access_cache` to invalidate it.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable
from django.core.exceptions import PermissionDenied
from django.db.models import Model, Q, QuerySet
# Attribute name used to cache the computed access sets on the user object.
_CACHE_ATTR = "_testcanvas_collection_access"
# --------------------------------------------------------------------------- #
# Public types
# --------------------------------------------------------------------------- #
class AccessLevel(IntEnum):
    """Access level of a user on an object, ordered from lowest to highest.
    Being an ``IntEnum``, levels can be compared (``level >= AccessLevel.READ``).
    """
    NONE = 0
    READ = 1
    WRITE = 2
class AccessDenied(PermissionDenied):
    """Raised when a user does not have the required access level.
    Subclasses ``PermissionDenied`` so that, if not handled, Django renders it
    as a 403. Callers that want to hide unreadable objects can inspect
    :attr:`level` and answer 404 when it is :attr:`AccessLevel.NONE`.
    Attributes:
        level: The access level the user actually has on the object.
        required: The access level that was required.
    """
    def __init__(self, level: AccessLevel, required: AccessLevel, message: str | None = None) -> None:
        self.level = level
        self.required = required
        if message is None:
            message = (
                "You do not have access to this object."
                if level == AccessLevel.NONE
                else "You only have read access to this object."
            )
        super().__init__(message)
@dataclass(frozen=True)
class CollectionAccess:
    """Pre-computed collection ids a user can read and write.
    Attributes:
        readable: Ids of the collections the user can read (cascade applied).
        writable: Ids of the collections the user can write (cascade applied).
        unrestricted: ``True`` for superusers, who bypass every check.
    """
    readable: frozenset[int] = field(default_factory=frozenset)
    writable: frozenset[int] = field(default_factory=frozenset)
    unrestricted: bool = False
    def level_for(self, collection_id: int | None) -> AccessLevel:
        """Return the access level on a collection id.
        Args:
            collection_id: The collection id, or ``None`` for the default
                (ungrouped) collection.
        Returns:
            The :class:`AccessLevel` granted on that collection.
        """
        if self.unrestricted:
            return AccessLevel.WRITE
        if collection_id is None:
            # The virtual default collection is reserved to superusers.
            return AccessLevel.NONE
        if collection_id in self.writable:
            return AccessLevel.WRITE
        if collection_id in self.readable:
            return AccessLevel.READ
        return AccessLevel.NONE
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
_REGISTRY: dict[type, _ModelSpec] = {}
def register_permission_model(
    model: type[Model],
    *,
    collection_path: str,
    resolve_map: Callable[[Any], Any],
) -> None:
    """Make a plugin model governed by the collection permissions.
    Args:
        model: The model class to register.
        collection_path: ORM lookup from ``model`` to the governing collection
            id, e.g. ``"flow_node__application_map__collection_id"``.
        resolve_map: Callable returning the owning ``ApplicationMap`` of an
            instance of ``model``.
    Example:
        >>> register_permission_model(
        ...     TestRun,
        ...     collection_path="test_case__acceptance_criterion__user_story"
        ...                     "__flow_node__application_map__collection_id",
        ...     resolve_map=lambda run: resolve_map(run.test_case),
        ... )
    """
    _REGISTRY[model] = _ModelSpec(collection_path=collection_path, resolve_map=resolve_map)
def _register_core_models() -> None:
    """Register the core TestCanvas models (called lazily, once)."""
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
    for klass in model.__mro__:
        if klass in _REGISTRY:
            return _REGISTRY[klass]
    return None
# --------------------------------------------------------------------------- #
# Access computation
# --------------------------------------------------------------------------- #
def is_unrestricted(user: Any) -> bool:
    """Return whether ``user`` bypasses the collection permissions.
    Args:
        user: The (possibly anonymous) user to evaluate.
    Returns:
        ``True`` only for authenticated, active superusers.
    """
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and getattr(user, "is_superuser", False)
    )
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
        if current in result:
            continue
        result.add(current)
        stack.extend(children_by_parent.get(current, []))
    return result
def get_access(user: Any) -> CollectionAccess:
    """Compute (or return the cached) collection access of ``user``.
    Args:
        user: The user whose grants are evaluated.
    Returns:
        A :class:`CollectionAccess` describing readable and writable ids.
    """
    if is_unrestricted(user):
        return CollectionAccess(unrestricted=True)
    if user is None or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return CollectionAccess()
    cached = getattr(user, _CACHE_ATTR, None)
    if cached is not None:
        return cached
    # Local import avoids a circular import (models -> utilities -> models).
    from testcanvas.models import ApplicationMapsCollection, CollectionPermission
    grants = CollectionPermission.objects.filter(
        Q(user=user) | Q(group__in=user.groups.all())
    ).values_list("collection_id", "can_read", "can_write")
    direct_read: set[int] = set()
    direct_write: set[int] = set()
    for collection_id, can_read_flag, can_write_flag in grants:
        if can_write_flag:
            # Write implies read.
            direct_write.add(collection_id)
            direct_read.add(collection_id)
        elif can_read_flag:
            direct_read.add(collection_id)
    if direct_read:
        # One query for the whole tree, then cascade the grants downwards.
        children_by_parent: dict[int | None, list[int]] = defaultdict(list)
        for pk, parent_id in ApplicationMapsCollection.objects.values_list("pk", "parent_id"):
            children_by_parent[parent_id].append(pk)
        readable = _expand_descendants(direct_read, children_by_parent)
        writable = _expand_descendants(direct_write, children_by_parent)
    else:
        readable, writable = set(), set()
    access = CollectionAccess(readable=frozenset(readable), writable=frozenset(writable))
    setattr(user, _CACHE_ATTR, access)
    return access
def clear_access_cache(user: Any) -> None:
    """Drop the cached access sets (e.g. after creating or moving a collection).
    Args:
        user: The user whose cache should be invalidated.
    """
    if user is not None and hasattr(user, _CACHE_ATTR):
        delattr(user, _CACHE_ATTR)
# --------------------------------------------------------------------------- #
# Object resolution
# --------------------------------------------------------------------------- #
def resolve_map(obj: Any):
    """Return the ``ApplicationMap`` owning ``obj``.
    Supports the core ISTQB chain, registered plugin models and any object
    exposing a ``get_permission_map()`` method.
    Args:
        obj: An ``ApplicationMap``, ``FlowNode``, ``UserStory``,
            ``AcceptanceCriterion``, ``TestCase`` or extension object.
    Returns:
        The owning ``ApplicationMap``.
    Raises:
        TypeError: If ``obj`` cannot be linked to a map.
    """
    from testcanvas.models import ApplicationMap
    if isinstance(obj, ApplicationMap):
        return obj
    spec = _spec_for(type(obj))
    if spec is not None and spec.resolve_map is not None:
        return spec.resolve_map(obj)
    getter = getattr(obj, "get_permission_map", None)
    if callable(getter):
        return getter()
    raise TypeError(f"Unsupported object for permission checks: {type(obj)!r}")
def governing_collection_id(obj: Any) -> int | None:
    """Return the id of the collection that governs access to ``obj``.
    Args:
        obj: A collection, a collection id, ``None`` (default collection) or
            any object supported by :func:`resolve_map`.
    Returns:
        The governing collection id, or ``None`` for the default collection.
    """
    from testcanvas.models import ApplicationMapsCollection
    if obj is None or isinstance(obj, int):
        return obj
    if isinstance(obj, ApplicationMapsCollection):
        return obj.pk
    return resolve_map(obj).collection_id
# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
def access_level(user: Any, obj: Any) -> AccessLevel:
    """Return the access level of ``user`` on ``obj``.
    This is the most general check: every other helper is built on it.
    Args:
        user: The user to evaluate.
        obj: A collection (instance, id or ``None`` for the default one) or
            any object supported by :func:`resolve_map`.
    Returns:
        :attr:`AccessLevel.NONE`, :attr:`AccessLevel.READ` or
        :attr:`AccessLevel.WRITE`.
    """
    return get_access(user).level_for(governing_collection_id(obj))
def can_read(user: Any, obj: Any) -> bool:
    """Return whether ``user`` can read ``obj`` (see :func:`access_level`)."""
    return access_level(user, obj) >= AccessLevel.READ
def can_write(user: Any, obj: Any) -> bool:
    """Return whether ``user`` can write ``obj`` (see :func:`access_level`)."""
    return access_level(user, obj) >= AccessLevel.WRITE
def can_read_collection(user: Any, collection: Any) -> bool:
    """Return whether ``user`` can read a collection.
    Args:
        user: The user to evaluate.
        collection: A collection instance, its id, or ``None`` for the default
            (ungrouped) collection.
    Returns:
        ``True`` when reading is allowed.
    """
    return can_read(user, collection)
def can_write_collection(user: Any, collection: Any) -> bool:
    """Return whether ``user`` can write a collection.
    Args:
        user: The user to evaluate.
        collection: A collection instance, its id, or ``None`` for the default
            (ungrouped) collection.
    Returns:
        ``True`` when writing is allowed.
    """
    return can_write(user, collection)
def require(user: Any, obj: Any, required: AccessLevel) -> AccessLevel:
    """Ensure ``user`` has at least ``required`` access on ``obj``.
    Args:
        user: The user to evaluate.
        obj: The object to check (see :func:`access_level`).
        required: The minimum access level.
    Returns:
        The actual access level (handy to drive the UI).
    Raises:
        AccessDenied: If the actual level is lower than ``required``.
    """
    level = access_level(user, obj)
    if level < required:
        raise AccessDenied(level=level, required=required)
    return level
def require_read(user: Any, obj: Any) -> AccessLevel:
    """Ensure ``user`` can read ``obj``; raise :class:`AccessDenied` otherwise."""
    return require(user, obj, AccessLevel.READ)
def require_write(user: Any, obj: Any) -> AccessLevel:
    """Ensure ``user`` can write ``obj``; raise :class:`AccessDenied` otherwise.
    The raised exception's ``level`` tells whether the object was readable
    (``READ``) or not visible at all (``NONE``).
    """
    return require(user, obj, AccessLevel.WRITE)
# --------------------------------------------------------------------------- #
# Querysets
# --------------------------------------------------------------------------- #
def filter_readable(user: Any, queryset: QuerySet, write: bool = False) -> QuerySet:
    """Restrict any supported queryset to the objects ``user`` can access.
    Works for collections, maps, FlowNodes, User Stories, Acceptance Criteria,
    Test Cases and every model registered with
    :func:`register_permission_model`.
    Args:
        user: The user to evaluate.
        queryset: The queryset to filter.
        write: When ``True`` keep only writable objects.
    Returns:
        The filtered queryset (unchanged for superusers). Objects in the
        default collection are always excluded for non-superusers.
    Raises:
        TypeError: If the queryset model is not supported.
    """
    spec = _spec_for(queryset.model)
    if spec is None:
        raise TypeError(f"Model {queryset.model!r} is not registered for permission filtering.")
    access = get_access(user)
    if access.unrestricted:
        return queryset
    ids = access.writable if write else access.readable
    return queryset.filter(**{f"{spec.collection_path}__in": ids})
def filter_maps(user: Any, queryset: QuerySet, write: bool = False) -> QuerySet:
    """Restrict an ``ApplicationMap`` queryset (alias of :func:`filter_readable`)."""
    return filter_readable(user, queryset, write=write)
def filter_collections(user: Any, queryset: QuerySet, write: bool = False) -> QuerySet:
    """Restrict a collection queryset (alias of :func:`filter_readable`)."""
    return filter_readable(user, queryset, write=write)
__all__ = [
    "AccessDenied",
    "AccessLevel",
    "CollectionAccess",
    "access_level",
    "can_read",
    "can_read_collection",
    "can_write",
    "can_write_collection",
    "clear_access_cache",
    "filter_collections",
    "filter_maps",
    "filter_readable",
    "get_access",
    "governing_collection_id",
    "is_unrestricted",
    "register_permission_model",
    "require",
    "require_read",
    "require_write",
    "resolve_map",
]
