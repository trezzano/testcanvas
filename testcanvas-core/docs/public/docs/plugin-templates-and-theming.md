# Plugin templates and theming

How to make the pages of a plugin look and behave like TestCanvas pages, using
plain Bootstrap 5 and the TestCanvas theme.

!!! abstract "TL;DR"
    1. Your plugin layout **extends** `testcanvas/bases/base_page.html`.
    2. Add your stylesheet in the `extra_css` block. Do **not** load Bootstrap,
       HTMX or `testcanvas.css` again.
    3. In your CSS, use the `--tc-*` variables, not hard-coded colors.
    4. Choose the page width with the `wrap_class` block, not with Bootstrap
       `container` classes.

## 1. What you get for free

When a template extends `testcanvas/bases/base_page.html`, the page already
contains:

| Feature | Provided by | You must not |
|---|---|---|
| Bootstrap 5.3 CSS + JS bundle | `base.html` | load Bootstrap again |
| TestCanvas theme (`css/testcanvas.css`, `--tc-*` variables) | `base.html` | copy theme values into your CSS |
| User theme override (`testcanvas-custom-theme.css`), linked **last** | `base.html` | link it yourself |
| Shared navbar (with your `nav_items`) | `base.html` | build your own navbar |
| Flash messages as toasts (`django.contrib.messages`) | `base.html` | render `messages` yourself |
| HTMX 1.9 + CSRF header on every HTMX request (`hx-headers` on `<body>`) | `base.html` | add the CSRF header again |
| Global HTMX spinner (opt out with class `hx-no-spinner`) | `base.html` | add a per-request spinner |
| Full-page spinner (add class `full-page-spinner` to a link) | `base.html` | — |
| Page header (breadcrumb, `<h1>`, top-right link) + centered content area | `base_page.html` | — |

