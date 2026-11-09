# TestCanvas documentation

TestCanvas is a Django test manager that follows the **ISTQB** methodology.
It links a visual application flow to the test artefacts that verify it:

```text
ApplicationMap ──< FlowNode ──< UserStory ──< AcceptanceCriterion ──< TestCase
```

The **core** application stores and validates this chain. Everything else
(statistics, execution reports, MCP tools, boards…) is added by optional
**plugins**.

## Where to start

Pick the path that matches what you want to do.

| I want to… | Read |
|---|---|
| Understand how TestCanvas is designed | [Architecture](concepts/architecture.md) |
| Decide who can see and edit the flows | [Collection permissions](administration/collection-permissions.md) |
| Change colors and fonts of the UI | [Custom theme](administration/custom-theme.md) |
| Build a plugin | [Plugin quickstart](plugins/quickstart.md) |

## Guide map

### Concepts

- [Architecture](concepts/architecture.md) — the ISTQB chain, collections and
  plugins at a glance.

### Administration

For people who install and run TestCanvas.

- [Collection permissions](administration/collection-permissions.md) — grant
  read or write access to users and groups.
- [Custom theme](administration/custom-theme.md) — restyle the UI with one CSS
  file.

### Plugin development

For developers who extend TestCanvas. Follow the pages in this order.

1. [Quickstart](plugins/quickstart.md) — every step, in order, with links.
2. [Python API](plugins/python-api.md) — read and write core data.
3. [Permissions](plugins/permissions.md) — apply collection permissions in
   your code.
4. [Navbar](plugins/navbar.md) — add a link to the shared navbar.
5. [Object widgets](plugins/object-widgets.md) — add buttons, progress bars
   and text to core pages.
6. [Templates and theming](plugins/templates-and-theming.md) — make plugin
   pages look like TestCanvas.


## Key terms

| Term | Meaning |
|---|---|
| **Flow** | An `ApplicationMap`: a graph of the steps of an application. It is the *test basis*. |
| **Flow node** | A step of a flow (`FlowNode`). It can also reference another flow as a **sub-flow**. |
| **User story** | The behaviour expected at a flow node. |
| **Acceptance criterion** | A measurable condition that a user story must meet. |
| **Test case** | A test that verifies an acceptance criterion. |
| **Collection** | A folder of flows. Permissions are granted on collections. |
| **UID** | The stable, opaque identifier of every core artefact (field `uid`). |
| **Plugin** | A Django app installed next to the core that adds features without changing it. |

