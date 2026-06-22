# openmates

Python SDK for OpenMates API-key access to app skills and encrypted chat workflows.

## Install

```bash
pip install openmates
```

## API Key

Create an API key in OpenMates under Settings > Developers > API Keys. The guided flow asks for scope, credit limit, and expiration before revealing the key once.

Set the key in your environment:

```bash
export OPENMATES_API_KEY="sk-api-..."
```

New SDK devices are blocked until approved in Settings > Developers > Devices.

## Usage

```python
from openmates import OpenMates

om = OpenMates()  # reads OPENMATES_API_KEY

result = om.apps.web.search({
    "requests": [{"query": "OpenMates SDK examples"}],
})
```

SDK methods authenticate lazily; there is no `connect()` call.

List encrypted account chats. The default limit is 10; pass `limit=0` only when you intentionally want all account chats:

```python
latest_chats = om.chats.list()
all_chats = om.chats.list(limit=0)
```

Create a non-persistent chat. This is the default and does not save the transcript to your OpenMates account:

```python
chat = om.chats.create()
response = chat.send("Summarize this release note draft.")
print(response.content)
```

Create a saved account chat explicitly:

```python
chat = om.chats.create(save_to_account=True)
chat.send("Create a project kickoff checklist.")

om.billing.overview()
om.billing.invoices()
om.docs.search("api keys")
```

## Errors

The SDK raises `OpenMatesConfigError` for missing configuration and `OpenMatesApiError` for API responses such as expired keys, unapproved devices, missing scopes, or exceeded credit limits.

Full source docs: `docs/user-guide/developers/sdk.md` in the OpenMates repository.
