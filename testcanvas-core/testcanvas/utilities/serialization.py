"""Shared, transport-agnostic serialization of the core artefacts.

Every function returns a plain ``dict`` (JSON-ready) so the web API, the MCP
server and any other plugin expose exactly the same shape.

Rules:
    * Artefacts are identified by their compact UIDs, never by internal
      primary keys. Collections have no UID, so their id is the only public
      identifier and is exposed as ``collection_id``.
    * Every artefact exposes its own UID as ``uid`` and its direct parent
      under an explicit, self-describing key named after the parent model,
      so the payload is unambiguous even when read out of context (e.g. by
      an LLM through MCP):

      ==========================  ==============================
      Artefact                    Parent key
      ==========================  ==============================
      ``ApplicationMap``          (none, a map has no parent)
      ``FlowNode``                ``application_map_uid``
      ``UserStory``               ``flow_node_uid``
      ``AcceptanceCriterion``     ``user_story_uid``
      ``TestCase``                ``acceptance_criterion_uid``
      ==========================  ==============================

      A SUBFLOW node also exposes the referenced map as ``sub_flow_uid``.
    * Related objects the user cannot read (e.g. the map referenced by a
      SUBFLOW node) are redacted through
      :func:`~testcanvas.utilities.permissions.readable_or_none`.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Prefetch

from testcanvas.models import (
    AcceptanceCriterion,
    ApplicationMap,
    FlowNode,
    TestCase,
    UserStory,
)
from testcanvas.utilities.permissions import (
    OBJECT_NOT_FOUND_MESSAGE,
    AccessDenied,
    AccessLevel,
    ObjectNotFound,
    readable_or_none,
    require,
)


def serialize_application_map(obj: ApplicationMap, *, include_graph: bool = False) -> dict:
    """Serialize an ``ApplicationMap``.

    Args:
        obj: The map to serialize.
        include_graph: When ``True`` also include the Cytoscape ``graph_data``.

    Returns:
        A JSON-ready dict.
    """
    data = {
        "uid": obj.uid,
        "name": obj.name,
        "description": obj.description,
        "collection_id": obj.collection_id,
        "created_at": obj.created_at.isoformat() if obj.created_at else None,
    }
    if include_graph:
        data["graph_data"] = obj.graph_data
    return data


def serialize_flow_node(obj: FlowNode, *, user: Any = None) -> dict:
    """Serialize a ``FlowNode``.

    Args:
        obj: The node to serialize.
        user: The acting user. When given, the referenced sub-flow is redacted
            (``sub_flow_uid``/``sub_flow_name`` set to ``None``) if the user
            cannot read it. ``None`` skips redaction and must only be used in
            trusted, user-less contexts.

    Returns:
        A JSON-ready dict with the node ``uid``, the owning map UID as
        ``application_map_uid`` and, for SUBFLOW nodes, the referenced map
        as ``sub_flow_uid`` / ``sub_flow_name``.
    """
    sub_flow = obj.sub_flow if obj.sub_flow_id else None
    if user is not None:
        sub_flow = readable_or_none(user, sub_flow)
    return {
        "uid": obj.uid,
        "application_map_uid": obj.application_map.uid,
        "local_graph_id": obj.local_graph_id,
        "title": obj.title,
        "description": obj.description,
        "node_type": obj.node_type,
        "sub_flow_uid": sub_flow.uid if sub_flow else None,
        "sub_flow_name": sub_flow.name if sub_flow else None,
    }


def serialize_user_story(obj: UserStory) -> dict:
    """Serialize a ``UserStory``.

    Args:
        obj: The story to serialize.

    Returns:
        A JSON-ready dict with the story ``uid`` and the owning node UID as
        ``flow_node_uid``.
    """
    return {
        "uid": obj.uid,
        "flow_node_uid": obj.flow_node.uid,
        "code": obj.code,
        "title": obj.title,
        "description": obj.description,
        "as_a": obj.as_a,
        "i_want_to": obj.i_want_to,
        "so_that": obj.so_that,
        "additional_notes": obj.additional_notes,
        "priority": obj.priority,
        "story_points": obj.story_points,
        "risk_level": obj.risk_level,
        "status": obj.status,
    }


def serialize_acceptance_criterion(obj: AcceptanceCriterion) -> dict:
    """Serialize an ``AcceptanceCriterion``.

    Args:
        obj: The criterion to serialize.

    Returns:
        A JSON-ready dict with the criterion ``uid`` and the owning story UID
        as ``user_story_uid``.
    """
    return {
        "uid": obj.uid,
        "user_story_uid": obj.user_story.uid,
        "code": obj.code,
        "description": obj.description,
        "gherkin_text": obj.gherkin_text,
        "criterion_type": obj.criterion_type,
        "additional_notes": obj.additional_notes,
        "moscow_priority": obj.moscow_priority,
        "verification_method": obj.verification_method,
    }


def serialize_test_case(obj: TestCase) -> dict:
    """Serialize a ``TestCase``.

    Args:
        obj: The test case to serialize.

    Returns:
        A JSON-ready dict with the test case ``uid`` and the owning criterion
        UID as ``acceptance_criterion_uid``.
    """
    return {
        "uid": obj.uid,
        "acceptance_criterion_uid": obj.acceptance_criterion.uid,
        "code": obj.code,
        "description": obj.description,
        "additional_notes": obj.additional_notes,
        "execution_type": obj.execution_type,
        "automation_status": obj.automation_status,
        "test_level": obj.test_level,
        "test_type": obj.test_type,
        "estimated_duration_minutes": obj.estimated_duration_minutes,
    }


def serialize_flow_overview(
    user: Any,
    application_map: ApplicationMap,
    *,
    include_test_cases: bool = False,
) -> dict:
    """Serialize a map as a nested tree: map → nodes → stories → criteria.

    The whole tree is loaded with a constant number of queries (prefetch),
    whatever its size. Sub-flow references are redacted for users who cannot
    read the referenced map.

    Args:
        user: The acting user (needs read access on the map).
        application_map: The map to serialize.
        include_test_cases: When ``True`` each criterion also lists its test
            cases.

    Returns:
        A JSON-ready dict with a ``nodes`` list; each node has
        ``user_stories``, each story ``acceptance_criteria`` and, optionally,
        each criterion ``test_cases``.

    Raises:
        ObjectNotFound: If the user cannot read the map.
    """
    try:
        require(user, application_map, AccessLevel.READ)
    except AccessDenied:
        raise ObjectNotFound(OBJECT_NOT_FOUND_MESSAGE) from None

    criteria_lookup = "user_stories__criteria"
    prefetches: list[Any] = [
        Prefetch("user_stories", queryset=UserStory.objects.order_by("code")),
        Prefetch(criteria_lookup, queryset=AcceptanceCriterion.objects.order_by("code")),
    ]
    if include_test_cases:
        prefetches.append(
            Prefetch(f"{criteria_lookup}__test_cases", queryset=TestCase.objects.order_by("code"))
        )
    nodes = (
        application_map.relational_nodes
        .select_related("sub_flow")
        .prefetch_related(*prefetches)
        .order_by("local_graph_id")
    )

    serialized_nodes = []
    for node in nodes:
        # Reuse the already-loaded map: avoids one query per node.
        node.application_map = application_map
        node_data = serialize_flow_node(node, user=user)
        stories = []
        for story in node.user_stories.all():
            story.flow_node = node
            story_data = serialize_user_story(story)
            criteria = []
            for criterion in story.criteria.all():
                criterion.user_story = story
                criterion_data = serialize_acceptance_criterion(criterion)
                if include_test_cases:
                    test_cases = []
                    for test_case in criterion.test_cases.all():
                        test_case.acceptance_criterion = criterion
                        test_cases.append(serialize_test_case(test_case))
                    criterion_data["test_cases"] = test_cases
                criteria.append(criterion_data)
            story_data["acceptance_criteria"] = criteria
            stories.append(story_data)
        node_data["user_stories"] = stories
        serialized_nodes.append(node_data)

    data = serialize_application_map(application_map)
    data["nodes"] = serialized_nodes
    return data


__all__ = [
    "serialize_acceptance_criterion",
    "serialize_application_map",
    "serialize_flow_node",
    "serialize_flow_overview",
    "serialize_test_case",
    "serialize_user_story",
]

