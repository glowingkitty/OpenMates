---
name: create-api-test-script
description: Create backend test scripts for app skills or providers that need Vault secrets inside the api Docker container
user-invocable: true
argument-hint: "<app>/<skill> or <provider>"
---

## Arguments

Parse `$ARGUMENTS` as the target to test, such as `web/search`, `images/search`, `brave`, or `context7`.

If the target is missing or ambiguous, ask which app skill or provider the script should exercise.

## Instructions

You are creating a manual backend API/app-skill test script that may need Vault-backed provider secrets. Use this workflow for quick probes, provider evaluations, and reproducible integration checks that are not part of the normal pytest suite.

### Step 1: Choose The Script Location

Put Vault-dependent scripts under `backend/scripts/` so they are available inside the running `api` container as `/app/backend/scripts/<script>.py`.

Do not put Vault-dependent scripts under `scripts/api_tests/` unless the script is intentionally host-only. The repo-level `scripts/` directory is not mounted into the `api` container by default, so those scripts cannot directly use `/vault-data/api.token` or the container runtime environment.

### Step 2: Choose The Execution Path

Use the path that matches what you are testing:

| Test target | Recommended path | Why |
|-------------|------------------|-----|
| App skill behavior | `SkillRegistry.dispatch_skill()` | Matches the in-process app-skill architecture used by API and workers |
| Provider wrapper behavior | Direct provider import + `SecretsManager` | Isolates provider auth, request, parsing, and errors |
| Public REST API contract | Authenticated `/v1/apps/{app}/skills/{skill}` | Tests external API auth, billing, and response envelope |

Avoid old per-app container endpoints such as `http://app-web:8000/skills/search`. Apps now load in-process inside `api` and Celery workers.

### Step 3: Use The Container Command

Run Vault-dependent scripts with:

```bash
docker exec api python /app/backend/scripts/<script>.py
```

Use `python`, not host `python3`, when documenting the in-container command. The script itself may use a `#!/usr/bin/env python3` shebang, but the command should be explicit and container-local.

### Step 4: App Skill Script Template

Use this when testing the actual app skill dispatch path:

```python
#!/usr/bin/env python3
"""
Purpose: Test <app>/<skill> through the in-process app skill registry.
Architecture: Runs inside the api container where Vault and backend apps are available.
Data sources: Existing OpenMates app skill and its configured providers.
Tests: Manual CLI verification with small, low-cost sample requests.
Usage: docker exec api python /app/backend/scripts/test_<app>_<skill>.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

from backend.core.api.app.services.skill_registry import build_skill_registry


APP_ID = "<app>"
SKILL_ID = "<skill>"


def summarize_response(response: dict[str, Any]) -> dict[str, Any]:
    results = response.get("results") or []
    first_group = results[0] if results else {}
    first_items = first_group.get("results") or [] if isinstance(first_group, dict) else []
    return {
        "provider": response.get("provider"),
        "error": response.get("error"),
        "group_count": len(results),
        "result_count": len(first_items),
        "first_title_present": bool(first_items and first_items[0].get("title")),
    }


async def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    registry, metadata = build_skill_registry()
    if APP_ID not in metadata:
        print(json.dumps({"status": "fail", "error": f"app not loaded: {APP_ID}"}))
        return 1
    if not registry.is_skill_available(APP_ID, SKILL_ID):
        print(json.dumps({"status": "fail", "error": f"skill not available: {APP_ID}/{SKILL_ID}"}))
        return 1

    response = await registry.dispatch_skill(
        APP_ID,
        SKILL_ID,
        {"requests": [{"id": "probe", "query": "OpenMates open source AI assistant", "count": 1}]},
    )
    summary = summarize_response(response)
    status = "pass" if summary["result_count"] > 0 and not summary["error"] else "fail"
    print(json.dumps({"status": status, **summary}, ensure_ascii=False))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

Adjust request fields to the target skill's `tool_schema`. For non-search skills, keep the summary similarly small and non-sensitive.

### Step 5: Provider Script Template

Use this when testing a provider wrapper directly:

```python
#!/usr/bin/env python3
"""
Purpose: Test the <provider> provider wrapper with Vault-backed credentials.
Architecture: Runs inside the api container and uses SecretsManager.
Data sources: External <provider> API through backend/shared/providers.
Tests: Manual CLI verification with one low-cost sample request.
Usage: docker exec api python /app/backend/scripts/test_<provider>_provider.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from backend.core.api.app.utils.secrets_manager import SecretsManager


async def main() -> int:
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    try:
        # Import and call the provider here. Keep counts small.
        # Never print secrets, prefixes, lengths, tokens, or raw auth headers.
        result = {"replace": "with provider result"}
    finally:
        await secrets_manager.aclose()

    print(json.dumps({"status": "pass", "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

### Step 6: Output Rules

Print only non-sensitive verification data:

- `status`: `pass` or `fail`
- provider name
- result counts
- selected non-sensitive fields, such as whether a title or URL is present
- error messages that do not include credentials

Do not print:

- API keys, tokens, OAuth credentials, cookies, or Vault values
- key prefixes, suffixes, lengths, masked values, or auth headers
- private user data or raw logs with identifiers
- large raw provider payloads unless the user explicitly needs a fixture and the payload is reviewed for sensitive content

If saving fixtures, write them under `backend/scripts/results/` or another explicit non-source output directory, and keep them out of commits unless the user asks to add sanitized fixtures.

### Step 7: Verify

Run the script in the `api` container:

```bash
docker exec api python /app/backend/scripts/<script>.py
```

If it fails because the provider is rate-limited or unavailable, report that separately from script correctness. Do not increase request counts to brute-force provider failures.

### Step 8: Cleanup And Commit Scope

Before committing, ensure the commit includes only the script and any intentional docs/skill changes. Do not commit generated result JSON unless it is a sanitized fixture requested by the user.

## Rules

- New `.py` scripts need a 5-10 line file header comment or docstring.
- Default to the smallest possible external request count, usually `count=1`.
- Use `asyncio` and `httpx`-based provider code; do not add `requests`.
- Prefer `SkillRegistry.dispatch_skill()` for app-skill tests.
- Prefer direct provider calls only for provider-specific tests.
- Never use old `app-{id}:8000/skills/...` endpoints for new scripts.
- Never expose secrets or partial secrets in logs, output, fixtures, or comments.
