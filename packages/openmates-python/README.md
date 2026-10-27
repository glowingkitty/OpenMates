# openmates

<img src="https://openmates.org/favicon.png" alt="OpenMates" width="72">

**Your agentic operating system for everyday tasks, learning & work. With user interests & privacy first.**

Python SDK for OpenMates: run app skills, create encrypted chats, inspect usage,
and automate everyday OpenMates tasks from Python.

[OpenMates](https://openmates.org) | [SDK docs](https://openmates.org/docs/user-guide/developers/sdk) | [Source](https://github.com/glowingkitty/OpenMates/tree/dev/packages/openmates-python)

## Install

```bash
pip install openmates
```

Install the latest prerelease from the `dev` channel:

```bash
pip install --pre --upgrade openmates
```

## Quick Start

Try eligible requests without an account or API key while the shared free
allowance is available. If `OPENMATES_API_KEY` is configured, the same constructor
automatically uses your account.

Run your first request:

```python
from openmates import OpenMates

om = OpenMates()

result = om.apps.web.search({
    "requests": [{"query": "OpenMates SDK examples"}],
})

print(result)
```

SDK methods authenticate lazily. You do not need to call `connect()`.

New SDK devices may need approval in **Settings > Developers > Devices** before
they can access encrypted account data.

## Try without an account

Without an explicit or environment API key, app skills and `chats.send()` use the
shared free allowance:

```python
from openmates import OpenMates, OpenMatesSignupRequiredError

om = OpenMates()
try:
    response = om.chats.send("Explain how a rainbow forms.")
    print(response.content)
except OpenMatesSignupRequiredError as error:
    print(error)  # Free allowance used or unavailable; create an account to continue.

print(om.anonymous.status())
```

No identity setup is needed. Free usage is limited by public IP and a shared
daily, weekly, and monthly service allowance; people on the same network may
share the IP limit. Status is informational: each operation's actual allowance
is checked by the server.
Anonymous chats send plaintext for processing without saving an account transcript.
For follow-up turns, pass a `history` list with `role`, `content`, and optional integer
`created_at` fields. Account storage, Projects, Teams, memories, connected accounts,
focus modes, goals, and model overrides require authenticated APIs. Anonymous AI
requests use `chats.send()`; `apps.ai.ask()` directs callers there.

For account access, create a key in **Settings > Developers > API Keys** with the
scopes and credit limit your script needs, then set `OPENMATES_API_KEY`.
Authentication failures and credit exhaustion never switch to the free allowance.
For advanced free-only use, `anonymous=True` ignores an environment key; combining
it with an explicit key raises `OpenMatesConfigError`.

## Experimental image decisions

`apps.ai.decide` supports Jev 1.14 judgments over inline PNG/JPEG images:

```python
import base64
import uuid
from pathlib import Path
from openmates import OpenMates

om = OpenMates()
ref = str(uuid.uuid4())
result = om.apps.ai.decide({
    "state": {"board": ref},
    "questions": {
        "clear": {"type": "noul", "instructions": "Is the path to the exit clear?"}
    },
    "assets": {
        ref: {
            "type": "image", "format": "png",
            "data_base64": base64.b64encode(Path("board.png").read_bytes()).decode("ascii")
        }
    }
})
print(result["data"]["answers"])
```

Each image needs a canonical lowercase UUID key referenced in a string value in
state, instructions, or criteria. OpenMates validates up to four still images,
1 MiB decoded per image and 4 MiB total, with both dimensions 280–1568 pixels.
State/questions remain limited to 16 KiB; the complete JSON body is limited to
6 MiB. Use `jpg` or `jpeg` for JPEG bytes.

This prototype feature uses direct TypeSafe only, without OpenRouter fallback.
Image tokens use the same applicable free allowance or account credits. Callers
need no provider key or image header. This path does not fetch remote images or
create stored uploads; the separate account upload flow still needs signup.
Handle `OpenMatesSignupRequiredError` and provider failures as for text requests.
See [REST image decisions](https://github.com/glowingkitty/OpenMates/blob/dev/docs/architecture/apps/rest-api.md#experimental-image-decisions).

## Common Examples

### Send a private chat message

By default, `chats.send()` creates a non-persistent chat. It does not save the
transcript to your OpenMates account.

```python
response = om.chats.send("Summarize this release note draft.")
print(response.content)
```

Save the chat explicitly when you want it in your account history:

```python
response = om.chats.send(
    "Draft a checklist for launching our beta.",
    save_to_account=True,
)
```

### List and load encrypted chats

```python
latest_chats = om.chats.list(limit=10)
chat = om.chats.load(latest_chats[0]["id"])

print(chat["chat"].get("title"))
```

Pass `limit=0` only when you intentionally want all account chats.

### Search the web

```python
search = om.apps.web.search({
    "requests": [
        {"query": "privacy-first AI assistants", "count": 5},
    ],
})
```

### Read a web page

```python
page = om.apps.web.read({
    "url": "https://openmates.org/docs/user-guide/developers/sdk",
})
```

### Search OpenMates docs

```python
docs = om.docs.search("API keys")
```

### Check billing and usage

```python
overview = om.billing.overview()
invoices = om.billing.invoices()
```

### Work with memories

```python
memory_types = om.memories.types()
saved_memories = om.memories.list(app_id="web")
```

### Create reminders

```python
reminder = om.reminders.create({
    "title": "Review OpenMates SDK usage",
    "due_at": "2026-07-10T09:00:00Z",
})
```

## SDK Areas

| Namespace | Purpose |
| --- | --- |
| `om.apps.*` | Generated app-skill methods such as `web.search`, `web.read`, `images.generate`, `pdf.search`, and more. |
| `om.chats.*` | Encrypted chat list/load/send/export/share/delete helpers. |
| `om.docs.*` | Search OpenMates documentation. |
| `om.billing.*` | Usage overview, invoices, and billing metadata. |
| `om.account.*` | Account info, interests, storage, export helpers. |
| `om.memories.*` | List, create, update, and delete encrypted memory entries when your API key has memory scopes. |
| `om.reminders.*` | Create, list, and manage reminders. |
| `om.connected_accounts.*` | Import connected-account data with explicit user approval flows. |
| `om.embeds.*` | Inspect and share embed data when available to the API key. |
| `om.settings.*` | Update supported account settings such as language, theme, model defaults, and chat auto-delete. |

Generated app-skill methods follow the app and skill names from OpenMates. For
example, the web search skill is `om.apps.web.search(...)` and PDF search is
`om.apps.pdf.search(...)`.

## API Keys and Scopes

API keys are bearer credentials. Treat them like passwords.

- Store keys in environment variables or a secret manager.
- Do not commit keys to source control.
- Use the narrowest scopes and credit limits your script needs.
- New SDK devices may require approval before they can access encrypted account data.

Common scopes include:

| Scope | Allows |
| --- | --- |
| `chat:create_incognito` | Non-persistent SDK chats. |
| `chat:create_saved` | Saved account chats. |
| `chat:read_existing` | Listing and loading existing encrypted chats. |
| `chat:append_existing` | Adding messages to existing saved chats. |
| `chat:share` | Creating share links. |
| `memory:read` | Reading memory entries selected by the SDK caller. |

App-skill scopes can allow all apps, a specific app, or a specific skill such as
`web:search`.

## Error Handling

```python
from openmates import OpenMates, OpenMatesApiError, OpenMatesConfigError

try:
    om = OpenMates()
    print(om.billing.overview())
except OpenMatesConfigError as error:
    print(f"Configuration error: {error}")
except OpenMatesApiError as error:
    print(f"API error {error.status_code}: {error.data}")
```

The SDK raises:

- `OpenMatesConfigError` for missing API keys or local key-unwrapping problems.
- `OpenMatesSignupRequiredError` (an `OpenMatesApiError` subclass) when the free allowance is exhausted or unavailable; exposes `signup_required`, `code`, and `reason`.
- `OpenMatesApiError` for API responses such as expired keys, unapproved devices,
  missing scopes, or exceeded credit limits.

## Export a calendar event

```python
from pathlib import Path
from openmates import build_calendar_event_file

# Use the decrypted content of a finished calendar_event embed.
calendar_file = build_calendar_event_file(embed_id, content)
if calendar_file is not None:
    Path("event.ics").write_bytes(calendar_file.encode("utf-8"))
```

The local serializer exports only the primary event. It validates dates and
timezones and preserves an unknown end time without inventing a duration.
Context events are for display only. No calendar account or network call is required.

## Versioning

OpenMates shows the short product line, for example `v0.29`, in the web app.
Python package artifacts use exact release-line versions:

- `0.29.0aN` is an alpha prerelease from the `dev` branch.
- `0.29.0` is a stable release from `main`.

Install stable releases with `pip install openmates`. Install prereleases with
`pip install --pre openmates`.

## More Documentation

- [Full SDK guide](https://openmates.org/docs/user-guide/developers/sdk)
- [OpenMates docs](https://openmates.org/docs)
- [Source code](https://github.com/glowingkitty/OpenMates/tree/dev/packages/openmates-python)
- [Issue tracker](https://github.com/glowingkitty/OpenMates/issues)
