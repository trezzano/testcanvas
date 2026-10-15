# Collection Permissions — Integration Guide for Plugins
Guide for developers of **external plugins and integrations** that read or
write TestCanvas data (custom views, REST endpoints, import/export scripts,
management commands, background jobs, …). It explains what the collection
permission system means for your code and how to use the core permission API
correctly.
See also: `collection-permissions-user-guide.md` — how permissions are
assigned by administrators.
---
## 1. Where permissions are enforced
TestCanvas enforces collection permissions at **application level**, not at
model level:
- the TestCanvas web pages call `testcanvas.utilities.permissions` before
  showing or saving data;
- the **models and the Django ORM are not restricted**: `save()`, `delete()`,
  `ApplicationMap.objects.filter(...)` know nothing about the current user.
This is intentional: plugins keep full freedom on the data model. The
consequence is that **every plugin entry point acting on behalf of a user must
apply the permission API itself**. Code that uses the ORM directly bypasses
every rule.
### The rules your plugin must respect
1. **Superusers** are unrestricted.
2. Other users only access the collections granted to them (directly or through
   a group) with **read** and/or **write** (write implies read).
3. Grants **cascade down** the collection tree and to every flow contained,
   including the whole chain
   `ApplicationMap → FlowNode → UserStory → AcceptanceCriterion → TestCase`.
4. **Flows without a collection** belong to a virtual *default collection*
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
| No user, raw ORM | everybody can read and write everything |
| Fixed **superuser** | same as above, and no audit trail of who changed what |
➡ Every operation must run on behalf of a real, authenticated **Django `User`**
(see §3).
### Pitfall 2 — Flows created without a collection disappear
A flow created without a `collection` lands in the **default collection**
(superuser-only). A normal user who created it **can no longer see it**.
➡ Creation code must receive a **target collection** and check that the user
can write it (see §5.1).
### Pitfall 3 — Unchecked modifications
Any code that updates or deletes an existing object (flow, node, User Story,
Acceptance Criterion, Test Case) must do it **only if the user has write
access** on the governing collection.
➡ Call `require_write(user, obj)` before every write (see §5.2).
### Pitfall 4 — Listings that leak data
Lists, searches, statistics and exports must only include what the user can
read. Resolving an object by UID must not reveal objects of inaccessible
collections.
➡ Use `filter_maps` / `filter_collections` and `require_read` (see §5.3).
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
| Django view / REST endpoint | `request.user` (authenticated session or token) |
| Background job | store the id of the user who started the job and reload that user when the job runs |
| Script / management command | a `--user` option resolved to an active user, or a dedicated **service account** |
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
Module: `testcanvas.utilities.permissions`
This module is a **pure domain layer**: it never raises or depends on
HTTP-specific exceptions (no `Http404`). It is safe to use from a view, a
management command, a background job or any other integration. Deciding what
HTTP status to answer (404 vs 403) is entirely up to your own code — see §5.4.
| Function | Use |
|----------|-----|
| `is_unrestricted(user)` | `True` for active superusers |
| `access_level(user, obj)` | returns `AccessLevel.NONE` / `READ` / `WRITE` — the general-purpose check |
| `can_read(user, obj)` / `can_write(user, obj)` | boolean shortcuts over `access_level` |
| `can_read_collection(user, c)` / `can_write_collection(user, c)` | same, restricted to a collection instance/id; `None` = default collection |
| `require_read(user, obj)` / `require_write(user, obj)` | raise `AccessDenied` (a plain `PermissionDenied` subclass) if access is insufficient; return the actual `AccessLevel` otherwise |
| `filter_readable(user, qs, write=False)` | restrict **any registered** queryset (collections, maps, FlowNode, UserStory, AcceptanceCriterion, TestCase, or a model you registered — see §4.2) |
| `filter_maps(user, qs, write=False)` / `filter_collections(user, qs, write=False)` | thin aliases of `filter_readable`, kept for readability |
| `resolve_map(obj)` | climb from FlowNode / UserStory / AcceptanceCriterion / TestCase (or a registered model) to the owning flow |
| `get_access(user)` | the raw `CollectionAccess(readable, writable, unrestricted)` (cached on the user instance) |
| `clear_access_cache(user)` | invalidate the cache after creating or moving collections |
Notes:
- `obj` can be an `ApplicationMapsCollection`, `ApplicationMap`, `FlowNode`,
  `UserStory`, `AcceptanceCriterion`, `TestCase`, or any model registered as
  described in §4.2: the governing collection is found automatically.
