# Coding Conventions

**Analysis Date:** 2026-03-26

## Naming Patterns

**Files:**
- Python: `snake_case.py` (e.g., `rate_limiting.py`, `chat_compressor.py`, `skill_executor.py`)
- TypeScript services: `camelCase.ts` (e.g., `chatListCache.ts`, `embedStore.ts`)
- Svelte components: `PascalCase.svelte` (e.g., `ChatMessage.svelte`, `ReminderSetterPanel.svelte`)
- TypeScript types: `camelCase.ts` placed in `types/` directory (e.g., `chat.ts`, `apps.ts`)
- Test files (Python): `test_<module>.py` (e.g., `test_rate_limiting.py`, `test_encryption_service.py`)
- Test files (TypeScript unit): `<module>.test.ts` co-located in `__tests__/` subdirectory
- E2E specs: `<feature>-flow.spec.ts` or `skill-<app>-<skill>.spec.ts` (e.g., `signup-flow.spec.ts`, `skill-web-read.spec.ts`)
- Preview files: `ComponentName.preview.ts` co-located with every shared component in `frontend/packages/ui/src/components/`

**Functions:**
- Python: `snake_case` for all functions and methods (e.g., `get_provider_rate_limit`, `check_rate_limit`)
- TypeScript: `camelCase` for all functions (e.g., `setCache`, `upsertChat`, `loginToTestAccount`)
- Python async functions use `async def` with `await` (no special naming suffix)

**Variables:**
- Python: `snake_case` for all variables (e.g., `plan_env_var`, `rate_limits_config`)
- TypeScript: `camelCase` for variables; `UPPER_SNAKE_CASE` for module-level constants
- Python: `UPPER_SNAKE_CASE` for module-level constants (e.g., `MAX_RESULTS_PER_REQUEST`, `DEFAULT_APP_INTERNAL_PORT`)

**Types/Classes:**
- Python classes: `PascalCase` (e.g., `EncryptionService`, `TestEncryptionService`, `RateLimitScheduledException`)
- TypeScript interfaces: `PascalCase` with `interface` keyword preferred over `type` for object shapes (e.g., `PreprocessorStepResult`, `Props`)
- TypeScript type aliases: `PascalCase` (e.g., `MessageStatus`, `TiptapJSON`, `ProcessingPhase`)
- Pydantic models: `PascalCase` ending with `Request` or `Response` for auto-discovery (e.g., `SkillRequest`, `OpenAICompletionResponse`)

---

## File Headers

**Every new `.py` file** requires a header comment block (5-10 lines):
```python
# backend/apps/ai/processing/rate_limiting.py
#
# Rate limiting helpers for provider API rate limit enforcement.
# Implements rate limiting using Dragonfly cache with plan-specific configurations
# loaded from provider YAML files.
```

**Every new `.ts` / `.svelte` file** requires a header comment block:
```typescript
// frontend/packages/ui/src/services/chatListCache.ts
// Global cache for chat list to persist across component remounts
// This prevents unnecessary database reads when the sidebar is closed and reopened
```

---

## Code Style

**Python Formatting:**
- PEP 8 style (no formatter config found — assumed enforced via CI)
- 4-space indentation
- Type hints on all function parameters and return values
- `Optional[T]` from `typing` for optional parameters (not `T | None` form)
- Imports from `typing`: `Dict`, `Any`, `Optional`, `Tuple`, `List` (not the lowercase generics form)

**TypeScript/Svelte Formatting (Prettier):**
- Config: `frontend/apps/web_app/.prettierrc`
- Tabs (not spaces) for indentation
- Single quotes (`singleQuote: true`)
- No trailing commas (`trailingComma: "none"`)
- 100-character print width
- Svelte files use `prettier-plugin-svelte`

**Linting:**
- ESLint config at `frontend/apps/web_app/eslint.config.js` and `frontend/packages/ui/eslint.config.js`
- Extends `@repo/eslint-config` shared config
- `@typescript-eslint/no-explicit-any` and `@typescript-eslint/no-require-imports` are commonly suppressed in Playwright spec files (acceptable — Playwright Docker image provides the module at runtime only)

---

## Svelte 5 Component Structure

**Required pattern — Svelte 5 Runes ONLY:**
```svelte
<script lang="ts">
  // Imports first
  import { onMount } from 'svelte';

  // Props interface
  interface Props {
    title: string;
    isVisible?: boolean;
  }

  // Props with defaults using Svelte 5 runes
  let { title, isVisible = true }: Props = $props();

  // Local state using Svelte 5 runes
  let isLoading = $state(false);

  // Derived/computed values using Svelte 5 runes (NOT $:)
  let displayTitle = $derived(title.toUpperCase());
</script>
```

**NEVER use `$:` reactive statements** — that is Svelte 4 syntax.

**Required props rule:** Callback props (`onFullscreen`, `onClose`, `onSubmit`) MUST be typed as required, not optional. If sometimes unneeded, use two component variants or a discriminated union type.

---

## Import Organization

**Python:**
1. Standard library imports
2. Third-party imports
3. Internal `backend.*` imports
4. Logger declaration at module level: `logger = logging.getLogger(__name__)`

**TypeScript:**
1. External library imports
2. Internal package imports (e.g., `from "../types/chat"`)
3. Relative local imports

**Path Aliases (TypeScript):**
- Frontend packages use relative paths within `frontend/packages/ui/src/`
- App-level code imports from `@repo/` monorepo packages

---

## Error Handling

