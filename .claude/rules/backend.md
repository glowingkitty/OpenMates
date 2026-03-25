---
description: Backend coding standards for Python, FastAPI, and Docker
globs:
  - "backend/**/*.py"
---

@docs/contributing/standards/backend.md

## Additional Backend Rules

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
