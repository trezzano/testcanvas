# Writing a plugin

This page describes the **public Python API** of `testcanvas-core` (since
version 1.1.0). A plugin (MCP server, CLI, REST adapter, web pages…) must never
re-implement permissions or ISTQB business rules: it calls the core and only
adapts the results to its own transport.

!!! tip "Where to start"
    For the full list of setup steps (settings, `AppConfig`, URLs, navbar,
    widgets, templates, tests) read the [Plugin quickstart](plugin-quickstart.md)
    first. This page covers only the Python API.

| Topic | Guide |
|---|---|
| Setup steps, in order | [Plugin quickstart](plugin-quickstart.md) |
| Navbar link | [Navbar](navbar-plugin-setup.md) |
| Widgets on core pages | [Object widgets — user guide](object-widgets-user-guide.md) |
| Permissions in depth, plugin models | [Collection permissions — integration](collection-permission-integration.md) |
| Templates, CSS, theme | [Plugin templates and theming](plugin-templates-and-theming.md) |

## 1. Import only from `testcanvas.api`

```python
from testcanvas import api
```

Everything re-exported by `testcanvas.api` (see its `__all__`) is supported
across minor releases. Anything else (`testcanvas.models`,
`testcanvas.utilities.*`, `testcanvas.services`…) is an implementation detail.

| Group | Names (all in `testcanvas.api`) |
|---|---|
| Models (read only; write through services) | `ApplicationMapsCollection`, `ApplicationMap`, `FlowNode`, `UserStory`, `AcceptanceCriterion`, `TestCase` |
| Exceptions | `ObjectNotFound`, `AccessDenied`, `BusinessRuleViolation`, `MapInUseAsSubflow`, `SubflowCannotOwnUserStories`, `ValidationError` |
| Permissions | `AccessLevel`, `can_read`, `can_write`, `require`, `require_read`, `require_write`, `filter_readable`, `filter_maps`, `filter_collections`, `register_permission_model`, `resolve_map`, … |
| UIDs | `UID_MODELS`, `get_object_by_uid_for_user`, `find_model_object_by_uid`, `get_collection_for_user`, `get_object_url` |
| Services (writes) | see § 4 |
| Serialization | see § 5 |
| Statistics (read only) | `get_dashboard_statistics`, `get_collection_statistics`, `get_flow_statistics` |

In plugin **models**, reference core models by string, not by import:

```python
test_case = models.ForeignKey("testcanvas.TestCase", on_delete=models.CASCADE)
```

## 2. Permission rules (summary)

- Superusers see and modify everything.
- Other users get access only through collection grants (user or group),
  which cascade down the collection tree and to the whole ISTQB chain
  (`ApplicationMap → FlowNode → UserStory → AcceptanceCriterion → TestCase`).
- Write implies read.
- Maps without a collection (the "default collection") are superuser-only.
- Creating a child requires write access on the **parent**.
- Moving a map requires write access on the map **and** on the target
  collection.
- A SUBFLOW reference may only target a map the user can read.

The full rules are in [Collection permissions — integration](collection-permission-integration.md).

