"""Domain services: the single entry point for writes on TestCanvas artefacts.

Both the web views and the plugins (MCP server, CLI, REST…) call these
functions instead of writing through the ORM, so every permission check and
every ISTQB business rule lives in exactly one place.

Conventions shared by every service:

* the acting ``user`` is always the first argument and permissions are
  enforced through :mod:`testcanvas.utilities.permissions` (creating a child
  requires write access on its **parent**);
* every instance is validated with ``full_clean()`` before being saved;
* every write runs inside ``transaction.atomic()``: on error nothing is
  persisted (bulk creations are all-or-nothing).

Errors are reported only through domain exceptions, never HTTP ones:

* :class:`~testcanvas.utilities.permissions.AccessDenied` — insufficient
  access (``exc.level`` tells NONE vs READ);
* :class:`~testcanvas.utilities.permissions.ObjectNotFound` — unknown or
  unreadable object (UID-based helpers only);
* :class:`BusinessRuleViolation` (and subclasses) — an ISTQB rule is broken;
* ``django.core.exceptions.ValidationError`` — invalid data.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from testcanvas.models import (
    AcceptanceCriterion,
    ApplicationMap,
    FlowNode,
    TestCase,
    UserStory,
)
from testcanvas.utilities.duplication import duplicate_by_uid
from testcanvas.utilities.permissions import (
    AccessDenied,
    AccessLevel,
    access_level,
    can_read,
    require_write,
)

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class BusinessRuleViolation(Exception):
    """Base class for every ISTQB / domain business-rule error."""


class SubflowCannotOwnUserStories(BusinessRuleViolation):
    """Raised when User Stories are attached to a SUBFLOW node.

    A SUBFLOW node only references another map: its test basis (User Stories
    and below) lives in the referenced sub-flow, never on the node itself.
    """


class MapInUseAsSubflow(BusinessRuleViolation):
    """Raised when deleting a map that other nodes reference as a sub-flow.

    Attributes:
        referencing_nodes: The ``FlowNode`` instances still referencing the map.
    """

    def __init__(self, message: str, referencing_nodes: list[FlowNode]) -> None:
        super().__init__(message)
        self.referencing_nodes = referencing_nodes


# Sentinel meaning "argument not provided" where ``None`` is a valid value
# (e.g. ``collection=None`` moves a map to the default collection).
_UNSET: Any = object()

# Parent foreign key of each model of the ISTQB chain (top-down order).
_CHAIN: tuple[type, ...] = (ApplicationMap, FlowNode, UserStory, AcceptanceCriterion, TestCase)
_PARENT_FIELD: dict[type, str] = {
    FlowNode: "application_map",
    UserStory: "flow_node",
    AcceptanceCriterion: "user_story",
    TestCase: "acceptance_criterion",
}

# ApplicationMap fields that can only change through the dedicated services
# (they drive the FlowNode sync or the collection permissions).
_MAP_STRUCTURAL_FIELDS = frozenset({"graph_data", "collection", "collection_id"})


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _require_collection_write(user: Any, collection: Any, message: str) -> None:
    """Ensure ``user`` can write ``collection`` (``None`` = default collection).

    Args:
        user: The acting user.
        collection: An ``ApplicationMapsCollection`` or ``None``.
        message: Error message used when the check fails.

    Raises:
        AccessDenied: If the user cannot write the collection.
    """
    level = access_level(user, collection)
    if level < AccessLevel.WRITE:
        raise AccessDenied(level=level, required=AccessLevel.WRITE, message=message)


def _validate_graph_data(graph_data: Any) -> None:
    """Check the minimal shape of a Cytoscape ``graph_data`` payload.

    Args:
        graph_data: The value about to be stored in ``ApplicationMap.graph_data``.

    Raises:
        ValidationError: If the payload is not a dict, or its ``elements`` is
            not a ``{"nodes": [...], "edges": [...]}`` mapping.
    """
    if not isinstance(graph_data, dict):
        raise ValidationError({"graph_data": "graph_data must be a JSON object."})
    elements = graph_data.get("elements")
    if elements is None:
        return
    if not isinstance(elements, dict):
        raise ValidationError({"graph_data": "graph_data.elements must be an object with 'nodes' and 'edges'."})
    for key in ("nodes", "edges"):
        if not isinstance(elements.get(key, []), list):
            raise ValidationError({"graph_data": f"graph_data.elements.{key} must be a list."})


def _graph_nodes(graph_data: dict) -> list[dict]:
    """Return the ``elements.nodes`` list of a graph (empty when missing).

    Args:
        graph_data: A Cytoscape graph payload.

    Returns:
        The list of graph node dictionaries.
    """
    return ((graph_data or {}).get("elements") or {}).get("nodes") or []


def _requested_subflow_ids(graph_data: dict) -> set[int]:
    """Return the map ids referenced by SUBFLOW nodes of a graph payload.

    Args:
        graph_data: A Cytoscape graph payload.

    Returns:
        The set of referenced ``ApplicationMap`` primary keys.
    """
    refs: set[int] = set()
    for node in _graph_nodes(graph_data):
        data = node.get("data") or {}
        raw = str(data.get("sub_flow") or "")
        if data.get("node_type") == FlowNode.SUBFLOW and raw.isdigit():
            refs.add(int(raw))
    return refs


def _check_subflow_references(user: Any, application_map: ApplicationMap | None, graph_data: dict) -> None:
    """Ensure every NEW sub-flow reference targets a map the user can read.

    References that already exist in the database are kept even if no longer
    readable, so a read-restricted target is never silently dropped.

    Args:
        user: The acting user.
        application_map: The map being updated, or ``None`` on creation.
        graph_data: The graph payload about to be stored.

    Raises:
        AccessDenied: If a new reference targets an unreadable (or unknown) map.
    """
    existing: set[int] = set()
    if application_map is not None and application_map.pk:
        existing = set(
            application_map.relational_nodes
            .exclude(sub_flow_id__isnull=True)
            .values_list("sub_flow_id", flat=True)
        )
    new_refs = _requested_subflow_ids(graph_data) - existing
    if not new_refs:
        return
    targets = {m.pk: m for m in ApplicationMap.objects.filter(pk__in=new_refs)}
    for ref in new_refs:
        target = targets.get(ref)
        if target is None or not can_read(user, target):
            raise AccessDenied(
                level=AccessLevel.NONE,
                required=AccessLevel.READ,
                message=_("You cannot reference a sub-flow you do not have access to."),
            )


def _mirror_node_types(application_map: ApplicationMap) -> None:
    """Mirror ``node_type``/``sub_flow`` from ``graph_data`` onto FlowNode rows.

    ``ApplicationMap.sync_flow_nodes`` only mirrors title/description, so the
    node nature is applied here and validated through ``FlowNode.full_clean``
    (coherence, self-reference, single-level nesting and cycle checks).

    Args:
        application_map: The (already saved) map whose nodes must be updated.

    Raises:
        ValidationError: If any node violates the FlowNode invariants.
    """
    flow_by_id = {fn.local_graph_id: fn for fn in application_map.relational_nodes.all()}
    for node in _graph_nodes(application_map.graph_data):
        data = node.get("data") or {}
        flow_node = flow_by_id.get(str(data.get("id")))
        if flow_node is None:
            continue
        node_type = data.get("node_type") or FlowNode.PURE
        sub_flow_id = data.get("sub_flow") if node_type == FlowNode.SUBFLOW else None
        if flow_node.node_type == node_type and flow_node.sub_flow_id == (sub_flow_id or None):
            continue  # Nothing changed: skip the validation queries.
        flow_node.node_type = node_type
        flow_node.sub_flow_id = sub_flow_id or None
        flow_node.full_clean()
        flow_node.save(update_fields=["node_type", "sub_flow"])


def _writable_field_names(model: type) -> set[str]:
    """Return the names of the editable concrete fields of ``model``.

    Primary keys and non-editable fields (such as the UID fields) are excluded.

    Args:
        model: A Django model class.

    Returns:
        The set of field names a payload may set.
    """
    return {
        field.name
        for field in model._meta.concrete_fields
        if field.editable and not field.primary_key
    }


def _bulk_create(model: type, parent_field: str, parent: Any, items: Iterable[dict]) -> list:
    """Validate and create several children of ``parent`` atomically.

    Args:
        model: The child model class.
        parent_field: Name of the child FK pointing to ``parent``.
        parent: The parent instance.
        items: Field dictionaries, one per child to create.

    Returns:
        The created instances, in input order.

    Raises:
        ValidationError: If ``items`` is malformed or any item is invalid. The
            raised error carries an ``item_index`` attribute with the
            position of the faulty item; nothing is persisted.
    """
    if not isinstance(items, (list, tuple)):
        raise ValidationError("items must be a list of objects.")
    allowed = _writable_field_names(model) - {parent_field}
    created = []
    with transaction.atomic():
        for index, item in enumerate(items):
            try:
                if not isinstance(item, dict):
                    raise ValidationError("Each item must be an object.")
                unknown = sorted(set(item) - allowed)
                if unknown:
                    raise ValidationError({name: "Unknown or read-only field." for name in unknown})
                obj = model(**item)
                setattr(obj, parent_field, parent)
                obj.full_clean()
            except ValidationError as exc:
                # Keep the error shape (field -> messages) so forms can map it,
                # and tell bulk callers which item failed.
                exc.item_index = index
                raise
            obj.save()
            created.append(obj)
    return created


def _chain_level(obj: Any) -> int:
    """Return the position of ``obj`` in the ISTQB chain.

    Args:
        obj: A core artefact instance.

    Returns:
        ``0`` for ``ApplicationMap`` up to ``4`` for ``TestCase``.

    Raises:
        TypeError: If ``obj`` is not a core artefact.
    """
    for level, model in enumerate(_CHAIN):
        if isinstance(obj, model):
            return level
    raise TypeError(f"Unsupported object: {type(obj)!r}")


def _remove_node_from_graph(flow_node: FlowNode) -> None:
    """Delete a FlowNode by removing it (and its edges) from the map graph.

    Deleting the row alone would break the ``graph_data`` ↔ ``FlowNode``
    contract (the next save would recreate it), so the graph is edited and the
    map re-saved: ``sync_flow_nodes`` then deletes the row and its cascade.

    Args:
        flow_node: The node to delete.
    """
    application_map = flow_node.application_map
    node_id = str(flow_node.local_graph_id)
    graph = copy.deepcopy(application_map.graph_data or {})
    elements = graph.get("elements")
    if isinstance(elements, dict):
        elements["nodes"] = [
            n for n in elements.get("nodes", [])
            if str((n.get("data") or {}).get("id")) != node_id
        ]
        # Drop the edges left dangling by the removed node.
        elements["edges"] = [
            e for e in elements.get("edges", [])
            if node_id not in (
                str((e.get("data") or {}).get("source")),
                str((e.get("data") or {}).get("target")),
            )
        ]
        application_map.graph_data = graph
        application_map.save()
    # Safety net for stale rows whose node was already missing from the graph.
    FlowNode.objects.filter(pk=flow_node.pk).delete()


# --------------------------------------------------------------------------- #
# Flows (ApplicationMap)
# --------------------------------------------------------------------------- #


def create_application_map(
    user: Any,
    *,
    name: str,
    graph_data: dict | None = None,
    description: str = "",
    collection: Any = None,
) -> ApplicationMap:
    """Create a flow inside a collection the user can write.

    Saving the map mirrors its graph nodes into ``FlowNode`` rows
    (``ApplicationMap.save``); the per-node ``node_type``/``sub_flow`` found in
    ``graph_data`` are then applied and validated.

    Args:
        user: The acting user.
        name: The flow name (required, trimmed).
        graph_data: Cytoscape graph payload; ``None`` creates an empty map.
        description: Optional (HTML) description.
        collection: Target ``ApplicationMapsCollection``, or ``None`` for the
            default collection (superusers only).

    Returns:
        The created ``ApplicationMap``.

    Raises:
        AccessDenied: If the user cannot write ``collection`` or references a
            sub-flow it cannot read.
        ValidationError: If the data is invalid.
    """
    _require_collection_write(user, collection, _("You do not have write access to the selected collection."))
    graph_data = {} if graph_data is None else graph_data
    _validate_graph_data(graph_data)
    _check_subflow_references(user, None, graph_data)

    application_map = ApplicationMap(
        name=name.strip() if isinstance(name, str) else name,
        description=description or "",
        graph_data=graph_data,
        collection=collection,
    )
    with transaction.atomic():
        application_map.full_clean()
        application_map.save()  # also runs sync_flow_nodes()
        _mirror_node_types(application_map)
    return application_map


def update_application_map(
    user: Any,
    application_map: ApplicationMap,
    *,
    graph_data: dict | None = None,
    description: str | None = None,
    name: str | None = None,
    collection: Any = _UNSET,
) -> ApplicationMap:
    """Update a flow, keeping the ``graph_data`` ↔ ``FlowNode`` sync.

    Arguments left to ``None`` (or ``_UNSET`` for ``collection``) are not
    changed.

    Args:
        user: The acting user.
        application_map: The map to update.
        graph_data: New Cytoscape graph payload.
        description: New description.
        name: New name (trimmed; must not be blank).
        collection: Target collection to move the map to; ``None`` moves it
            to the default collection (superusers only).

    Returns:
        The updated map.

    Raises:
        AccessDenied: If the user cannot write the map, cannot write the
            target collection, or references a sub-flow it cannot read.
        ValidationError: If the data is invalid (e.g. a sub-flow cycle).
    """
    require_write(user, application_map)

    if collection is not _UNSET:
        new_collection_id = collection.pk if collection is not None else None
        if new_collection_id != application_map.collection_id:
            # Moving needs write access on BOTH the map and the target.
            _require_collection_write(
                user, collection, _("You do not have write access to the selected collection."),
            )
            application_map.collection = collection

    if graph_data is not None:
        _validate_graph_data(graph_data)
        _check_subflow_references(user, application_map, graph_data)
        application_map.graph_data = graph_data
    if name is not None:
        application_map.name = name.strip()
    if description is not None:
        application_map.description = description

    with transaction.atomic():
        application_map.full_clean()
        application_map.save()  # also runs sync_flow_nodes()
        _mirror_node_types(application_map)
    return application_map


# --------------------------------------------------------------------------- #
# ISTQB chain (bulk create)
# --------------------------------------------------------------------------- #


def create_user_stories(user: Any, flow_node: FlowNode, items: list[dict]) -> list[UserStory]:
    """Create several User Stories under a PURE FlowNode, atomically.

    Args:
        user: The acting user (needs write access on ``flow_node``).
        flow_node: The parent node.
        items: One field dictionary per story (e.g. ``code``, ``title``,
            ``description``, ``as_a``, ``i_want_to``, ``so_that``,
            ``additional_notes``, ``priority``).

    Returns:
        The created stories, in input order.

    Raises:
        AccessDenied: If the user cannot write the parent node.
        SubflowCannotOwnUserStories: If ``flow_node`` is a SUBFLOW node.
        ValidationError: If any item is invalid (nothing is persisted).
    """
    require_write(user, flow_node)
    # ISTQB rule: a SUBFLOW node delegates its test basis to the sub-flow.
    if flow_node.node_type == FlowNode.SUBFLOW:
        raise SubflowCannotOwnUserStories(
            "A SUBFLOW node cannot own User Stories; add them to the referenced sub-flow."
        )
    return _bulk_create(UserStory, "flow_node", flow_node, items)


def create_acceptance_criteria(
    user: Any, user_story: UserStory, items: list[dict],
) -> list[AcceptanceCriterion]:
    """Create several Acceptance Criteria under a User Story, atomically.

    Args:
        user: The acting user (needs write access on ``user_story``).
        user_story: The parent story.
        items: One field dictionary per criterion (``code`` and
            ``description`` are required).

    Returns:
        The created criteria, in input order.

    Raises:
        AccessDenied: If the user cannot write the parent story.
        ValidationError: If any item is invalid, including duplicate codes
            within the story (nothing is persisted).
    """
    require_write(user, user_story)
    return _bulk_create(AcceptanceCriterion, "user_story", user_story, items)


def create_test_cases(
    user: Any, acceptance_criterion: AcceptanceCriterion, items: list[dict],
) -> list[TestCase]:
    """Create several Test Cases under an Acceptance Criterion, atomically.

    Args:
        user: The acting user (needs write access on the criterion).
        acceptance_criterion: The parent criterion.
        items: One field dictionary per test case (``code`` is required).

    Returns:
        The created test cases, in input order.

    Raises:
        AccessDenied: If the user cannot write the parent criterion.
        ValidationError: If any item is invalid, including duplicate codes
            within the criterion (nothing is persisted).
    """
    require_write(user, acceptance_criterion)
    return _bulk_create(TestCase, "acceptance_criterion", acceptance_criterion, items)


# --------------------------------------------------------------------------- #
# Update / delete
# --------------------------------------------------------------------------- #


def update_artefact(user: Any, obj: Any, changes: dict, allowed_fields: set[str]) -> list[str]:
    """Partially update an artefact (``full_clean`` + ``save(update_fields)``).

    Structural changes are refused here because they belong to dedicated
    services: FlowNodes are edited through their map graph
    (:func:`update_application_map`), as are a map ``graph_data`` and
    ``collection``. Re-parenting a story, criterion or test case is allowed
    when the parent field is in ``allowed_fields`` and requires write access
    on the new parent too.

    Args:
        user: The acting user (needs write access on ``obj``).
        obj: An ``ApplicationMap``, ``UserStory``, ``AcceptanceCriterion`` or
            ``TestCase``.
        changes: Field name → new value.
        allowed_fields: The field names the caller lets the user change.

    Returns:
        The names of the fields written.

    Raises:
        AccessDenied: If the user cannot write ``obj`` (or the new parent).
        SubflowCannotOwnUserStories: If a story is moved to a SUBFLOW node.
        ValidationError: If a field is not allowed or the data is invalid.
    """
    require_write(user, obj)
    if not isinstance(changes, dict):
        raise ValidationError("changes must be an object.")
    if isinstance(obj, FlowNode):
        raise ValidationError("Flow nodes are edited through their map graph (update_application_map).")

    forbidden = set(changes) - set(allowed_fields)
    # UIDs are immutable stable references: never updatable.
    if "uid" in changes:
        forbidden.add("uid")
    if isinstance(obj, ApplicationMap):
        forbidden |= set(changes) & _MAP_STRUCTURAL_FIELDS
    forbidden |= set(changes) - _writable_field_names(type(obj))
    if forbidden:
        raise ValidationError({name: "This field cannot be updated." for name in sorted(forbidden)})

    parent_field = _PARENT_FIELD.get(type(obj))
    if parent_field and parent_field in changes:
        new_parent = changes[parent_field]
        require_write(user, new_parent)
        if isinstance(obj, UserStory) and new_parent.node_type == FlowNode.SUBFLOW:
            raise SubflowCannotOwnUserStories(
                "A SUBFLOW node cannot own User Stories; add them to the referenced sub-flow."
            )

    fields = list(changes)
    if not fields:
        return []
    for name, value in changes.items():
        setattr(obj, name, value)
    with transaction.atomic():
        obj.full_clean()
        obj.save(update_fields=fields)
    return fields


def deletion_preview(obj: Any) -> dict:
    """Describe what deleting ``obj`` would remove through the cascade.

    Args:
        obj: Any core artefact of the ISTQB chain.

    Returns:
        A dict ``{"model", "uid", "descendants", "total"}`` where
        ``descendants`` maps each descendant model name to the list of UIDs
        that would be deleted and ``total`` counts ``obj`` plus descendants.

    Raises:
        TypeError: If ``obj`` is not a core artefact.
    """
    level = _chain_level(obj)
    descendants: dict[str, list[str]] = {}
    path: list[str] = []
    for child_model in _CHAIN[level + 1:]:
        # Lookup from the descendant up to ``obj``, e.g. for a story and its
        # test cases: "acceptance_criterion__user_story".
        path.insert(0, _PARENT_FIELD[child_model])
        descendants[child_model.__name__] = list(
            child_model.objects
            .filter(**{"__".join(path): obj})
            .order_by("pk")
            .values_list("uid", flat=True)
        )
    return {
        "model": type(obj).__name__,
        "uid": obj.uid,
        "descendants": descendants,
        "total": 1 + sum(len(uids) for uids in descendants.values()),
    }


def delete_artefact(user: Any, obj: Any) -> dict:
    """Delete an artefact and its cascade, enforcing the business rules.

    * A map referenced as a sub-flow by other nodes cannot be deleted.
    * A FlowNode is removed from its map graph (keeping the sync contract).

    Args:
        user: The acting user (needs write access on ``obj``).
        obj: Any core artefact of the ISTQB chain.

    Returns:
        The :func:`deletion_preview` of what was deleted.

    Raises:
        AccessDenied: If the user cannot write ``obj``.
        MapInUseAsSubflow: If ``obj`` is a map still used as a sub-flow.
        TypeError: If ``obj`` is not a core artefact.
    """
    require_write(user, obj)
    preview = deletion_preview(obj)
    with transaction.atomic():
        if isinstance(obj, ApplicationMap):
            referencing = list(obj.referencing_nodes.select_related("application_map"))
            if referencing:
                raise MapInUseAsSubflow(
                    f"Flow '{obj.name}' is used as a sub-flow and cannot be deleted.",
                    referencing,
                )
            obj.delete()
        elif isinstance(obj, FlowNode):
            _remove_node_from_graph(obj)
        else:
            obj.delete()
    return preview


__all__ = [
    "BusinessRuleViolation",
    "MapInUseAsSubflow",
    "SubflowCannotOwnUserStories",
    "create_acceptance_criteria",
    "create_application_map",
    "create_test_cases",
    "create_user_stories",
    "delete_artefact",
    "deletion_preview",
    "duplicate_by_uid",
    "update_application_map",
    "update_artefact",
]

