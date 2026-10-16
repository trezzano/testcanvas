"""Public plugin API of TestCanvas (stable surface, semantic-versioned).

Plugins (MCP server, CLI tools, REST adapters…) must import **only** from this
module. Everything re-exported here is supported across minor releases;
anything else in ``testcanvas`` is an implementation detail.

The surface is grouped as follows:

* **Permissions** — access levels, checks and queryset filters.
* **UID utilities** — resolve artefact UIDs. Every artefact stores its UID in
  a field named ``uid`` (opaque string: never rely on its format).
* **Resolution** — resolve-and-check helpers that hide unreadable objects.
* **Services** — the single entry point for every write (permissions and
  ISTQB business rules included).
* **Serialization** — plain-dict representations shared by every transport.
* **Exceptions** — the domain errors a plugin must map to its own responses.

Example:
    >>> from testcanvas import api
    >>> story = api.get_object_by_uid_for_user(
    ...     user, uid, model=api.UserStory, required=api.AccessLevel.WRITE,
    ... )
    >>> api.create_acceptance_criteria(user, story, [{"code": "AC-1", "description": "..."}])
"""

from django.core.exceptions import ValidationError

from testcanvas.models import (
    AcceptanceCriterion,
    ApplicationMap,
    ApplicationMapsCollection,
    FlowNode,
    TestCase,
    UserStory,
)
from testcanvas.services import (
    BusinessRuleViolation,
    MapInUseAsSubflow,
    SubflowCannotOwnUserStories,
    create_acceptance_criteria,
    create_application_map,
    create_test_cases,
    create_user_stories,
    delete_artefact,
    deletion_preview,
    duplicate_by_uid,
    update_application_map,
    update_artefact,
)
from testcanvas.utilities.other_support import UID_MODELS, find_model_object_by_uid
from testcanvas.utilities.permissions import (
    AccessDenied,
    AccessLevel,
    CollectionAccess,
    ObjectNotFound,
    access_level,
    can_read,
    can_read_collection,
    can_write,
    can_write_collection,
    clear_access_cache,
    filter_collections,
    filter_maps,
    filter_readable,
    get_access,
    get_collection_for_user,
    get_object_by_uid_for_user,
    governing_collection_id,
    is_unrestricted,
    readable_or_none,
    register_permission_model,
    require,
    require_read,
    require_write,
    resolve_map,
)
from testcanvas.utilities.serialization import (
    serialize_acceptance_criterion,
    serialize_application_map,
    serialize_flow_node,
    serialize_flow_overview,
    serialize_test_case,
    serialize_user_story,
)

#: Version of the public plugin API (mirrors the package version).
API_VERSION = "1.1.0"

__all__ = [
    "API_VERSION",
    # Models (read-only usage; write through the services).
    "AcceptanceCriterion",
    "ApplicationMap",
    "ApplicationMapsCollection",
    "FlowNode",
    "TestCase",
    "UserStory",
    # Exceptions.
    "AccessDenied",
    "BusinessRuleViolation",
    "MapInUseAsSubflow",
    "ObjectNotFound",
    "SubflowCannotOwnUserStories",
    "ValidationError",
    # Permissions.
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
    "readable_or_none",
    "register_permission_model",
    "require",
    "require_read",
    "require_write",
    "resolve_map",
    # UID utilities and resolution (every artefact exposes ``obj.uid``).
    "UID_MODELS",
    "find_model_object_by_uid",
    "get_collection_for_user",
    "get_object_by_uid_for_user",
    # Services.
    "create_acceptance_criteria",
    "create_application_map",
    "create_test_cases",
    "create_user_stories",
    "delete_artefact",
    "deletion_preview",
    "duplicate_by_uid",
    "update_application_map",
    "update_artefact",
    # Serialization.
    "serialize_acceptance_criterion",
    "serialize_application_map",
    "serialize_flow_node",
    "serialize_flow_overview",
    "serialize_test_case",
    "serialize_user_story",
]