- `AccessLevel` is an `IntEnum` (`NONE < READ < WRITE`), so it can be compared
  directly: `access_level(user, obj) >= AccessLevel.READ`.
- `AccessDenied` carries the access level the user actually has
  (`exc.level`), which is exactly what you need to turn it into a 404 (level
  is `NONE`, object should look like it does not exist) or a 403 (level is
  `READ`, object exists but is read-only). See §5.4.
- The access sets are cached on the **user instance**. In long-running
  processes, load a **fresh user** for each unit of work (or call
  `clear_access_cache`) so permission changes are picked up.
### 4.2 Extending the system to your own models
If your plugin adds a model linked to a flow (e.g. a `TestRun` linked to a
`TestCase`), register it so `filter_readable` and `resolve_map` understand it:
```python
from testcanvas.utilities.permissions import register_permission_model, resolve_map
register_permission_model(
    TestRun,
    collection_path=(
        "test_case__acceptance_criterion__user_story"
        "__flow_node__application_map__collection_id"
    ),
    resolve_map=lambda run: resolve_map(run.test_case),
)
```
If you only need single-object checks (no queryset filtering), it is enough to
add a `get_permission_map()` method to the model instead:
```python
class TestRun(models.Model):
    test_case = models.ForeignKey(TestCase, on_delete=models.CASCADE)
    def get_permission_map(self):
        return resolve_map(self.test_case)
```
---
## 5. Implementation patterns
### 5.1 Create a flow
```python
from django.core.exceptions import PermissionDenied
from testcanvas.models import ApplicationMap, ApplicationMapsCollection
from testcanvas.utilities.permissions import can_write_collection
def create_flow(user, name: str, collection_id: int | None) -> ApplicationMap:
    """Create a flow inside a collection the user can write."""
    collection = None
    if collection_id is not None:
        collection = ApplicationMapsCollection.objects.filter(pk=collection_id).first()
    # None = default collection: only superusers may create ungrouped flows.
    if not can_write_collection(user, collection):
        raise PermissionDenied("Choose a collection you have write access to.")
    return ApplicationMap.objects.create(name=name, collection=collection)
```
- Make the target collection a **required** input for normal users.
- Offer the user the list of **writable collections**
  (`filter_collections(user, qs, write=True)`) so they can pick a valid target.
- Imports of complete flows follow the same rule.
### 5.2 Modify or delete an existing object
```python
from testcanvas.utilities.other_support import find_model_object_by_uid
from testcanvas.utilities.permissions import require_write
def update_by_uid(user, uid: str, changes: dict):
    """Apply changes to any artefact identified by its UID."""
    obj = find_model_object_by_uid(uid)
    if obj is None:
        raise LookupError("Not found")
    require_write(user, obj)   # raises AccessDenied if insufficient
    for field, value in changes.items():
        setattr(obj, field, value)
    obj.save()
    return obj
```
- Apply the check to **every** write: create, update, delete, clone, link.
- Creating a child (for example a User Story under a FlowNode) means a write
  check on the **parent**.
- Moving a flow: `require_write(user, flow)` **and**
  `can_write_collection(user, target_collection)`.
