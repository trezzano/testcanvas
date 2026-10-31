# Object Widgets — User Guide

This guide explains, from a **user / plugin author** point of view, how the
`get_object_widgets` extension point lets an installed plugin add small pieces
of interface (called **widgets**) onto TestCanvas core objects — without ever
touching the core code.

If you want to understand how the mechanism is built internally, read the
companion document **Object Widgets — Developer Guide**.

---

## 1. What object widgets are

A **widget** is a small, self-contained piece of UI that a plugin contributes
to a core page. The core renders it for you using safe, pre-styled Bootstrap
partials. You never write HTML: you only describe *what* you want to show, and
the core decides *how* to show it.

Widgets are attached to a specific **core object family** (an *object type*):

| Object type            | Where it appears                              |
| ---------------------- | --------------------------------------------- |
| `application_map`      | The application map / flow editor header      |
| `flow_node`            | A single flow node page                       |
| `user_story`           | A user story page                             |
| `acceptance_criterion` | An acceptance criterion page                  |
| `test_case`            | A test case page                              |

Widgets are rendered **in the order you return them**, so you control the layout
simply by ordering the list.

```mermaid
flowchart LR
    subgraph Plugin
        A["get_object_widgets()"]
    end
    subgraph Core["TestCanvas Core"]
        B["collect_object_widgets()"]
        C["Normalise & validate"]
        D["Render Bootstrap partials"]
    end
    Page["Core page<br/>(flow node, user story, ...)"]

    A -- "list of widget dicts" --> B --> C --> D --> Page
```

---

## 2. The four widget types

You can currently contribute four widget types. Each is a plain Python
dictionary with a `type` key plus the fields that type understands.

### 2.1 `progress` — a progress bar with an optional comment

Use it to show a measurable value (coverage, completion, ...).

| Field        | Required | Default   | Meaning                                          |
| ------------ | -------- | --------- | ------------------------------------------------ |
| `type`       | ✅       | —         | Must be `"progress"`                             |
| `value`      | ✅       | —         | Current amount (number)                          |
| `max`        | ❌       | `100`     | Maximum amount                                   |
| `label`      | ❌       | `""`      | Caption shown above the bar                      |
| `class_type` | ❌       | `primary` | Bootstrap colour (`success`, `warning`, `danger`, ...) |
| `show_value` | ❌       | `True`    | Print the percentage inside the bar              |
| `title`      | ❌       | `""`      | Tooltip on the whole widget                      |

```python
{
    "type": "progress",
    "label": "Test coverage",
    "value": 7,
    "max": 10,
    "class_type": "success",
}
```

### 2.2 `text` — a short caption or note

| Field        | Required | Default | Meaning                              |
| ------------ | -------- | ------- | ------------------------------------ |
| `type`       | ✅       | —       | Must be `"text"`                     |
| `text`       | ✅       | —       | The content to show                  |
| `icon`       | ❌       | `""`    | Glyph shown before the text          |
| `class_type` | ❌       | `muted` | Bootstrap text colour                |
| `strong`     | ❌       | `False` | Render bold                          |

```python
{
    "type": "text",
    "icon": "ℹ️",
    "text": "Coverage is computed from linked test cases.",
}
```

### 2.3 `divider` — a separator line

Use it to group your widgets into tidy sections. It has no required field.

| Field   | Required | Default | Meaning                          |
| ------- | -------- | ------- | -------------------------------- |
| `type`  | ✅       | —       | Must be `"divider"`              |
| `label` | ❌       | `""`    | Optional caption centered on it  |

```python
{"type": "divider"}
{"type": "divider", "label": "Actions"}
```

### 2.4 `button` — a link styled as a Bootstrap button

A button opens a page. The core reverses the URL for you (you pass a **URL
name**, never a hard-coded URL) and can hide the button behind a permission.

An action that changes data belongs on a **plugin page** with a form submitted
by `POST`: the button only leads there.

| Field        | Required | Default     | Meaning                                        |
| ------------ | -------- | ----------- | ---------------------------------------------- |
| `type`       | ✅       | —           | Must be `"button"`                             |
| `label`      | ✅       | —           | Visible text                                   |
| `url_name`   | ✅       | —           | Django URL name to reverse                     |
| `args`       | ❌       | `[]`        | Positional args for the URL                    |
| `kwargs`     | ❌       | `None`      | Keyword args for the URL (not together with `args`) |
| `icon`       | ❌       | `""`        | Glyph shown before the label                   |
| `class_type` | ❌       | `secondary` | Bootstrap button colour                        |
| `permission` | ❌       | `None`      | Django permission required to see the button   |

