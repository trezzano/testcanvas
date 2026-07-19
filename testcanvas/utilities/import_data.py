"""
Importer for structured TestCanvas JSON documents.

This module turns a JSON payload shaped like the specification in
``docs/docs/json_model_format.md`` into the relational Django models:

    ApplicationMap -> FlowNode -> UserStory -> AcceptanceCriterion -> TestCase
                                                     (N:N) <----------

The public entry point is :func:`import_model_from_json`, which accepts a raw
JSON string. The root of the document may be **either**:

* a single object ``{...}`` (one complete model), or
* a **list** of such objects ``[{...}, {...}]`` (the format documented in
  ``json_model_format.md``).

Behaviour
---------
* The whole import runs inside a single database transaction. If *anything*
  fails (validation or a DB constraint) nothing is persisted.
* The document is **validated first** (structure, required fields, max lengths,
  unique codes and referential integrity of ``criteria_codes``) so we never hit
  avoidable database errors. All problems are collected and reported together
  through :class:`ImportValidationError`.
* If an :class:`~testcanvas.models.ApplicationMap` with the same ``name`` already
  exists it is **overwritten** (the previous map and its descendants are deleted
  and rebuilt) and a warning is emitted to inform the caller.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from django.db import transaction

from ..models import (
    AcceptanceCriterion,
    ApplicationMap,
    TestCase,
    UserStory,
)

# Allowed values for TestCase.status, derived from the model so the two never
# drift apart.
_VALID_STATUSES = {choice[0] for choice in TestCase.STATUS_CHOICES}

# Field length limits mirrored from the models (kept here so validation can
# report a clean error instead of letting the DB raise).
_MAX_MAP_NAME = 150
_MAX_LOCAL_GRAPH_ID = 50
_MAX_FLOWNODE_TITLE = 100
_MAX_US_CODE = 20
_MAX_US_TITLE = 150
_MAX_AC_CODE = 20
_MAX_TC_CODE = 20
_MAX_TC_TITLE = 150


class ImportValidationError(Exception):
    """Raised when a document cannot be imported.

    The individual, human-readable problems are available on :attr:`errors`.
    """

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__(f"{len(self.errors)} validation error(s)")


@dataclass
class _MapReport:
    """Per-ApplicationMap summary of what was written."""

    name: str
    overwritten: bool = False
    flow_nodes: int = 0
    user_stories: int = 0
    criteria: int = 0
    test_cases: int = 0


@dataclass
class ImportResult:
    """Outcome of a successful import."""

    maps: list[_MapReport] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Return a one-line-per-map, human-readable summary."""
        if not self.maps:
            return "Nothing was imported."
        return "\n".join(
            f"Imported '{m.name}' ({m.flow_nodes} flow nodes, "
            f"{m.user_stories} user stories, {m.criteria} criteria, "
            f"{m.test_cases} test cases)"
            for m in self.maps
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def import_model_from_json(payload: str | bytes) -> ImportResult:
    """Parse, validate and import a TestCanvas JSON document.

    Parameters
    ----------
    payload:
        Raw JSON text (``str``/``bytes``). The root may be a single object or a
        list of objects (see the module docstring).

    Returns
    -------
    ImportResult
        A summary of what was created, plus any non-blocking warnings.

    Raises
    ------
    ImportValidationError
        If the payload is not valid JSON, or if the document fails validation.
        In every failure case the transaction is rolled back and nothing is
        persisted.
    """
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ImportValidationError([f"Invalid JSON: {exc}"])

    # Normalise the root to a list of documents so both formats share one path.
    if isinstance(data, dict):
        documents = [data]
    elif isinstance(data, list):
        documents = data
    else:
        raise ImportValidationError(
            ["Root must be a JSON object or a list of objects."]
        )

    if not documents:
        raise ImportValidationError(["Document is empty: nothing to import."])

    # --- validate everything up-front (fail fast, report all problems) ------
    errors: list[str] = []
    for i, doc in enumerate(documents):
        prefix = f"document[{i}] " if len(documents) > 1 else ""
        _validate_document(doc, prefix, errors)
    if errors:
        raise ImportValidationError(errors)

    # --- persist inside a single transaction --------------------------------
    result = ImportResult()
    with transaction.atomic():
        for doc in documents:
            _import_document(doc, result)
    return result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _graph_node_ids(graph_data: Any) -> set[str]:
    """Return the set of node ids declared in ``graph_data.elements.nodes``."""
    ids: set[str] = set()
    if not isinstance(graph_data, dict):
        return ids
    elements = graph_data.get("elements")
    if not isinstance(elements, dict):
        return ids
    for node in elements.get("nodes", []) or []:
        if isinstance(node, dict):
            node_id = (node.get("data") or {}).get("id")
            if node_id is not None:
                ids.add(str(node_id))
    return ids


def _check_str(value: Any, *, required: bool, max_len: int | None,
               label: str, prefix: str, errors: list[str]) -> None:
    """Validate a string field, appending precise messages to ``errors``."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            errors.append(f"{prefix}{label} is required.")
        return
    if not isinstance(value, str):
        errors.append(f"{prefix}{label} must be a string.")
        return
    if max_len is not None and len(value) > max_len:
        errors.append(
            f"{prefix}{label} exceeds max length {max_len} (got {len(value)})."
        )


def _validate_document(doc: Any, prefix: str, errors: list[str]) -> None:
    """Validate a single document object, collecting problems into ``errors``."""
    if not isinstance(doc, dict):
        errors.append(f"{prefix}must be a JSON object.")
        return

    app = doc.get("application_map")
    if not isinstance(app, dict):
        errors.append(f"{prefix}'application_map' object is required.")
        # Without an application_map we cannot validate the rest meaningfully.
        return

    _check_str(app.get("name"), required=True, max_len=_MAX_MAP_NAME,
               label="application_map.name", prefix=prefix, errors=errors)

    graph_data = app.get("graph_data")
    if not isinstance(graph_data, dict):
        errors.append(f"{prefix}application_map.graph_data object is required.")
    graph_ids = _graph_node_ids(graph_data)

    # Collect every acceptance-criterion code declared in the document so we can
    # validate test-case references and detect duplicates.
    ac_codes: set[str] = set()
    us_codes: set[str] = set()

    flow_nodes = app.get("flow_nodes")
    if flow_nodes is None:
        flow_nodes = []
    if not isinstance(flow_nodes, list):
        errors.append(f"{prefix}application_map.flow_nodes must be a list.")
        flow_nodes = []

    for fi, fn in enumerate(flow_nodes):
        fp = f"{prefix}flow_nodes[{fi}] "
        if not isinstance(fn, dict):
            errors.append(f"{fp}must be an object.")
            continue

        local_id = fn.get("local_graph_id")
        _check_str(local_id, required=True, max_len=_MAX_LOCAL_GRAPH_ID,
                   label="local_graph_id", prefix=fp, errors=errors)
        _check_str(fn.get("title"), required=True, max_len=_MAX_FLOWNODE_TITLE,
                   label="title", prefix=fp, errors=errors)
        # A flow_node must map onto an existing graph node, otherwise
        # ApplicationMap.sync_flow_nodes() would delete it on save.
        if isinstance(local_id, str) and graph_ids and local_id not in graph_ids:
            errors.append(
                f"{fp}local_graph_id '{local_id}' does not match any "
                f"graph_data node id."
            )

        stories = fn.get("user_stories") or []
        if not isinstance(stories, list):
            errors.append(f"{fp}user_stories must be a list.")
            stories = []

        for si, us in enumerate(stories):
            sp = f"{fp}user_stories[{si}] "
            if not isinstance(us, dict):
                errors.append(f"{sp}must be an object.")
                continue
            code = us.get("code")
            _check_str(code, required=True, max_len=_MAX_US_CODE,
                       label="code", prefix=sp, errors=errors)
            _check_str(us.get("title"), required=True, max_len=_MAX_US_TITLE,
                       label="title", prefix=sp, errors=errors)
            if isinstance(code, str) and code:
                if code in us_codes:
                    errors.append(f"{sp}duplicate User Story code '{code}'.")
                else:
                    us_codes.add(code)

            criteria = us.get("acceptance_criteria") or []
            if not isinstance(criteria, list):
                errors.append(f"{sp}acceptance_criteria must be a list.")
                criteria = []
            for ci, ac in enumerate(criteria):
                cp = f"{sp}acceptance_criteria[{ci}] "
                if not isinstance(ac, dict):
                    errors.append(f"{cp}must be an object.")
                    continue
                ac_code = ac.get("code")
                _check_str(ac_code, required=True, max_len=_MAX_AC_CODE,
                           label="code", prefix=cp, errors=errors)
                _check_str(ac.get("text"), required=True, max_len=None,
                           label="text", prefix=cp, errors=errors)
                if isinstance(ac_code, str) and ac_code:
                    if ac_code in ac_codes:
                        errors.append(
                            f"{cp}duplicate Acceptance Criterion code "
                            f"'{ac_code}'."
                        )
                    else:
                        ac_codes.add(ac_code)

    # -- test cases (object level, because of the M2M relationship) ----------
    test_cases = doc.get("test_cases")
    if test_cases is None:
        test_cases = []
    if not isinstance(test_cases, list):
        errors.append(f"{prefix}test_cases must be a list.")
        test_cases = []

    tc_codes: set[str] = set()
    for ti, tc in enumerate(test_cases):
        tp = f"{prefix}test_cases[{ti}] "
        if not isinstance(tc, dict):
            errors.append(f"{tp}must be an object.")
            continue
        tc_code = tc.get("test_code")
        _check_str(tc_code, required=True, max_len=_MAX_TC_CODE,
                   label="test_code", prefix=tp, errors=errors)
        _check_str(tc.get("title"), required=True, max_len=_MAX_TC_TITLE,
                   label="title", prefix=tp, errors=errors)
        _check_str(tc.get("steps"), required=True, max_len=None,
                   label="steps", prefix=tp, errors=errors)
        _check_str(tc.get("expected_result"), required=True, max_len=None,
                   label="expected_result", prefix=tp, errors=errors)

        if isinstance(tc_code, str) and tc_code:
            if tc_code in tc_codes:
                errors.append(f"{tp}duplicate Test Case code '{tc_code}'.")
            else:
                tc_codes.add(tc_code)

        status = tc.get("status")
        if status is not None and status not in _VALID_STATUSES:
            allowed = ", ".join(sorted(_VALID_STATUSES))
            errors.append(f"{tp}invalid status '{status}'. Allowed: {allowed}.")

        criteria_codes = tc.get("criteria_codes")
        if criteria_codes is None:
            criteria_codes = []
        if not isinstance(criteria_codes, list):
            errors.append(f"{tp}criteria_codes must be a list.")
            criteria_codes = []
        for ref in criteria_codes:
            if not isinstance(ref, str):
                errors.append(f"{tp}criteria_codes entries must be strings.")
                continue
            if ref not in ac_codes:
                errors.append(
                    f"{tp}references unknown Acceptance Criterion code '{ref}'."
                )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _import_document(doc: dict, result: ImportResult) -> None:
    """Persist a single, already-validated document object."""
    app = doc["application_map"]
    name = app["name"]

    report = _MapReport(name=name)

    # Overwrite an existing map with the same name (delete + rebuild). Deleting
    # the ApplicationMap cascades to FlowNode -> UserStory -> AcceptanceCriterion.
    existing = ApplicationMap.objects.filter(name=name)
    if existing.exists():
        report.overwritten = True
        existing.delete()
        result.warnings.append(
            f"ApplicationMap '{name}' already existed and was overwritten."
        )

    # Creating the map persists graph_data; ApplicationMap.save() then runs
    # sync_flow_nodes(), which materialises the FlowNode rows from the graph.
    application_map = ApplicationMap.objects.create(
        name=name,
        graph_data=app.get("graph_data") or {},
    )

    # Map local_graph_id -> FlowNode (created by sync_flow_nodes on save).
    flow_by_id = {
        fn.local_graph_id: fn
        for fn in application_map.relational_nodes.all()
    }
    report.flow_nodes = len(flow_by_id)

    # criterion code -> AcceptanceCriterion instance (for wiring the M2M later).
    criterion_by_code: dict[str, AcceptanceCriterion] = {}

    for fn in app.get("flow_nodes") or []:
        flow_node = flow_by_id.get(fn["local_graph_id"])
        if flow_node is None:
            # Should never happen: validation guarantees the id exists in the
            # graph, and sync_flow_nodes creates a FlowNode for every graph node.
            continue

        for us in fn.get("user_stories") or []:
            story = UserStory.objects.create(
                flow_node=flow_node,
                code=us["code"],
                title=us["title"],
                description=us.get("description", "") or "",
            )
            report.user_stories += 1

            for ac in us.get("acceptance_criteria") or []:
                criterion = AcceptanceCriterion.objects.create(
                    user_story=story,
                    code=ac["code"],
                    text=ac["text"],
                )
                criterion_by_code[ac["code"]] = criterion
                report.criteria += 1

    # -- test cases + M2M links ---------------------------------------------
    for tc in doc.get("test_cases") or []:
        try:
            test_case, _created = TestCase.objects.update_or_create(
                test_code=tc["test_code"],
                defaults={
                    "title": tc["title"],
                    "preconditions": tc.get("preconditions", "") or "",
                    "steps": tc["steps"],
                    "expected_result": tc["expected_result"],
                    "status": tc.get("status", "TO_EXECUTE") or "TO_EXECUTE",
                },
            )
        except:
            pass
        linked = [
            criterion_by_code[code]
            for code in (tc.get("criteria_codes") or [])
            if code in criterion_by_code
        ]
        test_case.criteria.set(linked)
        report.test_cases += 1

    result.maps.append(report)