**Python — No Silent Failures (CRITICAL):**
```python
# CORRECT — errors are visible and logged
try:
    data = read_file()
except Exception as e:
    logger.error(
        f"Failed to fetch results from {provider} "
        f"for query='{query[:50]}' request_id={request_id}: {e}",
        exc_info=True
    )
    raise
```

Never silently catch exceptions and return `None`/fallback unless the function contract explicitly documents that behavior. Always include context: what operation failed, relevant identifiers (request_id, provider, user context), and the original error.

**TypeScript — No Silent Failures:**
```typescript
// CORRECT
try {
  data = await fetchData();
} catch (e) {
  console.error('[ServiceName] Failed to fetch data:', e);
  throw e; // or surface to user
}
```

Never use `fallback values to hide errors`. Use `try-catch` for async operations. Display user-friendly error messages.

**Cache-miss fallback pattern (backend):**
```python
value = await cache.get(key)
if value is None:
    value = await db.get(key)
    await cache.set(key, value)
```
Cache reads MUST have a database fallback. Never treat a cache miss as a terminal error.

---

## Logging

**Python:**
- Use `logging.getLogger(__name__)` — never `print()` in production code
- Pattern: `logger = logging.getLogger(__name__)` at module level
- Use `logger.debug()`, `logger.info()`, `logger.warning()`, `logger.error()`
- `logger.error(..., exc_info=True)` for exception context
- Debug logs are only removed after the user confirms an issue is fixed

**TypeScript:**
- Use `console.debug()` for cache/state internals (e.g., `[ChatListCache] Cache updated: ...`)
- Use `console.error()` for errors
- Prefix with `[ClassName]` or `[ServiceName]` for traceability

---

## Comments

**When to Comment:**
- Explain business logic and architecture decisions, not syntax
- Link to `docs/architecture/` for complex design decisions
- Add `// Bug history this test suite guards against:` block at top of test files, referencing specific commit SHAs and the bug that was fixed
- Explain non-obvious invariants inline

**JSDoc/TSDoc:**
- `/** ... */` JSDoc on all public class methods and exported functions
- Include `@param` and explanation of edge cases
- Used consistently in services and cache classes

**Python Docstrings:**
- Required on all functions and classes
- Include `Args:` and `Returns:` sections for non-trivial functions
- Reference architecture docs inline (e.g., `# Architecture: docs/architecture/app_skills.md`)

---

## Constants — No Magic Values

**Python:**
```python
# CORRECT
MAX_RESULTS_PER_REQUEST = 50
if len(results) > MAX_RESULTS_PER_REQUEST:
    results = results[:MAX_RESULTS_PER_REQUEST]
```
Module-level constants for single-file use. Shared constants → dedicated config/constants module.

**TypeScript:**
```typescript
private readonly CACHE_STALE_MS = 5 * 60 * 1000; // 5 minutes
private readonly LAST_MESSAGE_CACHE_STALE_MS = 5 * 60 * 1000; // 5 minutes
```

---

## Module Boundaries

**Backend:**
- Skills must NOT import from other skills. Shared logic → `BaseSkill` or `backend/shared/`
- Providers (`backend/shared/providers/`) must NOT depend on skill-specific code — pure API wrappers only
- Shared Python utilities: `backend/shared/python_utils/`
- Shared Pydantic models: `backend/shared/python_schemas/`

**Frontend:**
- Stores must NOT import from other stores' internal modules — use barrel exports only
- Shared components: `frontend/packages/ui/src/components/`
- Shared services/utils: `frontend/packages/ui/src/services/` and `src/utils/`
- External images must use `proxyImage()` / `proxyFavicon()` from `imageProxy.ts`

---

## Pydantic Models (Backend)

Every app skill MUST define `{Name}Request` and `{Name}Response` Pydantic models in its skill module for REST API auto-discovery. These names are required — auto-discovery scans for classes ending with `Request` / `Response`:

```python
class MySkillRequest(BaseModel):
    query: str = Field(..., description="Search query")

class MySkillResponse(BaseModel):
    success: bool = Field(default=False)
    results: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = Field(None)
```

All `Field()` calls must include `description=` for OpenAPI docs.

---

## Styling (Frontend)

**CSS Custom Properties — Required:**
- All colors use CSS custom properties from `frontend/packages/ui/src/styles/theme.css`
- NEVER use raw color literals (`white`, `#fff`, `black`, `#000`) — dark mode inverts the grey scale
- NEVER use `px` for font sizes — use `rem` (respects browser zoom/accessibility settings)
- Font size variables: `var(--font-size-p)`, `var(--font-size-h1)` through `var(--font-size-h4)`
- Color variables: `var(--color-grey-0)` through `var(--color-grey-30)`, `var(--color-font-primary)`, `var(--color-error)`, etc.
- All settings visual elements use canonical components from `settings/elements/` (29 components)

---

## Function Design

**Python:** Focused single-responsibility functions. Async for all I/O operations.
**TypeScript:** Arrow functions or regular named functions; async/await for async operations.

**Return Values:**
- Python: Return `None` for "not found" cases when documented; raise exceptions for unexpected failures
- TypeScript: Return `null` for "not present" cache misses; throw for unexpected errors
- Never return empty fallbacks that silently swallow errors

---

## Dependency Management

**Never add a package with a version number from memory.** Always verify with:
- npm: `pnpm info <package-name> version`
- pip: `pip index versions <package-name>`

Pin exact versions in Python requirements files (`package==1.2.3`). Use conservative ranges in npm (`^1.2.3`). Never use `"latest"` or `"*"`.

---

*Convention analysis: 2026-03-26*
