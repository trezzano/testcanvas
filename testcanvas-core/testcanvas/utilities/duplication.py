"""Duplicate any TestCanvas object, starting from its UID.

The single public entry point is :func:`duplicate_by_uid`. Given the UID of an
``ApplicationMap``, ``FlowNode``, ``UserStory``, ``AcceptanceCriterion`` or
``TestCase``, it creates a copy of that object together with **all** the
objects that hang below it (cascade copy).

Naming rules:

* only the object the user asked to duplicate (the "root" of the copy) gets
  the ``copy_`` prefix;
* every child copied in cascade keeps exactly the same name/code;
* every copy always receives brand-new UIDs (they are generated automatically
  by the model field defaults).

Which field receives the ``copy_`` prefix on the root object:

==========================  ===========================================
Object                      Field
==========================  ===========================================
``ApplicationMap``          ``name``
``FlowNode``                ``title`` (and the node ``name`` in the graph)
``UserStory``               ``title``
``AcceptanceCriterion``     ``code``
``TestCase``                ``code``
==========================  ===========================================

Cascade order::

    ApplicationMap -> FlowNode -> UserStory -> AcceptanceCriterion -> TestCase
"""

import copy

import networkx as nx
from django.db import transaction

from testcanvas.models import (
    AcceptanceCriterion,
    ApplicationMap,
    FlowNode,
    TestCase,
    UserStory,
)
from testcanvas.utilities.other_support import find_model_object_by_uid

# Prefix added to the name of the object the user asked to duplicate.
COPY_PREFIX = "copy_"

# How far (in pixels) a duplicated graph node is moved from the original one,
# so that the two nodes do not overlap in the map editor.
NODE_POSITION_OFFSET = 40

# Maximum length allowed for the ``code`` field of AC and TC
# (must match ``max_length`` in models.py).
CODE_MAX_LENGTH = 200


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def duplicate_by_uid(uid: str, *, user=None):
    """Duplicate the object identified by ``uid`` and everything below it.

    The whole operation runs inside a single database transaction: if anything
    goes wrong, nothing is saved (no half-made copies are left behind).

    The UID is treated as an opaque string: its format is never inspected.

    Args:
        uid: The UID of the object to duplicate.
        user: Optional acting user. When given, write access on the original
            is enforced (the copy lands in the same flow/collection). ``None``
            skips the check and is kept for backward compatibility (trusted
            callers such as management commands).

    Returns:
        The newly created copy (same model as the original object).

    Raises:
        ValueError: If ``user`` is ``None`` and no object matches ``uid``, or
            the copy cannot be built.
        ObjectNotFound: If ``user`` is given and the object is unknown or not
            readable by the user.
        AccessDenied: If ``user`` is given and the object is only readable.
    """
    if user is not None:
        # Local import: permissions imports this package lazily as well.
        from testcanvas.utilities.permissions import AccessLevel, get_object_by_uid_for_user

        original = get_object_by_uid_for_user(user, uid, required=AccessLevel.WRITE)
    else:
        original = find_model_object_by_uid(uid)
    if original is None:
        raise ValueError(f"No object found with uid '{uid}'.")

    with transaction.atomic():
        if isinstance(original, ApplicationMap):
            return _clone_application_map(original)

        if isinstance(original, FlowNode):
            return _clone_flow_node(original)

        if isinstance(original, UserStory):
            # The copy stays on the same flow node as the original story.
            return _clone_user_story(original, original.flow_node, is_root=True)

        if isinstance(original, AcceptanceCriterion):
            # The copy stays on the same user story as the original criterion.
            return _clone_acceptance_criterion(original, original.user_story, is_root=True)

        if isinstance(original, TestCase):
            # The copy stays on the same criterion as the original test case.
            return _clone_test_case(original, original.acceptance_criterion, is_root=True)

    raise ValueError(f"Objects of type '{type(original).__name__}' cannot be duplicated.")


# --------------------------------------------------------------------------- #
# Cloners (one per model, from the top of the tree to the bottom)
# --------------------------------------------------------------------------- #

def _clone_application_map(original_map: ApplicationMap) -> ApplicationMap:
    """Copy a whole map: its graph, its nodes and all their user stories.

    Args:
        original_map: The map to duplicate.

    Returns:
        The new map, named ``copy_<original name>``.
    """
    # Create the new map with the same graph. Saving a map automatically
    # creates one FlowNode for every node found in the graph (see
    # ApplicationMap.sync_flow_nodes), so the nodes already exist afterwards.
    new_map = _copy_instance(
        original_map,
        name=_add_copy_prefix(original_map.name, max_length=150),
        graph_data=copy.deepcopy(original_map.graph_data),
    )

    # Complete every new node with the information the graph does not carry
    # (node type, sub-flow reference) and copy its user stories.
    for original_node in original_map.relational_nodes.all():
        new_node = new_map.relational_nodes.get(local_graph_id=original_node.local_graph_id)
        _copy_node_content(original_node, new_node)

    return new_map


