---
description: Backend coding standards for Python, FastAPI, and Docker
globs:
  - "backend/**/*.py"
---

@docs/contributing/standards/backend.md

## Additional Backend Rules

- **API surface classification:** Before adding or changing a FastAPI route, classify it as one of: unauthenticated public REST API, developer API-key REST API, first-party client surface only (web/CLI/SDK/native with session or approved device auth), or internal-only. Record the classification in the spec/session notes or route comments when non-obvious.
- **API security contract:** Every changed route must define auth requirements, owner/team scoping, rate limits, credit/budget limits for paid or anonymous work, and whether it can be reached through Caddy's public API allowlist. Direct REST/WebSocket proof against `https://api.dev.openmates.org` must verify the happy path and relevant unauthorized/forbidden/rate-limited behavior before CLI, SDK, web, or Apple verification.
- **Encryption boundary:** Routes that accept or return client-side encrypted chat, memory, file, key, sync, or share material must default to first-party or internal-only access. Do not expose those routes as broad public/developer REST APIs unless an approved spec explains how the endpoint preserves encryption boundaries, prevents cross-user access, and avoids leaking decrypted plaintext, key material, share fragments, or private metadata.
- **Cache-miss fallback pattern:** Cache reads MUST have a database fallback. Never treat a cache miss as a terminal error:
  ```python
  value = await cache.get(key)
  if value is None:
      value = await db.get(key)
      await cache.set(key, value)
  ```
- **Skills** must NOT import from other skills. Shared logic goes to `BaseSkill` or `backend/shared/`.
- **Providers** must NOT depend on skill-specific code. Keep them as pure API wrappers in `backend/shared/providers/`.
- **Logging:** Only remove debug logs after user confirms the issue is fixed.
