# Custom theme (CSS)

TestCanvas ships with a light theme based on **CSS custom properties**
(variables). You can restyle the whole UI from your own Django project by
adding **one plain CSS file**. You do not need a build step, Sass or npm.

## How it works

TestCanvas loads its stylesheets in this order:

1. Bootstrap 5
2. `testcanvas.css`, the default theme. It declares every `--tc-*` variable.
3. Page-specific stylesheets
4. **`testcanvas-custom-theme.css`**, your file, if it exists.

TestCanvas looks for your file through Django's staticfiles finders. If it finds
the file, it adds a `<link>` tag after its own stylesheets. The CSS cascade then
gives priority to your values. If the file is missing, no tag is added. You get
no 404 error and no error from `ManifestStaticFilesStorage`.

The detection runs in the context processor
`testcanvas.context_processors.app_context`: it must be listed in
`TEMPLATES[0]["OPTIONS"]["context_processors"]`, otherwise the file is never
linked.

Plugin pages that extend `testcanvas/bases/base_page.html` receive the theme
and your custom file too: their stylesheets are loaded in step 3, so your
file still wins.

!!! note
    The file name is fixed: `testcanvas-custom-theme.css`, placed at the
    **root** of a static directory (not inside a sub-folder).

## Quick start

### 1. Create the file

Put the file in a directory that Django serves as static files, for example:

```text
my_project/
├── manage.py
├── my_project/
│   └── settings.py
└── static/
    └── testcanvas-custom-theme.css   ← your theme
```

and make sure the directory is listed in your settings:

```python
# settings.py
STATICFILES_DIRS = [BASE_DIR / "static"]
```

The `static/` folder of one of your own apps works too
(`my_app/static/testcanvas-custom-theme.css`).

!!! tip
    A fully commented starting point is shipped with TestCanvas:
    `testcanvas/static/css/testcanvas-custom-theme.example.css`.
    Copy it, rename it to `testcanvas-custom-theme.css` and uncomment what
    you need.

### 2. Override only what you need

```css
/* static/testcanvas-custom-theme.css */
:root {
    --tc-ink:    #003366;   /* navbar & primary buttons */
    --tc-signal: #FF9900;   /* accent: focus ring, active link, badge */
    --tc-signal-text: #B35F00;
    --tc-signal-tint: #FFF1DE;
}
```

Any variable you do not define keeps its default value.

### 3. Reload

- **Development (`DEBUG = True`):** reload the page. TestCanvas detects new
  files on each request.
- **Production (`DEBUG = False`):** run `python manage.py collectstatic` and
  restart the application server. TestCanvas detects the file once per process
  and caches the result.

## Variables reference

### Brand

| Variable | Default | Used for |
|---|---|---|
| `--tc-ink` | `#111111` | Navbar background, primary buttons, strong text |
| `--tc-ink-hover` | `#333333` | Hover of elements filled with `--tc-ink` |
| `--tc-on-ink` | `#FFFFFF` | Text and icons on `--tc-ink` (navbar, primary button) |
| `--tc-signal` | `#FF4081` | Accent: focus ring, active nav link, logo badge, spinner |
| `--tc-signal-text` | `#C2185B` | Accent used as text on light backgrounds (links, codes) |
| `--tc-signal-tint` | `#FFE4EE` | Light accent background: selected rows, code chips |

### Neutrals

| Variable | Default | Used for |
|---|---|---|
| `--tc-bg` | `#F7F7F8` | Page background |
| `--tc-surface` | `#FFFFFF` | Cards, tables, inputs, drawers |
| `--tc-border` | `#E1E1E5` | Subtle borders |
| `--tc-border-strong` | `#CBCBD1` | Input and secondary-button borders |
| `--tc-text` | `#18181B` | Main text |
| `--tc-text-muted` | `#6B6B76` | Secondary text, hints, table headers |
| `--tc-hover` | `#EFEFF1` | Hover background |

### Status

Each status has a text color and a background color. In the UI, color always
appears together with an icon and text.

| Status | Text variable | Background variable | Defaults |
|---|---|---|---|
| Passed / success | `--tc-success-text` | `--tc-success-bg` | `#0A7A3D` / `#E3F4EA` |
| Failed / error | `--tc-error-text` | `--tc-error-bg` | `#D92D20` / `#FDE8E6` |
| Blocked / warning | `--tc-warning-text` | `--tc-warning-bg` | `#B54708` / `#FEF0C7` |
| Info | `--tc-info-text` | `--tc-info-bg` | `#175CD3` / `#E3EEFD` |
| To execute / neutral | `--tc-neutral-text` | `--tc-neutral-bg` | `#6B6B76` / `#EFEFF1` |

`--tc-on-status` (`#FFFFFF`) sets the text color on solid status fills, for
example when you hover a danger button.

### Typography

| Variable | Default |
|---|---|
| `--tc-font-sans` | `'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif` |
| `--tc-font-heading` | `'Inter Tight', 'Inter', system-ui, sans-serif` |
| `--tc-font-mono` | `'Geist Mono', ui-monospace, 'SF Mono', Consolas, monospace` |