```python
{
    "type": "button",
    "label": "Open in My Plugin",
    "url_name": "my_plugin:object_detail",
    "args": [obj.uid],
    "icon": "🔗",
    "class_type": "primary",
}
```

!!! warning "Hiding a button does not protect the page"
    `permission` only checks a **Django permission** and only decides whether
    the button is shown. For collection permissions use `api.can_write(request.user, obj)`
    in the hook, and always check access again in the view the button opens:
    anyone can type its URL.

---

## 3. How to contribute widgets

Add a `get_object_widgets` method to your plugin's `AppConfig`. The core calls
it for every core object it renders and passes you three arguments:

- `object_type` — one of the object types in the table above,
- `obj` — the concrete core instance being rendered,
- `request` — the current HTTP request (used for permission checks).

Return a **list of widget dicts**. Return an empty list when you have nothing to
show for that object: this is how a plugin decides, object by object, whether a
button appears.

The hook runs **on every render** of the object, including after a save, inside
the core request. Two rules follow:

- **Keep it fast.** A slow hook slows down every detail page of the core. Avoid
  calls to external services, or cache their result in your plugin.
- **Keep it read-only.** The hook only decides what to show: never change `obj`
  or any other data. Changes happen in your plugin's views.

```python
from django.apps import AppConfig


class MyPluginConfig(AppConfig):
    name = "my_plugin"

    def get_object_widgets(self, object_type, obj, request):
        # Only enrich flow nodes; ignore everything else.
        if object_type != "flow_node":
            return []

        return [
            {
                "type": "progress",
                "label": "Completion",
                "value": 40,
                "class_type": "warning",
            },
            {"type": "divider"},
            {
                "type": "button",
                "label": "Open in My Plugin",
                "url_name": "my_plugin:object_detail",
                "args": [obj.uid],
                "class_type": "primary",
            },
        ]
```

That's it — install the app in `INSTALLED_APPS` and the widgets appear. No core
file needs to change.

---

## 4. A complete real example

A **stats** plugin contributes a coverage bar and a "View report" button to each
flow node, and a coverage bar to the whole map. This is what its
`get_object_widgets` produces for a flow node:

```mermaid
flowchart TB
    subgraph Node["Flow node page"]
        P["progress — Test coverage 7/10 (green)"]
        D["divider"]
        B["button — 📊 View report"]
    end
    P --> D --> B
```

The colour of the bar changes with the value: green at ≥ 80%, yellow at ≥ 50%,
red below. The button only appears on flow nodes, because maps have no per-node
report page.

---

## 5. Good to know (safety rules)

The core protects itself and you:

- **A broken plugin never breaks the page.** If your `get_object_widgets`
  raises, or a widget is malformed (for example not a dict), the core skips it,
  logs the error on the `testcanvas.plugins` logger and keeps rendering.
- **Unknown widget types are ignored.** If you misspell `type`, that widget is
  dropped instead of breaking the layout. Nothing is logged.
- **Styling is whitelisted and text is escaped.** `class_type` only accepts a
  whitelist of Bootstrap colours and text values are auto-escaped. Do not pass
  `mark_safe` values: they would bypass the escaping.
- **Invalid buttons are dropped.** A missing `url_name`, an unreversible URL, or
  a failed permission check simply hides that button. Nothing is logged, so
  check these first when a button does not appear.
- **The slot self-hides.** If no plugin contributes anything, no empty area is
  shown.

These rules protect the page from mistakes, not from the plugin itself: a plugin
runs in the same Python process as the core. Respecting the
[plugin rules](plugin-quickstart.md#rules-always-true) is what keeps the core
safe.

```mermaid
flowchart TD
    W["Widget dict from plugin"] --> T{"Known type?"}
    T -- "no" --> X["Skipped"]
    T -- "yes" --> N{"Valid payload?"}
    N -- "no" --> X
    N -- "yes" --> R["Rendered with Bootstrap partial"]
```

---

## 6. Checklist before shipping a widget

- [ ] `get_object_widgets` is defined on your `AppConfig`.
- [ ] It returns a **list of dicts** (empty list when nothing to show).
- [ ] It is fast and read-only.
- [ ] Each dict has a valid `type` (`progress`, `text`, `divider`, `button`).
- [ ] Buttons pass a `url_name` (never a hard-coded URL) and identify objects by
      `uid`.
- [ ] The view opened by a button checks permissions again.
- [ ] `class_type` uses a Bootstrap colour token only.
- [ ] Widgets are ordered the way you want them to appear.
- [ ] Your app is listed in `INSTALLED_APPS`.


