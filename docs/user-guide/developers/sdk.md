---
status: draft
last_verified: 2026-06-22
---

# OpenMates SDKs

OpenMates provides JavaScript and Python SDKs for API-key access to app skills, encrypted chat workflows, and CLI-parity account/product operations.

## API Keys

Create an API key in Settings > Developers > API Keys. The guided flow asks for scope, credit limit, and expiration before revealing the key once.

Defaults are intentionally convenient but powerful:

- Full access is enabled by default.
- Credit usage is unlimited by default.
- Expiration is Never by default.

Each default shows a warning before the key is created. New SDK devices are blocked until approved in Settings > Developers > Devices.

## JavaScript

Install the npm package:

```bash
npm install openmates
```

Package page: [openmates on npm](https://www.npmjs.com/package/openmates)

```ts
import { OpenMates } from "openmates";

const om = new OpenMates({ apiKey: process.env.OPENMATES_API_KEY });

const search = await om.apps.web.search({
  requests: [{ query: "OpenMates SDK examples" }],
});
```

You do not need to call `connect()`. SDK methods authenticate lazily with the API key.

List the latest encrypted account chats. The default limit is 10 for fast loading; pass `limit: 0` only when you intentionally want all account chats:

```ts
const chats = await om.chats.list({ limit: 10 });
const allChats = await om.chats.list({ limit: 0 });
```

Create a non-persistent chat. This is the default and does not save the transcript to your OpenMates account:

```ts
const response = await om.chats.send("Summarize this release note draft.");
```

Create a saved account chat explicitly:

```ts
await om.chats.send("Create a project kickoff checklist.", { saveToAccount: true });
```

Use named namespaces for CLI-parity operations:

```ts
await om.account.info();
await om.billing.overview();
await om.billing.invoices();
await om.docs.search("api keys");
```

SDK chat deletion/sharing, billing exports/downloads, connected-account import, encrypted memories, assistant feedback, and benchmarks are available through named SDK methods. Debug-log sharing remains CLI-only and returns a typed unavailable error in SDKs.

### Workflow Automation

Author Workflows from YAML when you want the same server-side validation and compilation as the CLI:

```ts
const source = `
title: Morning rain check
trigger:
  type: manual
steps: []
`;

const validation = await om.workflows.validateYaml(source);
if (validation.draft_valid) {
  const { workflow } = await om.workflows.createFromYaml(source);
  await om.workflows.enable(workflow.id);
}
```

Structured callers can still create or modify graph workflows directly:

```ts
const workflow = await om.workflows.create({
  title: "Morning rain check",
  enabled: false,
  graph: {
    version: 1,
    trigger_node_id: "trigger",
    nodes: [{ id: "trigger", type: "manual_trigger", config: {} }],
    edges: [],
  },
});

await om.workflows.update(workflow.id, { enabled: true });
```

Run Workflows with a stable idempotency key, poll run detail, inspect retained node outputs, cancel active runs, or answer an `ask_for_user_input` step:

```ts
const run = await om.workflows.run(workflow.id, {
  idempotencyKey: `rain-check-${Date.now()}`,
  mode: "manual",
  input: { city: "Berlin" },
});

const detail = await om.workflows.runDetail(workflow.id, run.id);
for (const nodeRun of detail.node_runs ?? []) {
  console.log(nodeRun.node_id, nodeRun.status, nodeRun.output_summary);
}

await om.workflows.respond(workflow.id, run.id, "ask-city", { city: "Berlin" });
await om.workflows.cancelRun(workflow.id, run.id);
```

## Python

Install the Python package:

```bash
pip install openmates
```

Package page: [openmates on PyPI](https://pypi.org/project/openmates/)

```python
from openmates import OpenMates

om = OpenMates()  # reads OPENMATES_API_KEY

result = om.apps.web.search({
    "requests": [{"query": "OpenMates SDK examples"}],
})
```

List latest encrypted account chats. The default limit is 10 for fast loading; pass `limit=0` only when you intentionally want all account chats:

```python
chats = om.chats.list(limit=10)
all_chats = om.chats.list(limit=0)
```

Create a non-persistent chat:

```python
response = om.chats.send("Summarize this release note draft.")
```

Create a saved account chat explicitly:

```python
om.chats.send("Create a project kickoff checklist.", save_to_account=True)
```

Use named namespaces for CLI-parity operations:

```python
om.account.info()
om.billing.overview()
om.billing.invoices()
om.docs.search("api keys")
```

SDK chat deletion/sharing, billing exports/downloads, connected-account import, encrypted memories, assistant feedback, and benchmarks are available through named SDK methods. Debug-log sharing remains CLI-only and returns a typed unavailable error in SDKs.

### Workflow Automation

Use YAML when you want server-side validation and compilation parity with the CLI:

```python
source = """
title: Morning rain check
trigger:
  type: manual
steps: []
"""

validation = om.workflows.validate_yaml(source)
if validation["draft_valid"]:
    created = om.workflows.create_from_yaml(source)
    workflow = created["workflow"]
    om.workflows.enable(workflow["id"])
```

Structured callers can create and modify graph workflows directly:

```python
workflow = om.workflows.create(
    title="Morning rain check",
    enabled=False,
    graph={
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [{"id": "trigger", "type": "manual_trigger", "config": {}}],
        "edges": [],
    },
)

om.workflows.update(workflow["id"], enabled=True)
```

Run Workflows, inspect retained per-node outputs, cancel active runs, or answer `ask_for_user_input` steps:

```python
run = om.workflows.run(
    workflow["id"],
    idempotency_key="rain-check-2026-07-14",
    mode="manual",
    input_data={"city": "Berlin"},
)

detail = om.workflows.run_detail(workflow["id"], run["id"])
for node_run in detail.get("node_runs", []):
    print(node_run.get("node_id"), node_run.get("status"), node_run.get("output_summary"))

om.workflows.respond(workflow["id"], run["id"], "ask-city", {"city": "Berlin"})
om.workflows.cancel_run(workflow["id"], run["id"])
```

## Scopes

Chat scopes are enforced server-side:

- `chat:create_incognito` allows non-persistent SDK chats.
- `chat:create_saved` allows saved account chats.
- `chat:read_existing` allows listing existing encrypted account chats, including `chats.list({ limit })`.
- `chat:append_existing` allows adding messages to existing saved chats.
- `chat:delete` allows deleting chats.
- `chat:share` allows creating share links.

App-skill scopes can allow all apps, specific apps, or specific skills such as `web:search`. SDK app skills are exposed as generated native methods such as `om.apps.web.search(...)` and `om.apps.images.generate(...)`; public docs do not promote a generic `apps.run(...)` escape hatch.

Memory access requires `memory:read`. SDK callers must explicitly load and select memory IDs; the backend does not pause SDK requests to ask the user for memory-selection confirmation.

## Errors

SDKs return typed errors for:

- Missing `OPENMATES_API_KEY`.
- Expired or revoked API keys.
- New or unapproved SDK devices.
- Missing scopes.
- Credit limits that would be exceeded.

Credit limits can use exactly one period: daily, weekly, monthly, or lifetime.