### Shape & motion

| Variable | Default | Used for |
|---|---|---|
| `--tc-radius` | `4px` | Buttons, inputs, badges |
| `--tc-radius-lg` | `6px` | Cards, editors, panels |
| `--tc-transition` | `0.15s ease` | Hover/focus transitions |

### Derived tokens (advanced)

TestCanvas computes these from the variables above with `color-mix()`, so they
change automatically when you change the base variables. Override them only for
fine-tuning.

| Variable | Default |
|---|---|
| `--tc-focus-ring` | 3px ring of `--tc-signal` at 20% |
| `--tc-signal-soft` | `--tc-signal` at 15% |
| `--tc-on-ink-soft` | `--tc-on-ink` at 15% (navbar hover) |
| `--tc-shadow` | `0 4px 12px rgba(0, 0, 0, 0.1)` |

### Bootstrap

TestCanvas maps its variables onto Bootstrap's variables (`--bs-primary`,
`--bs-body-bg`, ...), so Bootstrap components follow your theme. CSS cannot
compute `--bs-primary-rgb` from a hex value, so set it yourself when you change
`--tc-ink`:

```css
:root {
    --tc-ink: #003366;
    --bs-primary-rgb: 0, 51, 102;
}
```

## Examples

### Corporate colors

```css
:root {
    --tc-ink:          #0B3D2E;
    --tc-ink-hover:    #145A44;
    --tc-signal:       #2BB673;
    --tc-signal-text:  #1E7F50;
    --tc-signal-tint:  #E1F6EB;
    --bs-primary-rgb:  11, 61, 46;
}
```

### Custom fonts

Load the font in your theme file, then point the variables to it:

```css
@import url("https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600&display=swap");

:root {
    --tc-font-sans:    'Poppins', system-ui, sans-serif;
    --tc-font-heading: 'Poppins', system-ui, sans-serif;
}
```

!!! warning
    Put `@import` at the very top of the file, before any other rule.

### Dark theme (starting point)

```css
:root {
    --tc-bg:            #121214;
    --tc-surface:       #1C1C20;
    --tc-border:        #2E2E35;
    --tc-border-strong: #3F3F48;
    --tc-text:          #F2F2F5;
    --tc-text-muted:    #A1A1AA;
    --tc-hover:         #26262C;

    --tc-ink:           #000000;
    --tc-ink-hover:     #26262C;
    --tc-signal-text:   #FF7AA8;
    --tc-signal-tint:   #3A1E2A;
}
```

!!! note
    Bootstrap components that do not use these variables may need extra rules,
    for example `data-bs-theme="dark"` or specific overrides. Check the pages
    you use most.

### Extra rules

You can add any CSS rule to the same file. Use the variables where possible so
your rules stay consistent with the theme:

```css
.app-navbar {
    background: linear-gradient(90deg, var(--tc-ink), var(--tc-signal));
}
```

!!! warning
    TestCanvas does not treat CSS class names as a public API. Variables are
    stable across releases. Rules that target internal classes may need to be
    updated after an upgrade. The only exception is the short list below.

## Stable CSS classes for plugins

Plugin templates may use these classes. They are kept stable across minor
releases. Every other core class is internal.

| Class | Where | Purpose |
|---|---|---|
| `wrap-narrow`, `wrap-wide` | `wrap_class` block of `base_page.html` | width of the content area |
| `crumbs` | `crumbs` block of `base_page.html` | breadcrumb text style |
| `header-link` | `header_link` block of `base_page.html` | top-right header link |
| `full-page-spinner` | any `<a>` | show the full-page spinner while the next page loads |
| `hx-no-spinner` | any HTMX element (or ancestor) | hide the global HTMX spinner for that request |

Bootstrap 5 classes are always allowed: Bootstrap is themed through the
`--bs-*` mapping. How to style plugin pages:
[Plugin templates and theming](plugin-templates-and-theming.md).

## Troubleshooting

| Symptom | Check |
|---|---|
| Nothing changes | File name must be exactly `testcanvas-custom-theme.css`, at the root of a static directory. Check that `testcanvas.context_processors.app_context` is registered. |
| A plugin page ignores the theme | The plugin layout must extend `testcanvas/bases/base_page.html` and its CSS must use `--tc-*` variables. |
| Works in dev, not in prod | Run `collectstatic` and restart the server (detection is cached when `DEBUG = False`). |
| Only some colors change | Make sure you set the related variables (e.g. `--tc-signal-text` and `--tc-signal-tint` together with `--tc-signal`). |
| Bootstrap primary color unchanged | Set `--bs-primary-rgb` as an `R, G, B` triplet. |
| Old colors still visible | Hard-refresh the browser (`Ctrl+Shift+R`) to bypass the cache. |
| Is my file detected? | Run `python manage.py findstatic testcanvas-custom-theme.css`. |

