"""TestCanvas JSON importer (placeholder).

The structured-JSON importer was intentionally removed: the import contract for
the core chain (ApplicationMap -> FlowNode -> UserStory -> AcceptanceCriterion
-> TestCase) has yet to be defined.

Re-implement :func:`import_model_from_json` here once the new contract is agreed.
"""
from __future__ import annotations
from typing import Any
def import_model_from_json(payload: str | bytes) -> Any:
    """Import a structured TestCanvas JSON document.

    Placeholder: the previous implementation was removed and the new import
    contract for the core chain (ApplicationMap -> FlowNode -> UserStory ->
    AcceptanceCriterion -> TestCase) has still to be defined.

    Args:
        payload: Raw JSON text (``str`` or ``bytes``).
    Raises:
        NotImplementedError: Always, until the importer is re-implemented.
    """
    raise NotImplementedError("to implement")