def _clone_flow_node(original_node: FlowNode) -> FlowNode:
    """Copy a single node inside its own map, together with its user stories.

    A FlowNode only exists if the matching node exists in the map graph,
    so the copy is first added to the graph and then the map is saved: this
    creates the new FlowNode row automatically.

    Args:
        original_node: The node to duplicate.

    Returns:
        The new node, titled ``copy_<original title>``.

    Raises:
        ValueError: If the node is missing from the graph or the resulting
            graph is not valid.
    """
    application_map = original_node.application_map
    new_title = _add_copy_prefix(original_node.title, max_length=100)

    # Work on a copy of the graph, so the map is only changed when saved.
    graph_data = copy.deepcopy(application_map.graph_data)
    graph_nodes = graph_data["elements"]["nodes"]

    # Find the original node inside the graph.
    original_graph_node = _find_graph_node(graph_nodes, original_node.local_graph_id)
    if original_graph_node is None:
        raise ValueError(
            f"Node '{original_node.local_graph_id}' was not found in the graph of map '{application_map}'."
        )

    # Build the new graph node: same look and description, new id and name.
    # Edges are NOT copied: the new node starts unconnected.
    new_graph_id = _new_graph_node_id(graph_nodes)
    new_graph_node = copy.deepcopy(original_graph_node)
    new_graph_node["data"]["id"] = new_graph_id
    new_graph_node["data"]["value"] = new_graph_id  # required by NetworkX
    new_graph_node["data"]["name"] = new_title

    # Move the copy a little, so it does not sit on top of the original.
    if "position" in new_graph_node:
        new_graph_node["position"]["x"] += NODE_POSITION_OFFSET
        new_graph_node["position"]["y"] += NODE_POSITION_OFFSET

    graph_nodes.append(new_graph_node)

    # Make sure NetworkX can still read the graph before saving it.
    _check_graph_is_valid(graph_data)

    # Saving the map creates the new FlowNode from the new graph node.
    application_map.graph_data = graph_data
    application_map.save()

    new_node = application_map.relational_nodes.get(local_graph_id=new_graph_id)
    _copy_node_content(original_node, new_node)
    return new_node


def _clone_user_story(original_story: UserStory, target_node: FlowNode, is_root: bool = False) -> UserStory:
    """Copy a user story under ``target_node``, together with its criteria.

    Args:
        original_story: The story to duplicate.
        target_node: The node the copy must belong to.
        is_root: ``True`` when this story is the object the user asked to
            duplicate; only in that case the title gets the ``copy_`` prefix.

    Returns:
        The new user story.
    """
    new_title = original_story.title
    if is_root:
        new_title = _add_copy_prefix(original_story.title, max_length=150)

    new_story = _copy_instance(
        original_story,
        flow_node=target_node,
        title=new_title,
    )

    for original_criterion in original_story.criteria.all():
        _clone_acceptance_criterion(original_criterion, new_story)

    return new_story


def _clone_acceptance_criterion(
    original_criterion: AcceptanceCriterion,
    target_story: UserStory,
    is_root: bool = False,
) -> AcceptanceCriterion:
    """Copy an acceptance criterion under ``target_story``, with its test cases.

    Args:
        original_criterion: The criterion to duplicate.
        target_story: The user story the copy must belong to.
        is_root: ``True`` when this criterion is the object the user asked to
            duplicate. The copy then stays in the same user story, so its
            ``code`` gets the ``copy_`` prefix to keep it unique there.

    Returns:
        The new acceptance criterion.
    """
    new_code = original_criterion.code
    if is_root:
        existing_codes = target_story.criteria.values_list("code", flat=True)
        new_code = _free_copy_code(original_criterion.code, existing_codes)

    new_criterion = _copy_instance(
        original_criterion,
        user_story=target_story,
        code=new_code,
    )

    for original_test_case in original_criterion.test_cases.all():
        _clone_test_case(original_test_case, new_criterion)

    return new_criterion


