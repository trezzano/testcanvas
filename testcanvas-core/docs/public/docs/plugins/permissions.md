# Permissions in plugins

How to apply TestCanvas **collection permissions** in plugin code: custom
views, REST endpoints, import/export scripts, management commands and
background jobs.

!!! info "See also"
    [Collection permissions](../administration/collection-permissions.md)
    explains how administrators assign permissions.

---

## 1. Where permissions are enforced

TestCanvas enforces collection permissions at **application level**, not at
model level:

- the TestCanvas pages and services check permissions before showing or saving
  data;
- the **models and the Django ORM are not restricted**: `save()`, `delete()`
  and `ApplicationMap.objects.filter(...)` know nothing about the current user.

This is intentional: plugins keep full freedom on the data model. The
consequence is simple:

!!! warning
    **Every plugin entry point acting on behalf of a user must apply the
    permission API itself.** Code that uses the ORM directly bypasses every
    rule.

### The rules your plugin must respect

1. **Superusers** are unrestricted.
2. Other users only access the collections granted to them (directly or
   through a group) with **read** and/or **write**. Write implies read.
3. Grants **cascade down** the collection tree and to every flow it contains,
   including the whole chain
   `ApplicationMap → FlowNode → UserStory → AcceptanceCriterion → TestCase`.
4. **Flows without a collection** belong to a virtual *default collection*,
   readable and writable by **superusers only**.
5. Non-superusers can create flows and collections **only inside a writable
   collection** (no ungrouped flows, no top-level collections).

---

## 2. Common pitfalls

### Pitfall 1 — Not knowing who the user is

If your code runs without a Django user, or always as a superuser, permissions
cannot be applied:

| Approach | Effect |
|----------|--------|
| No user, raw ORM | Everybody can read and write everything. |
| Fixed **superuser** | Same as above, and no audit trail of who changed what. |

