# Plugin quickstart

Start here. This page lists **every** step to build a TestCanvas plugin, in
order, and links to the detailed guide for each step.

A plugin is a normal Django app installed next to the `testcanvas` core app.
It adds features (pages, models, MCP tools, statistics…) **without changing
the core**.

!!! info "Reference implementation"
    `sandbox/testcanvas_kanban` follows every step of this page.

## Rules (always true)

1. Import the core **only** from `testcanvas.api` (`from testcanvas import api`).
2. Reference core models by string in relations: `"testcanvas.TestCase"`.
3. Identify core objects by `uid` (opaque string), never by primary key.
4. Every action done for a user goes through the permission API.
5. The core never imports a plugin. Installing or removing a plugin requires
   no core change.
6. Plugin pages extend `testcanvas/bases/base_page.html` and use the `--tc-*`
   theme variables.
7. Do not override core templates: a copy stops receiving core updates and can
   break silently. Add widgets to core pages, and put anything else on a plugin
   page.

Background: [ISTQB strategy and plugin architecture](istqb-strategy-and-plugin-architecture.md).

## 0. Project prerequisites

Done once per Django project that hosts TestCanvas.

```python
# <your_project>/settings.py
INSTALLED_APPS = [
    # ... django.contrib apps ...
    "testcanvas",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # Required: navbar links, branding, custom theme detection.
                "testcanvas.context_processors.app_context",
            ],
        },
    },
]

# Optional: project-level static files (e.g. testcanvas-custom-theme.css).
STATICFILES_DIRS = [BASE_DIR / "static"]
```

```python
# <your_project>/urls.py
from django.urls import include, path

urlpatterns = [
    # Plugin routes first, the core is mounted at the site root.
    path("my-plugin/", include("my_plugin.urls")),
    path("", include("testcanvas.urls")),
]
```

!!! warning "Silent failure"
    Without `testcanvas.context_processors.app_context` the pages still render,
    but the navbar has no links and the custom theme is never loaded. No error
    is raised.

## 1. Create the app and install it

```text
my_plugin/
├── __init__.py
├── apps.py                     # AppConfig: navbar, widgets, permissions
├── models.py                   # optional
├── urls.py                     # app_name = "my_plugin"
├── views.py                    # function-based views
├── migrations/
├── static/my_plugin/           # namespaced static files
├── templates/my_plugin/        # namespaced templates
└── tests/
```

```python
# settings.py
INSTALLED_APPS += ["my_plugin.apps.MyPluginConfig"]
```

## 2. Configure the `AppConfig`

All integration points live in one class.

```python
# my_plugin/apps.py
from django.apps import AppConfig


class MyPluginConfig(AppConfig):
    """Configure My Plugin: navbar link, object widgets, permissions."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "my_plugin"
    label = "my_plugin"          # unique; used by NAVBAR_APP_ORDER
    verbose_name = "My Plugin"

    # Step 4 — navbar link (or define get_nav_items(self, request)).
    nav_items = [
        {"label": "My plugin", "url_name": "my_plugin:index", "icon": "🔌"},
    ]

    def ready(self) -> None:
        """Step 6 — register plugin models in the permission system."""
        # See collection-permission-integration.md § 4.2.

    def get_object_widgets(self, object_type: str, obj, request) -> list[dict]:
        """Step 5 — add widgets to core object pages (optional)."""
        return []
```

| Attribute / method | Purpose | Guide |
|---|---|---|
| `label` | unique app id, navbar ordering | [Navbar](navbar-plugin-setup.md) |
| `nav_items` / `get_nav_items(request)` | links in the shared navbar | [Navbar](navbar-plugin-setup.md) |
| `get_object_widgets(object_type, obj, request)` | buttons/progress/… on core pages | [Object widgets — user guide](object-widgets-user-guide.md) |
| `ready()` | register plugin models in the permission system | [Collection permissions](collection-permission-integration.md#42-extending-the-system-to-your-own-models) |

## 3. URLs and views

```python
# my_plugin/urls.py
from django.urls import path

from . import views

app_name = "my_plugin"           # required: url names are namespaced

urlpatterns = [
    path("", views.index, name="index"),
]
```

```python
# my_plugin/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def index(request):
    """Render the plugin home page."""
    return render(request, "my_plugin/index.html")
```

Use function-based views. Every view acting for a user must check permissions
(step 6).

## 4. Navbar link

Declared in the `AppConfig` (step 2). Details, ordering, permissions, tests:
[How to add a Django app to the shared navbar](navbar-plugin-setup.md).

## 5. Object widgets (optional)

Show buttons, progress bars or text on core pages (flow, flow node, user story,
acceptance criterion, test case) without touching core templates. The hook runs
on every render, so it must be fast and read-only:
[Object widgets — user guide](object-widgets-user-guide.md).

## 6. Data access and permissions

- Read and write core data through `testcanvas.api`:
  [Writing a plugin](writing-a-plugin.md).
- Respect collection permissions and register your own models:
  [Collection permissions — integration](collection-permission-integration.md).

## 7. Templates and styling

Extend the core layout, add your CSS, use the theme variables:
[Plugin templates and theming](plugin-templates-and-theming.md).
Project-wide colors and fonts: [Custom theme](custom-theme.md).

## 8. Tests

Minimum set:

| Test | Why |
|---|---|
| navbar link is collected | broken links fail silently ([example](navbar-plugin-setup.md#how-to-test-your-navbar-link)) |
| pages use `base_page.html` and load CSS after `testcanvas.css` | theme inheritance ([example](plugin-templates-and-theming.md#9-test-it)) |
| a user without access gets 404/403 | permissions ([patterns](collection-permission-integration.md#54-error-handling)) |

```bash
python manage.py test my_plugin
```

## Final checklist

- [ ] Project prerequisites done (context processor, core URLs).
- [ ] App in `INSTALLED_APPS` with its `AppConfig` path; `label` unique.
- [ ] `urls.py` has `app_name`; URLs included in the project `urls.py`.
- [ ] Navbar link declared and tested.
- [ ] Core accessed only through `testcanvas.api`; relations by string.
- [ ] Plugin models registered in `ready()` (if any).
- [ ] Every user-facing view checks permissions.
- [ ] Layout extends `testcanvas/bases/base_page.html`; CSS uses `--tc-*`.
- [ ] Static files and templates namespaced with the plugin label.
- [ ] New dependencies listed in the plugin `requirements.txt`.
- [ ] Migrations created (`python manage.py makemigrations my_plugin`).