**Prerequisite:** the project must register the TestCanvas context processor,
otherwise the navbar and the user theme are silently missing (see
[Project prerequisites](plugin-quickstart.md#0-project-prerequisites)).

## 2. CSS load order

```text
1. Bootstrap 5                     (base.html)
2. css/testcanvas.css              (base.html, declares every --tc-* variable)
3. css/fonts-geist.css, page-spinner.css
4. {% block extra_css %}           ← YOUR plugin stylesheets
5. testcanvas-custom-theme.css     (only if the project provides it)
```

Consequences:

- Your CSS can **use** every `--tc-*` and `--bs-*` variable.
- Your CSS **overrides** Bootstrap and the core theme rules.
- The project's custom theme **overrides your CSS**. Because your rules read
  `--tc-*` variables, they follow the custom theme automatically.

## 3. Blocks reference

### `testcanvas/bases/base.html`

| Block | Content | Default |
|---|---|---|
| `html_lang` | `lang` attribute of `<html>` | `LANGUAGE_CODE` |
| `title` | `<title>` text | `TestCanvas` |
| `extra_css` | extra `<link>`/`<style>` in `<head>` | empty |
| `body_class` | CSS classes on `<body>` | empty |
| `navbar` | shared navbar (override with empty content to hide it) | navbar for authenticated users |
| `messages` | toast messages | toasts |
| `body` | page body (`base_page.html` fills it) | empty |
| `extra_js` | extra `<script>` at the end of `<body>`, after Bootstrap and HTMX | empty |

### `testcanvas/bases/base_page.html` (extends `base.html`)

| Block | Content | Typical value |
|---|---|---|
| `crumbs` | small breadcrumb above the `<h1>` | `<div class="crumbs"><a href="…">Plugin</a></div>` |
| `page_heading` | `<h1>` text | `My plugin` |
| `header_link` | top-right link(s) of the header | `<a class="header-link" href="…">← Back</a>` |
| `wrap_class` | width modifier of the content area | `wrap-narrow`, `wrap-wide` or empty |
| `content` | page body | your HTML |

## 4. Recommended plugin layout

Create **one** layout per plugin, e.g. `my_plugin/templates/my_plugin/base.html`.
Every page of the plugin extends it.

```django
{% extends "testcanvas/bases/base_page.html" %}
{% load static %}

{# Title: the suffix stays even when a page sets its own title. #}
{% block title %}{% block plugin_title %}My plugin{% endblock %} · TestCanvas{% endblock %}

{# Plugin CSS is always loaded; pages add more CSS in "plugin_css". #}
{% block extra_css %}
    <link rel="stylesheet" href="{% static 'my_plugin/my_plugin.css' %}">
    {% block plugin_css %}{% endblock %}
{% endblock %}

{% block body_class %}my-plugin-body{% endblock %}

{# Pages fill only the breadcrumb content, the wrapper keeps the core style. #}
{% block crumbs %}<div class="crumbs">{% block plugin_crumbs %}{% endblock %}</div>{% endblock %}

{% block header_link %}
    <a class="header-link" href="{% url 'my_plugin:index' %}">My plugin home</a>
{% endblock %}

{% block wrap_class %}wrap-wide{% endblock %}
```

A page of the plugin:

```django
{% extends "my_plugin/base.html" %}

{% block plugin_title %}Reports{% endblock %}
{% block plugin_crumbs %}<a href="{% url 'my_plugin:index' %}">My plugin</a>{% endblock %}
{% block page_heading %}Reports{% endblock %}

{% block content %}
<div class="card">
    <div class="card-body">Plain Bootstrap markup, themed by TestCanvas.</div>
</div>
{% endblock %}

{% block extra_js %}
<script src="{% static 'my_plugin/reports.js' %}"></script>
{% endblock %}
```

!!! warning "Why nested `plugin_*` blocks?"
    If a page overrides `extra_css` directly, it **replaces** the plugin
    stylesheet declared in the plugin layout. Nested blocks (`plugin_css`
    inside `extra_css`) let pages add CSS without losing it. The same applies
    to `title` and `crumbs`. Alternative: call `{{ block.super }}` inside the
    overridden block.

## 5. Page width

`content` is rendered inside `<div class="wrap {% block wrap_class %}">`.

| `wrap_class` | Max width | Use for |
|---|---|---|
| *(empty)* | 900px | forms, detail pages |
| `wrap-narrow` | 700px | small forms |
| `wrap-wide` | 1200px | lists, tables |
| your own class | your choice | e.g. full-width boards (see below) |

Full width for a specific page:

```css
/* my_plugin.css */
.wrap.my-plugin-full { max-width: none; }
```

```django
{% block wrap_class %}my-plugin-full{% endblock %}
```

!!! danger "Do not"
    Do not wrap `content` in Bootstrap `container` / `container-fluid`: `.wrap`
    already sets width, margins and padding, and the two stack up.

## 6. Writing plugin CSS

Use the theme variables (full list in [Custom theme](custom-theme.md#variables-reference)).
Add a fallback value so the rule still works if a variable is missing.

| Need | Variable |
|---|---|
| page background | `--tc-bg` |
| card / panel / input background | `--tc-surface` |
| hover background, secondary panels | `--tc-hover` |
| borders | `--tc-border`, `--tc-border-strong` |
| main / secondary text | `--tc-text`, `--tc-text-muted` |
| primary color (navbar, primary buttons) | `--tc-ink` |
| accent (focus, active, highlight) | `--tc-signal`, `--tc-signal-soft`, `--tc-signal-tint` |
| status colors | `--tc-success-*`, `--tc-error-*`, `--tc-warning-*`, `--tc-info-*`, `--tc-neutral-*` |
| radius | `--tc-radius`, `--tc-radius-lg` |
| transitions | `--tc-transition` |
| fonts | `--tc-font-sans`, `--tc-font-heading`, `--tc-font-mono` |

```css
/* Good: follows the theme and any custom theme. */
.my-plugin-card {
    background: var(--tc-surface, #fff);
    border: 1px solid var(--tc-border, #dee2e6);
    border-radius: var(--tc-radius-lg, 6px);
}

/* Bad: ignores the theme. */
.my-plugin-card { background: #fff; border: 1px solid #ddd; }
```

Rules:

- Prefix every plugin class with the plugin name (`.my-plugin-…`) to avoid
  clashes with the core and other plugins.
- Bootstrap components (`btn btn-primary`, `card`, `table`, `form-control`,
  `badge`…) are already themed: use them as they are.
- Only the classes listed in [Stable CSS classes](custom-theme.md#stable-css-classes-for-plugins)
  are a public contract. Do not style other core classes.

## 7. Static files and templates naming

Namespace everything with the plugin label, as Django recommends:

```text
my_plugin/
├── static/my_plugin/my_plugin.css      → {% static 'my_plugin/my_plugin.css' %}
└── templates/my_plugin/base.html       → "my_plugin/base.html"
```

Third-party libraries not shipped by the core (jQuery, DataTables, SortableJS,
Trix…) are loaded by the plugin pages that need them, in `plugin_css` /
`extra_js`.

## 8. HTMX partials

Templates returned to HTMX requests (fragments swapped into the page) must
**not** extend any layout: they are plain fragments. The CSRF header and the
spinner are already handled by the page that contains them.

## 9. Test it

```python
from django.test import TestCase
from django.urls import reverse


class MyPluginLayoutTests(TestCase):
    """Plugin pages use the core layout and load the theme before plugin CSS."""

    def test_page_uses_core_layout(self):
        # Log in a user first (the navbar and most pages need authentication).
        response = self.client.get(reverse("my_plugin:index"))
        self.assertTemplateUsed(response, "testcanvas/bases/base_page.html")
        html = response.content.decode()
        self.assertLess(html.find("css/testcanvas.css"), html.find("my_plugin/my_plugin.css"))
```

## 10. Checklist

- [ ] The plugin layout extends `testcanvas/bases/base_page.html`.
- [ ] No second copy of Bootstrap, HTMX or `testcanvas.css`.
- [ ] Plugin CSS is added in `extra_css` through a nested block.
- [ ] Plugin CSS uses `--tc-*` variables with fallbacks; no hard-coded colors.
- [ ] Width chosen with `wrap_class`; no `container` around the content.
- [ ] Classes, static files and templates are namespaced with the plugin label.
- [ ] HTMX fragments do not extend a layout.
- [ ] A test checks the layout and the CSS order.

Reference implementations in the sandbox:

- `testcanvas_kanban/templates/testcanvas_kanban/base.html` — full-width board,
  extra libraries (SortableJS, Trix, DataTables), HTMX fragments.
- `testcanvas_stats/templates/testcanvas_stats/base.html` — read-only pages,
  breadcrumb and actions mapped onto the core header, theme status colours.

