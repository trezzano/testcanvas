# Test Canvas — ISTQB Test Manager Application (AI-Ready)

Application for defining software testing assets following the principles of **ISTQB (International Software Testing Qualifications Board)** standards.

---

### Legal Disclaimer
**This project is an independent software implementation. We are NOT affiliated, associated, authorized, endorsed by, or in any way officially connected with the International Software Testing Qualifications Board (ISTQB), or any of its subsidiaries or affiliates. This software merely implements workflows and data structures that follow ISTQB public methodologies.**

---

### ⚠️ Important Notice: Project Status
**This project is currently in its early/initial phase. At this stage, it is a conceptual framework and a foundational skeleton, not a plug-and-play solution. It should not be used as-is in production environments.**

---

## Concept & Philosophy

The primary goal of **Test Canvas** is to provide an **opinionated architectural skeleton**. Instead of delivering a rigid, pre-built tool, it enforces a solid testing methodology and an organized data structure. 

This core framework is specifically designed to be highly customizable and serves as the perfect starting point for building bespoke test management platforms, with a strong focus on seamless **AI integration**.

## Key Features

- **ISTQB Methodology Alignment:** Support for test artifact structures (Test Plans, Test Suites, Test Cases) mapped to follow ISTQB standards, ensuring your data model is compliant from day one.
- **Customization-First Architecture:** A clean, flexible Django core intended to be customized, rewritten, and extended according to your specific business workflows.
- **AI-Ready Blueprint:** Architected with the exact data structures and hooks needed to easily integrate Large Language Models (LLMs) for automated test case generation, smart risk analysis, and predictive QA automation.
- **MCP & Local AI Integration:** Native compatibility with Model Context Protocol (MCP) and local LLM endpoints to preserve strict data privacy and security in enterprise environments *(available via proprietary commercial plugin)*.

## Tech Stack

- **Backend:** Python 3.x, Django
- **Architecture:** ISTQB-Compliant Data Modeling

--- 

## 📄 License

**Test Canvas** is **source-available**, not traditional open source. In short:

- ✅ **You can use it freely** — for personal projects, internal tools, or inside commercial products.
- ✅ **You can modify it** however you want, and you don't have to share your changes back.
- ❌ **You can't offer it as a competing hosted/managed service** — e.g. you can't take this project and resell it as your own SaaS in direct competition with us.
- ❌ **You can't remove the "Powered by Test Canvas" credit** from any public deployment — unless you buy a whitelabel license (see below).

### Why attribution matters

This project is free to use, but it's not free to build and maintain. In exchange for the freedom we give you, we ask for one small thing: **visible credit**. A `"Powered by Test Canvas"` with link somewhere public (footer, docs, about page) is enough — it's how people discover the project and how we keep building it.

Don't want to show the badge? No problem — contact the author for a whitelabel license and remove it.

### Paid Plugins & Consulting

The core project is free under the terms above. 

Advanced enterprise modules — including the **Native MCP & Local AI Integration Plugin** — as well as custom 
implementation and consulting services, are offered separately under a commercial license. 

Contact the author for licensing details and enterprise add-ons.

For full legal terms, please read the [LICENCE.md](./LICENCE.md) file in the root directory.

---

# How to Install

## Requirements

- Python 3.10 or later
- Django 4.2 or later


## install the core

```bash
pip install "git+[https://github.com/trezzano/testcanvas.git#subdirectory=testcanvas-core](https://github.com/trezzano/testcanvas.git#subdirectory=testcanvas-core)"
```

## Configuring TestCanvas in a Django application

How to add the TestCanvas core to an existing Django project. The configuration
comes from a project that already uses the core.

## 2. Configure `settings.py`

These settings are required.

Add the app:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # at the bottom :
    "testcanvas",
]
```

Add the core's context processor:

```python
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # HERE add testcanvas
                "testcanvas.context_processors.app_context",
            ],
        },
    },
]
```

Without the context processor, pages still open, but the navbar has no links and
the custom theme isn't loaded. No error is raised.

Set the authentication redirects. The core's landing page is also the login page:

```python
LOGIN_URL = "testcanvas:index"
LOGIN_REDIRECT_URL = "testcanvas:map_list"
LOGOUT_REDIRECT_URL = "testcanvas:index"
```

## 3. Configure `urls.py`

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Endpoint for the language switcher in the navbar.
    path("i18n/", include("django.conf.urls.i18n")),
    # The core is mounted at the site root: plugin URLs go before it.
    path("", include("testcanvas.urls")),
]
```

## Optional settings

| Setting | Purpose |
| --- | --- |
| `NAVBAR_LOGO_TEXT` | Logo text in the navbar |
| `LOGIN_PAGE_LOGO_PATH` | Logo on the login page, file path or url |
| `NAVBAR_APP_ORDER` | Order of the sections in the navbar |
| `STATICFILES_DIRS` | Project static files, such as the custom theme |

```python
import os

NAVBAR_LOGO_TEXT = os.environ.get("NAVBAR_LOGO_TEXT", "Test Canvas")

# Static path, absolute path or external URL.
LOGIN_PAGE_LOGO_PATH = "images/my_logo.png"

# Keys are AppConfig.label values: lower numbers are shown first.
NAVBAR_APP_ORDER = {
    "testcanvas": 10,
}

# The folder must exist. It can contain testcanvas-custom-theme.css.
STATICFILES_DIRS = [BASE_DIR / "static"]
```

## Adding a plugin

1. Install the plugin's package.
2. Add its app to `INSTALLED_APPS`, along with any apps it depends on.
3. Mount its URLs **before** the core's:

   ```python
   path("<pip-name>/", include("testcanvas_plugin_<name>.urls")),
   path("", include("testcanvas.urls")),
   ```

4. Add its `label` to `NAVBAR_APP_ORDER` if you want to set its position.
5. Run `python manage.py migrate`.

Some plugins require other settings, described in their documentation. For
example, the kanban plugin in the core's sandbox uses the `ordered_model` app and
`MEDIA_ROOT` for attachments.