Plugin models that must follow the same rules are registered with
`api.register_permission_model(...)` in `AppConfig.ready()`. Read the known
limitation in [§ 4.2 of the integration guide](collection-permission-integration.md#42-extending-the-system-to-your-own-models)
before doing it.

## 3. UIDs

Every core artefact (`ApplicationMap`, `FlowNode`, `UserStory`,
`AcceptanceCriterion`, `TestCase`) stores its compact, globally unique UID in
the same field: `uid`. Read it with `obj.uid`, filter with
`Model.objects.filter(uid=...)`. `api.UID_MODELS` lists the models carrying a
`uid`.

!!! warning "No format assumptions"
    A UID is an **opaque string**. Never parse it, never rely on a prefix or a
    length, never infer the artefact type from it. Use the API instead.

| Function | Purpose |
|----------|---------|
| `api.get_object_by_uid_for_user(user, uid, *, model=None, required=READ)` | Resolve + check access in one call (recommended). |
| `api.find_model_object_by_uid(uid)` | Raw lookup, **no permission check**; returns `None` for unknown/invalid input. |
| `api.get_collection_for_user(user, collection_id, required=READ)` | Resolve + check a collection (`None` = default collection). |
| `api.readable_or_none(user, obj)` | Redact related objects (e.g. sub-flows). |

```python
story = api.get_object_by_uid_for_user(
    user, uid, model=api.UserStory, required=api.AccessLevel.WRITE,
)
```

## 4. Services (all writes)

Every service takes `user` first, enforces permissions, runs `full_clean()`
and is atomic.

| Service | Notes |
|---------|-------|
| `create_application_map(user, *, name, graph_data=None, description="", collection=None)` | Write on the collection. |
| `update_application_map(user, map, *, graph_data=None, description=None, name=None, collection=...)` | Omit `collection` to keep it; `None` moves to the default collection. |
| `create_user_stories(user, flow_node, items)` | Bulk, all-or-nothing. Rejects SUBFLOW nodes. |
| `create_acceptance_criteria(user, user_story, items)` | Bulk, all-or-nothing. |
| `create_test_cases(user, acceptance_criterion, items)` | Bulk, all-or-nothing. |
| `update_artefact(user, obj, changes, allowed_fields)` | Partial update; UIDs and structural fields are never updatable. |
| `deletion_preview(obj)` | UIDs of every descendant removed by the cascade. |
| `delete_artefact(user, obj)` | Returns the preview of what was deleted. |
| `duplicate_by_uid(uid, *, user=None)` | Pass `user` to enforce write access. |

On a bulk validation error the raised `ValidationError` carries an
`item_index` attribute with the position of the faulty item.

## 5. Serialization

`serialize_application_map`, `serialize_flow_node(obj, *, user=None)`,
`serialize_user_story`, `serialize_acceptance_criterion`,
`serialize_test_case` return plain dicts exposing UIDs (never internal
primary keys). `uid` is the artefact itself; the direct parent is exposed
under an explicit key named after the parent model:

| Serializer | Parent key |
|------------|------------|
| `serialize_application_map` | — (a map has no parent) |
| `serialize_flow_node` | `application_map_uid` (plus `sub_flow_uid` for the referenced map) |
| `serialize_user_story` | `flow_node_uid` |
| `serialize_acceptance_criterion` | `user_story_uid` |
| `serialize_test_case` | `acceptance_criterion_uid` |

`serialize_flow_overview(user, map, *, include_test_cases=False)` returns the
nested tree with sub-flows redacted for users who cannot read them.

## 6. Exceptions and recommended responses

| Exception | Meaning | HTTP | MCP / JSON |
|-----------|---------|------|-----------|
| `ObjectNotFound` | Unknown **or** unreadable object | 404 | `{"ok": false, "message": str(exc)}` |
| `AccessDenied` (`level == READ`) | Readable but not writable | 403 | `{"ok": false, "message": str(exc)}` |
| `AccessDenied` (`level == NONE`) | Not readable (direct checks only) | 404 | treat as "not found" |
| `BusinessRuleViolation` (and subclasses) | ISTQB rule broken | 400 / 409 | `{"ok": false, "message": str(exc)}` |
| `ValidationError` | Invalid data | 400 | `{"ok": false, "message": "; ".join(exc.messages)}` |

A minimal adapter:

```python
def guarded(call, *args, **kwargs):
    try:
        return {"ok": True, "result": call(*args, **kwargs)}
    except api.ObjectNotFound as exc:
        return {"ok": False, "message": str(exc)}
    except api.AccessDenied as exc:
        message = "Not found." if exc.level == api.AccessLevel.NONE else str(exc)
        return {"ok": False, "message": message}
    except api.BusinessRuleViolation as exc:
        return {"ok": False, "message": str(exc)}
    except api.ValidationError as exc:
        return {"ok": False, "message": "; ".join(exc.messages)}
```