➡ Every operation must run on behalf of a real, authenticated Django `User`
(see [§ 3](#3-identifying-the-user)).

### Pitfall 2 — Flows created without a collection disappear

A flow created without a `collection` lands in the **default collection**
(superuser-only). A normal user who created it **can no longer see it**.

➡ Creation code must receive a **target collection** and check that the user
can write it (see [§ 5.1](#51-create-a-flow)).

### Pitfall 3 — Unchecked modifications

Any code that updates or deletes an existing object (flow, node, user story,
acceptance criterion, test case) must do it **only if the user has write
access** on the governing collection.

➡ Call `require_write(user, obj)` before every write (see
[§ 5.2](#52-modify-or-delete-an-existing-object)).

### Pitfall 4 — Listings that leak data

Lists, searches, statistics and exports must only include what the user can
read. Resolving an object by UID must not reveal objects of inaccessible
collections.

➡ Use `filter_maps` / `filter_collections` and `require_read` (see
[§ 5.3](#53-read-list-search)).

### Pitfall 5 — Moves and references

- Moving a flow to another collection needs write access on **both** the flow
  and the **target** collection.
- Moving a collection needs write access on it and on the new parent;
  non-superusers cannot move it to the top level.
- Referencing another flow as a **sub-flow** is allowed only if the user can
  **read** the referenced flow.

---

## 3. Identifying the user

| Context | How to get the user |
|---------|---------------------|
| Django view / REST endpoint | `request.user` (authenticated session or token). |
| Background job | Store the id of the user who started the job and reload that user when the job runs. |
| Script / management command | A `--user` option resolved to an active user, or a dedicated **service account**. |

### Service accounts

For automated processes, create a dedicated user (for example `import-bot`)
that is **not** superuser and **not** staff, and grant it only the collections
it needs. This keeps the impact of the automation limited and visible.

### Never

- Never run user-facing operations as a **superuser** just "to make it work".
- Never trust a user id received from an untrusted client: resolve the user
  from an authenticated session or token.

---

## 4. The permission API

Import everything from the public API: `from testcanvas import api` (see
[Python API](python-api.md)). The permission functions are a **pure domain
layer**: they never raise HTTP-specific exceptions (no `Http404`), so they are
safe to use from a view, a management command, a background job or any other
integration. Choosing the HTTP status (404 or 403) is up to your code — see
[§ 5.4](#54-error-handling).

### 4.1 Functions

| Function | Use |
|----------|-----|
| `is_unrestricted(user)` | `True` for active superusers. |
| `access_level(user, obj)` | Returns `AccessLevel.NONE` / `READ` / `WRITE`. The general-purpose check. |
| `can_read(user, obj)` / `can_write(user, obj)` | Boolean shortcuts over `access_level`. |
| `can_read_collection(user, c)` / `can_write_collection(user, c)` | Same, for a collection instance or id; `None` = default collection. |
| `require_read(user, obj)` / `require_write(user, obj)` | Raise `AccessDenied` (a `PermissionDenied` subclass) if access is insufficient; otherwise return the actual `AccessLevel`. |
| `filter_readable(user, qs, write=False)` | Restrict **any registered** queryset (collections, maps, flow nodes, user stories, acceptance criteria, test cases, or your own model — see [§ 4.2](#42-extending-the-system-to-your-own-models)). |
| `filter_maps(user, qs, write=False)` / `filter_collections(user, qs, write=False)` | Readable aliases of `filter_readable`. |
| `resolve_map(obj)` | Climb from a flow node, user story, acceptance criterion, test case (or a registered model) to the owning flow. |
| `get_access(user)` | The raw `CollectionAccess(readable, writable, unrestricted)`, cached on the user instance. |
| `clear_access_cache(user)` | Invalidate the cache after creating or moving collections. |

Good to know:

- `obj` can be any core artefact or any model registered as described in
  [§ 4.2](#42-extending-the-system-to-your-own-models): the governing
  collection is found automatically.
- `AccessLevel` is an `IntEnum` (`NONE < READ < WRITE`), so you can compare
  it: `access_level(user, obj) >= AccessLevel.READ`.
- `AccessDenied` carries the level the user actually has (`exc.level`). Use it
  to answer 404 (level `NONE`: the object must look non-existent) or 403
  (level `READ`: the object exists but is read-only).
- Access sets are cached on the **user instance**. In long-running processes,
  load a **fresh user** for each unit of work (or call `clear_access_cache`)
  so permission changes are picked up.

### 4.2 Extending the system to your own models

Register your plugin models so `filter_readable`, `can_read`, `can_write` and
`require_*` understand them. Pass **exactly one** resolver:

| Your model belongs to… | Use | Example |
|---|---|---|
| Something below a flow (e.g. a `TestRun` linked to a `TestCase`) | `resolve_map` | `TestRun` below |
| A collection directly (e.g. a per-collection board) | `resolve_collection` | `Board` below |

Register in `AppConfig.ready()` (models are importable there):

```python
# my_plugin/apps.py
from django.apps import AppConfig


class MyPluginConfig(AppConfig):
    name = "my_plugin"
    label = "my_plugin"

    def ready(self) -> None:
        """Register plugin models in the collection permission system."""
        from testcanvas import api

        from .models import Board, TestRun

        # Known limitation: the core registers its own models lazily, only
        # while the registry is still empty. Touch the registry first (lazy
        # queryset, no DB query) so the core models are registered before ours.
        api.filter_readable(None, api.ApplicationMapsCollection.objects.none())

        api.register_permission_model(
            TestRun,
            collection_path=(
                "test_case__acceptance_criterion__user_story"
                "__flow_node__application_map__collection_id"
            ),
            resolve_map=lambda run: api.resolve_map(run.test_case),
        )
        api.register_permission_model(
            Board,
            collection_path="collection_id",
            resolve_collection=lambda board: board.collection_id,
        )
```

!!! warning "Do not skip the first call"
    Without the `filter_readable(...)` line, registering a plugin model first
    leaves the registry non-empty, so the core models are never registered and
    permission checks on core objects stop working.

If you only need single-object checks (no queryset filtering), add a
`get_permission_map()` method to the model instead:

```python
from django.db import models
from testcanvas import api


class TestRun(models.Model):
    # Reference core models by string: plugins never import core models
    # into their model definitions.
    test_case = models.ForeignKey("testcanvas.TestCase", on_delete=models.CASCADE)

    def get_permission_map(self):
        """Return the ApplicationMap that governs access to this run."""
        return api.resolve_map(self.test_case)
```

---

## 5. Implementation patterns

!!! tip
    The core services (`api.create_application_map`, `api.update_artefact`,
    `api.delete_artefact`, …) already check permissions. Prefer them for
    writes. The patterns below show what to do when you write your own logic.

### 5.1 Create a flow

```python
from django.core.exceptions import PermissionDenied
from testcanvas import api


def create_flow(user, name: str, collection_id: int | None) -> api.ApplicationMap:
    """Create a flow inside a collection the user can write."""
    collection = None
    if collection_id is not None:
        collection = api.ApplicationMapsCollection.objects.filter(pk=collection_id).first()
    # None = default collection: only superusers may create ungrouped flows.
    if not api.can_write_collection(user, collection):
        raise PermissionDenied("Choose a collection you have write access to.")
    return api.ApplicationMap.objects.create(name=name, collection=collection)
```

- Make the target collection a **required** input for normal users.
- Offer the list of **writable collections**
  (`filter_collections(user, qs, write=True)`) so users pick a valid target.
- Imports of complete flows follow the same rule.

### 5.2 Modify or delete an existing object

```python
from testcanvas import api


def update_by_uid(user, uid: str, changes: dict):
    """Apply changes to any artefact identified by its UID."""
    obj = api.find_model_object_by_uid(uid)
    if obj is None:
        raise LookupError("Not found")
    api.require_write(user, obj)   # raises AccessDenied if insufficient
    for field, value in changes.items():
        setattr(obj, field, value)
    obj.save()
    return obj
```

- Apply the check to **every** write: create, update, delete, clone, link.
- Creating a child (for example a user story under a flow node) needs a write
  check on the **parent**.
- Moving a flow: `require_write(user, flow)` **and**
  `can_write_collection(user, target_collection)`.
- Sub-flow references: the referenced flow must satisfy `can_read(user, flow)`.

### 5.3 Read, list, search

```python
from testcanvas import api


def list_flows(user):
    """Return only the flows the user can read."""
    return api.filter_maps(user, api.ApplicationMap.objects.select_related("collection"))


def get_by_uid(user, uid):
    """Return an artefact by UID, hiding unreadable ones."""
    obj = api.find_model_object_by_uid(uid)
    if obj is None:
        raise LookupError("Not found")
    api.require_read(user, obj)    # unreadable raises AccessDenied(level=NONE)
    return obj
```

- Never start from `Model.objects.all()` for data shown to a user.
- Compute statistics and exports on filtered querysets only.

### 5.4 Error handling

`AccessDenied` is deliberately **not** tied to any transport. Your code
decides what to do with it, based on `exc.level`:

```python
from testcanvas import api


def handle_update(user, uid, changes):
    try:
        return update_by_uid(user, uid, changes)
    except api.AccessDenied as exc:
        if exc.level is api.AccessLevel.NONE:
            ...   # object does not exist for this user -> "Not found"
        else:
            ...   # object exists but is read-only -> "Forbidden"
```

| Exception | Meaning | Typical response |
|-----------|---------|-------------------|
| `AccessDenied` with `level == NONE` | Not readable | "Not found" (do not reveal that the object exists) |
| `AccessDenied` with `level == READ` | Readable but not writable | "Forbidden" |
| `ValidationError` | Invalid data | "Invalid data" plus messages |

In a Django view you can raise `django.http.Http404` or
`django.core.exceptions.PermissionDenied` yourself based on `exc.level`: this
is what the TestCanvas views do. Outside a view (scripts, jobs, other APIs),
map `AccessDenied` to your own error format.

---

## 6. Complete examples

### 6.1 A Django view in a plugin

```python
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from testcanvas import api


@login_required
def flow_summary(request, uid):
    """Show a read-only summary of a flow, with an edit link when allowed."""
    flow = get_object_or_404(api.ApplicationMap, uid=uid)
    try:
        api.require_read(request.user, flow)
    except api.AccessDenied as exc:
        if exc.level is api.AccessLevel.NONE:
            raise Http404("Flow not found.") from exc
        raise
    return render(request, "my_plugin/flow_summary.html", {
        "flow": flow,
        "can_write": api.can_write(request.user, flow),  # drives buttons
    })
```

```django
{% if can_write %}
    <a href="{% url 'my_plugin:flow_edit' flow.uid %}">Edit</a>
{% endif %}
```

!!! note
    Hiding buttons is only a convenience. Always repeat the check in the view
    that performs the write.

### 6.2 A management command that imports data

```python
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from my_plugin.services import create_flow  # see § 5.1


class Command(BaseCommand):
    """Import a flow on behalf of a given user."""

    help = "Create a flow in a collection, respecting collection permissions."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True)
        parser.add_argument("--collection", type=int, required=True)
        parser.add_argument("--name", required=True)

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(
            username=options["user"], is_active=True,
        ).first()
        if user is None:
            raise CommandError("Unknown or inactive user.")
        try:
            flow = create_flow(user, options["name"], options["collection"])
        except PermissionDenied as exc:
            raise CommandError(f"Forbidden: {exc}")
        self.stdout.write(self.style.SUCCESS(f"Created {flow.uid}"))
```

### 6.3 What different users get

Assume the tree `Sales / Checkout`, user *Mario* with **write** on `Sales`, and
user *Lucia* with **read** on `Checkout`:

| Operation | Mario | Lucia | Superuser |
|-----------|-------|-------|-----------|
| `list_flows` | Flows of `Sales` and `Checkout` | Flows of `Checkout` only | All flows |
| `create_flow(..., collection_id=checkout.pk)` | ✅ Created | ❌ `PermissionDenied` | ✅ Created |
| `create_flow(..., collection_id=None)` | ❌ `PermissionDenied` | ❌ `PermissionDenied` | ✅ Created (ungrouped) |
| `update_by_uid` on a `Checkout` flow | ✅ Updated | ❌ `AccessDenied(level=READ)` | ✅ Updated |
| `update_by_uid` on a `Marketing` flow | ❌ `AccessDenied(level=NONE)` | ❌ `AccessDenied(level=NONE)` | ✅ Updated |

---

## 7. Checklist

- [ ] Every operation runs on behalf of a real, authenticated Django `User`.
- [ ] Listings use `filter_maps` / `filter_collections` (or `filter_readable`
      for your own registered models).
- [ ] Single-object reads call `require_read`.
- [ ] Every write calls `require_write` (on the parent for creations).
- [ ] New flows go into a **writable collection** (no ungrouped flows for
      normal users).
- [ ] Moves and sub-flow references also check the destination.
- [ ] `AccessDenied` is mapped to a clear error (404-style for
      `level == NONE`, 403-style for `level == READ`).
- [ ] Long-running processes use a fresh user, or clear the cache, for each
      unit of work.
- [ ] Tests cover: a reader cannot write, a stranger cannot read, creation
      without collection is rejected for normal users, the superuser can do
      everything.

