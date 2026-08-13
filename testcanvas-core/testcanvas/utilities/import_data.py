"""TestCanvas JSON importer (placeholder).
The structured-JSON importer was intentionally removed: Test Case management now
lives in the ``testcanvas_test_execution`` plugin and the import contract for
the reduced core (ApplicationMap -> FlowNode -> UserStory -> AcceptanceCriterion)
has yet to be defined.
Re-implement :func:`import_model_from_json` here once the new contract is agreed.
"""
from __future__ import annotations
from typing import Any
def import_model_from_json(payload: str | bytes) -> Any:
    """Import a structured TestCanvas JSON document.
    Placeholder: the previous implementation was removed while Test Cases moved
    to the ``testcanvas_test_execution`` plugin. Implement the new import
    contract here.
    Args:
        payload: Raw JSON text (``str`` or ``bytes``).
    Raises:
        NotImplementedError: Always, until the importer is re-implemented.
    """
    raise NotImplementedError("to implement")