def _clone_test_case(
    original_test_case: TestCase,
    target_criterion: AcceptanceCriterion,
    is_root: bool = False,
) -> TestCase:
    """Copy a test case under ``target_criterion``.

    Args:
        original_test_case: The test case to duplicate.
        target_criterion: The acceptance criterion the copy must belong to.
        is_root: ``True`` when this test case is the object the user asked to
            duplicate. The copy then stays in the same criterion, so its
            ``code`` gets the ``copy_`` prefix to keep it unique there.

    Returns:
        The new test case.
    """
    new_code = original_test_case.code
    if is_root:
        existing_codes = target_criterion.test_cases.values_list("code", flat=True)
        new_code = _free_copy_code(original_test_case.code, existing_codes)

    return _copy_instance(
        original_test_case,
        acceptance_criterion=target_criterion,
        code=new_code,
    )


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _copy_node_content(original_node: FlowNode, new_node: FlowNode) -> None:
    """Copy what the graph does not carry from one node to another.

    The graph only stores a node's name and description. The node type and the
    sub-flow reference live only in the database, so they are copied here.
    The sub-flow reference keeps pointing to the same map as the original: the
    referenced map is NOT duplicated. Finally all user stories are copied.

    Args:
        original_node: The node to read from.
        new_node: The freshly created node to complete.
    """
    new_node.node_type = original_node.node_type
    new_node.sub_flow = original_node.sub_flow
    new_node.save(update_fields=["node_type", "sub_flow"])

    for original_story in original_node.user_stories.all():
        _clone_user_story(original_story, new_node)


def _copy_instance(original, **changes):
    """Create and save a copy of ``original`` with some fields changed.

    All the regular fields are copied as they are, except:

    * the primary key, so the database creates a new row;
    * the ``uid`` field, so the model generates a new UID automatically.

    Args:
        original: The model instance to copy.
        **changes: Fields to set on the copy (e.g. the new parent or the new
            name), applied after the plain copy.

    Returns:
        The saved copy.
    """
    model_class = type(original)
    new_object = model_class()

    # Copy every regular field, one by one.
    for field in model_class._meta.concrete_fields:
        if field.primary_key or field.name == "uid":
            continue
        setattr(new_object, field.attname, getattr(original, field.attname))

    # Apply the requested changes (new parent, new name, ...).
    for field_name, value in changes.items():
        setattr(new_object, field_name, value)

    new_object.save()
    return new_object


def _add_copy_prefix(text: str, max_length: int) -> str:
    """Return ``text`` with the ``copy_`` prefix, cut to ``max_length``.

    Args:
        text: The original name or title.
        max_length: The maximum length allowed by the model field.

    Returns:
        The prefixed text, shortened if needed.
    """
    return (COPY_PREFIX + text)[:max_length]


def _free_copy_code(original_code: str, existing_codes) -> str:
    """Return a ``copy_`` code that is not used yet inside the same parent.

    The prefix is added once (``copy_AC-01``); if that code is already taken
    (the same object was duplicated before) it is added again
    (``copy_copy_AC-01``) until a free code is found.

    Args:
        original_code: The code of the object being duplicated.
        existing_codes: The codes already used inside the same parent.

    Returns:
        A free code starting with ``copy_``.

    Raises:
        ValueError: If the new code would be longer than the field allows.
    """
    used_codes = set(existing_codes)

    new_code = COPY_PREFIX + original_code
    while new_code in used_codes:
        new_code = COPY_PREFIX + new_code

    if len(new_code) > CODE_MAX_LENGTH:
        raise ValueError(
            f"Cannot duplicate '{original_code}': the new code '{new_code}' "
            f"is longer than {CODE_MAX_LENGTH} characters."
        )

    return new_code


def _find_graph_node(graph_nodes: list, node_id: str):
    """Return the graph node whose id is ``node_id``, or ``None``.

    Args:
        graph_nodes: The ``elements.nodes`` list of a map graph.
        node_id: The id to look for.

    Returns:
        The matching graph node dictionary, or ``None`` if not found.
    """
    for graph_node in graph_nodes:
        if str(graph_node["data"]["id"]) == str(node_id):
            return graph_node
    return None


def _new_graph_node_id(graph_nodes: list) -> str:
    """Return a node id (``n1``, ``n2``, ...) not used yet in the graph.

    Args:
        graph_nodes: The ``elements.nodes`` list of a map graph.

    Returns:
        A free node id.
    """
    used_ids = set()
    for graph_node in graph_nodes:
        used_ids.add(str(graph_node["data"]["id"]))

    number = 1
    while f"n{number}" in used_ids:
        number += 1
    return f"n{number}"


def _check_graph_is_valid(graph_data: dict) -> None:
    """Make sure NetworkX can rebuild the graph, as the map editor does.

    Args:
        graph_data: The graph in Cytoscape format.

    Raises:
        ValueError: If NetworkX cannot read the graph.
    """
    try:
        nx.cytoscape_graph(graph_data)
    except Exception as error:  # noqa: BLE001 - report any conversion problem
        raise ValueError(f"The duplicated graph is not valid: {error}") from error