- Sub-flow references: the referenced flow must satisfy `can_read(user, flow)`.
### 5.3 Read, list, search
```python
from testcanvas.models import ApplicationMap
from testcanvas.utilities.other_support import find_model_object_by_uid
from testcanvas.utilities.permissions import filter_maps, require_read
def list_flows(user):
    """Return only the flows the user can read."""
    return filter_maps(user, ApplicationMap.objects.select_related("collection"))
def get_by_uid(user, uid):
    """Return an artefact by UID, hiding unreadable ones."""
    obj = find_model_object_by_uid(uid)
    if obj is None:
        raise LookupError("Not found")
    require_read(user, obj)    # unreadable raises AccessDenied(level=NONE)
    return obj
```
- Never start from `Model.objects.all()` for data shown to a user.
- Compute statistics and exports on filtered querysets only.
### 5.4 Error handling
`AccessDenied` is deliberately **not** tied to any transport. Your code
decides what to do with it, based on `exc.level`:
```python
from testcanvas.utilities.permissions import AccessDenied, AccessLevel, require_write
def handle_update(user, uid, changes):
    try:
        return update_by_uid(user, uid, changes)
    except AccessDenied as exc:
        if exc.level is AccessLevel.NONE:
            ...   # object does not exist for this user -> "Not found"
        else:
            ...   # object exists but is read-only -> "Forbidden"
```
| Exception | Meaning | Typical response |
|-----------|---------|-------------------|
| `AccessDenied` with `level == NONE` | not readable | "Not found" (do not reveal that the object exists) |
| `AccessDenied` with `level == READ` | readable but not writable | "Forbidden" |
| `ValidationError` | invalid data | "Invalid data" plus messages |
In a Django view you are of course free to raise `django.http.Http404` or
`django.core.exceptions.PermissionDenied` yourself based on `exc.level` — that
is exactly what TestCanvas's own views do internally. Outside a view (scripts,
jobs, other APIs), map `AccessDenied` to your own error format.
---
## 6. Complete examples
### 6.1 A Django view in a plugin
```python
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from testcanvas.models import ApplicationMap
from testcanvas.utilities.permissions import AccessDenied, AccessLevel, can_write, require_read
@login_required
def flow_summary(request, pk):
    """Show a read-only summary of a flow, with an edit link when allowed."""
    flow = get_object_or_404(ApplicationMap, pk=pk)
    try:
        require_read(request.user, flow)
    except AccessDenied as exc:
        if exc.level is AccessLevel.NONE:
            raise Http404("Flow not found.") from exc
        raise
    return render(request, "my_plugin/flow_summary.html", {
        "flow": flow,
        "can_write": can_write(request.user, flow),  # drive buttons in the template
    })
```
```django
{% if can_write %}
    <a href="{% url 'my_plugin:flow_edit' flow.pk %}">Edit</a>
{% endif %}
```
> Hiding buttons is only a convenience. Always repeat the check in the view
> that performs the write.
### 6.2 A management command that imports data
```python
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError
from my_plugin.services import create_flow  # see §5.1
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
        self.stdout.write(self.style.SUCCESS(f"Created {flow.flow_uid}"))
```
### 6.3 What different users get
Assume the tree `Sales / Checkout`, user *Mario* with **write** on `Sales`, and
user *Lucia* with **read** on `Checkout`:
| Operation | Mario | Lucia | Superuser |
|-----------|-------|-------|-----------|
| `list_flows` | flows of `Sales` and `Checkout` | flows of `Checkout` only | all flows |
| `create_flow(..., collection_id=checkout.pk)` | ✅ created | ❌ `PermissionDenied` | ✅ created |
| `create_flow(..., collection_id=None)` | ❌ `PermissionDenied` | ❌ `PermissionDenied` | ✅ created (ungrouped) |
| `update_by_uid` on a `Checkout` flow | ✅ updated | ❌ `AccessDenied(level=READ)` | ✅ updated |
| `update_by_uid` on a `Marketing` flow | ❌ `AccessDenied(level=NONE)` | ❌ `AccessDenied(level=NONE)` | ✅ updated |
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
- [ ] `AccessDenied` is mapped to a clear error for your context (404-style
      for `level == NONE`, 403-style for `level == READ`).
- [ ] Long-running processes use a fresh user, or clear the cache, for each
      unit of work.
- [ ] Tests cover: a reader cannot write, a stranger cannot read, creation
      without collection is rejected for normal users, the superuser can do
      everything.
