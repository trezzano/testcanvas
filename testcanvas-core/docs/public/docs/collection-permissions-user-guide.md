# Collection Permissions — User Guide

This guide explains how to control **who can see** and **who can edit** the
application flows of TestCanvas by assigning permissions to
**collections**.

---

## 1. Key concepts

| Concept | Meaning |
|---------|---------|
| **Collection** | A folder that groups application flows. Collections can be nested (folder / sub-folder). |
| **Read** | The user can open the collection, its flows and every artefact inside them (nodes, User Stories, Acceptance Criteria, Test Cases), but cannot change anything. |
| **Write** | The user can also create, edit, clone and delete. **Write always includes read.** |
| **Grantee** | The permission is assigned either to a single **user** or to a **group** (all its members inherit it). |

### The rules in a nutshell

1. **Superusers see and edit everything.** For them the system behaves as if
   no permission existed.
2. **Other users only see what has been explicitly granted** to them (directly
   or through one of their groups).
3. **Permissions cascade downwards.** A permission set on a collection also
   applies to all its sub-collections and to every flow they contain.
4. **Flows without a collection** belong to a virtual *default collection*
   that only superusers can see and edit.

```
Sales                 ← "Mario: Write"   → Mario writes everything below
├── Checkout          ← (inherited)      → Mario writes
│   └── Payment       ← (inherited)      → Mario writes
Marketing             ← nothing          → Mario does not see it
(flows without collection)               → superusers only
```

---

## 2. How to assign a permission

Permissions are managed from the **Django admin** by a superuser.

1. Open the admin (`/admin/`).
2. Go to **Application Maps Collections** and open the collection.
3. At the bottom of the page, in the **Collection Permissions** section, add a
   row:
    - choose **either** a *User* **or** a *Group* (never both);
    - tick **Can read** and/or **Can write**.
4. Save.

> Ticking only **Can write** automatically enables **Can read** too.

To review every assignment at once, use the **Collection Permissions** page of
the admin: it lists all grants and can be filtered by collection, read or
write.

### Tips

- Prefer **groups** (e.g. *QA Team*, *Business Analysts*) to individual users:
  adding a person to a group is enough to give them all the related access.
- Assign permissions **as high as possible** in the tree: they cascade to all
  sub-collections automatically.
- A user can hold several grants (direct and via groups): the **widest access
  wins**.

---

## 3. What users see

### Users with read access

- The flow list and the collections tree only show the readable items.
- Parent collections they have no access to are shown greyed out, only to keep
  the tree structure; they cannot be opened.
- The flow editor opens in **read-only mode**: no *Save*, *Clone*, *Delete*
  nor *Operations* panel; nodes cannot be moved and fields are locked.
- User Story / Acceptance Criterion / Test Case pages show the data with
  locked fields and without create / edit / delete buttons.

### Users with write access

- Everything above, plus all editing actions.
- **New flows** must be created inside a collection they can write.
- **New collections** can only be created *inside* a writable collection (not
  at the top level).
- A flow can only be moved to another writable collection; it cannot be left
  without a collection.
- A collection can only be moved under another writable collection.
- A collection that still contains flows (also in its sub-collections) cannot
  be deleted: move or delete the flows first.

### Superusers only

- Creating top-level collections and flows without a collection.
- The **Field settings** page (global optional fields configuration).
- Managing the permissions themselves (Django admin).

---

## 4. Access denied

- Opening something you cannot read answers **"Not found" (404)**: the system
  does not reveal that the object exists.
- Trying to modify something you can only read answers **"Forbidden" (403)**.
- Searching an object by **UID** follows exactly the same rules.

---

## 5. FAQ

**A user cannot see a flow. Why?**
The flow is in a collection (or sub-tree) where neither the user nor any of
their groups has a grant, or the flow has no collection at all
(superuser-only).

**I removed a grant but the user still sees the flow.**
Check the user's **groups** and the **parent collections**: an inherited grant
from above or from a group still applies.

**Can I give access to a single flow?**
No: permissions are set on collections. Put the flow in a dedicated
(sub-)collection and grant access to it.

