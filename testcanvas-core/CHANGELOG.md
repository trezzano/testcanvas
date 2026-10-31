# Changelog

All notable changes to `testcanvas-core` are documented here. The project
follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Removed (breaking)

- Statistics payload (`get_flow_statistics`, `get_collection_statistics`,
  `get_dashboard_statistics`): removed the flow-node traceability metrics
  `coverage.pure_nodes_with_user_stories`, `coverage.node_coverage_pct` and
  `gaps.pure_nodes_without_user_stories`. A flow node may be purely
  descriptive, so a node without user stories is not a traceability hole.
  Node counts remain available in `structure.flow_nodes`.
- Statistics `schema_version` bumped to `"2.0"`; public `api.API_VERSION`
  bumped to `"2.0.0"`.
- Button object widgets: removed the `htmx` and `target` options. A button is
  now always a plain link to a plugin page; the two keys are ignored, so a
  plugin still passing them gets a normal navigation.

### Fixed

- Object widgets: a malformed widget (not a dict, or a button with both `args`
  and `kwargs`) or a provider returning a failing generator no longer breaks
  the core page. The faulty contribution is skipped and logged.

### Changed

- Object widgets: a `get_object_widgets` that raises is now logged on the
  `testcanvas.plugins` logger instead of being skipped silently.

### Documentation

- Object widgets and plugin quickstart: `get_object_widgets` must be fast and
  read-only, examples identify objects by `uid`, `test_case` is listed among the
  object types, and plugins are told not to override core templates.

## [1.1.0] — 2026-10-16

Plugin-friendly public API: plugins can now resolve artefacts, enforce
collection permissions and apply the ISTQB business rules without
re-implementing any core logic.

### Added

- `testcanvas.api`: single, explicit public facade for plugins (permissions,
  UID utilities, services, serialization, exceptions). Plugins should import
  only from here.
- `testcanvas.services`: domain services, the single entry point for writes
  (used by both the web views and the plugins). Every service takes `user`
  first, enforces permissions (write on the **parent** when creating), runs
  `full_clean()` and is atomic.
  - `create_application_map`, `update_application_map` (moving a map requires
    write on both the map and the target collection; sub-flow references must
    target readable maps; node types are mirrored from `graph_data`).
  - `create_user_stories`, `create_acceptance_criteria`, `create_test_cases`
    (bulk, all-or-nothing).
  - `update_artefact`, `deletion_preview`, `delete_artefact`.
  - `duplicate_by_uid` re-exported (see *Changed*).
  - Exceptions `BusinessRuleViolation`, `SubflowCannotOwnUserStories`,
    `MapInUseAsSubflow`.
- `testcanvas.utilities.permissions`:
  - `ObjectNotFound` — raised for unknown **or** unreadable objects, with an
    identical message in both cases.
  - `get_object_by_uid_for_user`, `get_collection_for_user`,
    `readable_or_none` (all exported in `__all__`).
- `testcanvas.utilities.other_support.UID_MODELS`: the tuple of models that
  carry a `uid` field, in lookup order.
- `testcanvas.utilities.serialization`: plain-dict serializers exposing UIDs
  only (`uid` for the artefact, an explicit parent key named after the parent
  model — `application_map_uid`, `flow_node_uid`, `user_story_uid`,
  `acceptance_criterion_uid` — and `sub_flow_uid` for a referenced map), plus
  `serialize_flow_overview`
  (prefetch-optimised nested tree with sub-flow redaction).
- `testcanvas.views._permissions.get_object_by_uid_or_404` HTTP adapter.
- Documentation page "Writing a plugin".

### Changed

- **Breaking** — every core artefact now stores its UID in a single field
  named `uid` (was `flow_uid`, `node_uid`, `user_story_uid`, `ac_uid`,
  `tc_uid`). Migration `0012_rename_uid_fields` renames the columns and keeps
  the stored values. Read a UID with `obj.uid`, filter with
  `Model.objects.filter(uid=...)`. The prefix of each model is declared next
  to the field through `models.uid_field(prefix)`.
- **Breaking** — serialized payloads expose the artefact UID as `uid` and the
  direct parent under an explicit key named after the parent model, instead
  of a generic `parent_uid`, so payloads are self-describing (also for LLM
  clients through MCP):
  - `FlowNode` → `application_map_uid`
  - `UserStory` → `flow_node_uid`
  - `AcceptanceCriterion` → `user_story_uid`
  - `TestCase` → `acceptance_criterion_uid`
- Internal permission helpers (`_ModelSpec`, `_REGISTRY`, `_spec_for`,
  `_expand_descendants`, `_not_found`, `_enforce`, …) moved from
  `testcanvas.utilities.permissions` to the private module
  `testcanvas.utilities.permissions_support_func`. The public API is
  unchanged.
- **Behaviour change** — `find_model_object_by_uid` now returns `None` for a
  non-string, empty or blank `uid` instead of raising `ValueError`.
- `find_model_object_by_uid` runs one indexed query per table of `UID_MODELS`
  (at most 5). The first match wins, which assumes UIDs are unique across the
  artefact tables (documented, not enforced).

### Removed

- `get_uid(obj)` (use `obj.uid`), `uid_field_for(model)` (always `"uid"`) and
  the internal `_UID_LOOKUP` registry.
- `duplicate_by_uid(uid, *, user=None)`: when `user` is given, write access on
  the original is enforced. `user=None` keeps the previous behaviour.
- Web views (create/edit/delete of User Stories, Acceptance Criteria, Test
  Cases and maps, map save, UID resolver, clone) now go through the services
  and the new resolution helpers. Deleting a FlowNode through the services
  removes it from the map graph to keep the `graph_data` ↔ `FlowNode` sync.
- Creating a User Story on a SUBFLOW node is now rejected
  (`SubflowCannotOwnUserStories`).

## [1.0.0]

- Initial release.

