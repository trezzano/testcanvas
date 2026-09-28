"""Explicit catalogue of user-toggleable optional fields (Option A).

This module is the single source of truth that distinguishes *optional* fields
— extra attributes a user can turn on or off globally — from *core* fields,
which are always shown. Core fields are simply everything **not** listed here.

Keeping the catalogue explicit (instead of inferring it from nullable columns)
avoids misclassifying structural fields as optional and keeps the settings
page, the dynamic forms and the detail templates in agreement.

Extending the catalogue is a two-step change: add an entry here **and** ship the
matching model field. A coherence test asserts every declared name exists on its
model, so the two never drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OptionalFieldSpec:
    """Describe one optional field exposed in the project settings page.

    Attributes:
        name: The model field name (must exist on the target model).
        label: Human-readable label shown in the settings page and forms.
    """

    name: str
    label: str


# Catalogue keyed by model class name. Extend this to expose more optional
# fields; a matching model field must exist (enforced by a coherence test).
OPTIONAL_FIELDS: dict[str, list[OptionalFieldSpec]] = {
    "UserStory": [
        OptionalFieldSpec("story_points", "Story points"),
        OptionalFieldSpec("risk_level", "Risk level"),
        OptionalFieldSpec("status", "Status"),
    ],
    "AcceptanceCriterion": [
        OptionalFieldSpec("moscow_priority", "MoSCoW priority"),
        OptionalFieldSpec("verification_method", "Verification method"),
    ],
    "TestCase": [
        OptionalFieldSpec("execution_type", "Execution type"),
        OptionalFieldSpec("automation_status", "Automation status"),
        OptionalFieldSpec("test_level", "Test level"),
        OptionalFieldSpec("test_type", "Test type"),
        OptionalFieldSpec("estimated_duration_minutes", "Estimated duration (minutes)"),
    ],
}


def get_optional_field_specs(model_name: str) -> list[OptionalFieldSpec]:
    """Return the optional field specs declared for a model.

    Args:
        model_name: The model class name (e.g. ``"TestCase"``).

    Returns:
        The list of :class:`OptionalFieldSpec`, empty when none are declared.
    """
    return OPTIONAL_FIELDS.get(model_name, [])


def get_visible_optional_field_names(model_name: str, project=None) -> list[str]:
    """Return the ordered names of optional fields visible globally.

    A field is visible only when a ``FieldVisibilityPreference`` row exists with
    ``is_visible=True``. Missing rows mean "hidden", so the system starts "clean"
    and fields are enabled from the settings page.

    Args:
        model_name: The model class name (e.g. ``"TestCase"``).
        project: Deprecated parameter, ignored (kept for backward compatibility).

    Returns:
        The optional field names to show, in catalogue order.
    """
    # Imported lazily to avoid a circular import at module load time.
    from testcanvas.models import FieldVisibilityPreference

    specs = get_optional_field_specs(model_name)
    if not specs:
        return []

    visible = set(
        FieldVisibilityPreference.objects.filter(
            target_model=model_name,
            is_visible=True,
        ).values_list("field_name", flat=True)
    )
    # Preserve catalogue order rather than DB order for a stable UI.
    return [spec.name for spec in specs if spec.name in visible]


def resolve_project_for(obj) -> None:
    """Deprecated: field visibility is now global, not per-project.

    This function is kept for backward compatibility but always returns ``None``.
    Forms and views can call ``get_visible_optional_field_names()`` directly
    without passing a project.

    Args:
        obj: Ignored (for backward compatibility with existing code).

    Returns:
        Always ``None``.
    """
    return None


