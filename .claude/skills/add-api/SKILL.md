---
name: openmates:add-api
description: Integrate a new external API provider (research, wrapper, test script, docs)
user-invocable: true
argument-hint: "<provider-name>"
---

## Arguments

Parse `$ARGUMENTS` as the provider name (e.g., `openweathermap`, `spotify`, `yelp`).

If missing, ask the user what API they want to integrate.

## Instructions

You are integrating a new external API provider. This is a research-first workflow — never rely on training data for API details.

### Step 0: Load the Full Guide

```bash
python3 scripts/sessions.py context --doc api
```

Read the guide output carefully — it contains the test script template, documentation template, and reverse-engineering workflow.

### Step 1: Research

Before writing any code:

1. **Search for official API docs** — use web search, never assume from training data
2. **Check existing work** — look in `docs/architecture/`, `docs/apis/`, and `backend/shared/providers/`
3. **Identify key details:**
   - Authentication method (API key, OAuth2, etc.)
   - Endpoints needed and their request/response formats
   - Rate limits and pricing
   - Data freshness and geographic restrictions

4. **Present findings to the user and wait for confirmation** before proceeding to code.

### Step 2: Read Reference Implementation

Read an existing provider as template:
```
backend/shared/providers/brave/brave_search.py
```

Key patterns to follow:
- Vault lookup with environment variable fallback
- Rate limit handling with retry logic
- `async`/`await` with `httpx`
- Health check function (no billing impact)
- Constants for URLs, secret paths, retry limits

### Step 3: Create Provider Directory

Create `backend/shared/providers/{provider_name}/`:

| File | Purpose |
|------|---------|
| `__init__.py` | Export main functions/classes |
| `client.py` | Pure API wrapper — NO skill-specific logic |
| `models.py` | Pydantic request/response schemas |

**client.py must include:**
- Secret loading: vault first, env var fallback (`SECRET__{PROVIDER}__{KEY_NAME}`)
- Rate limit handling with exponential backoff
- Health check function
- Proper error logging with `logger = logging.getLogger(__name__)`
- Constants for API URLs, secret paths, retry config

### Step 4: Create Test Script

Create `scripts/api_tests/test_{provider_name}_api.py`:

**Required features:**
- `--api-key` flag for manual key override
- `--test <name>` to run a specific test
- `--list` to list available tests
- Vault + env var fallback for auth
- Structured results: `{"status": "pass"|"fail", "duration": float, "error": str}`
- Summary with pass/fail counts

Use the template from the guide (loaded in Step 0).

### Step 5: Create API Documentation

Create `docs/apis/{provider_name}.md` with:
- Overview and purpose
- Authentication details (type, vault key name)
- Endpoints used (URL, method, purpose)
- Input/output structure tables
- Pricing (free tier, paid tier, estimated cost)
- Limitations (rate limits, data freshness, geographic restrictions)
- Scaling considerations

### Step 6: Check Privacy & Legal

Read `.claude/rules/privacy.md` and check if updates are needed:
- `shared/docs/privacy_policy.yml`
- `i18n/sources/legal/privacy.yml`
- `legal/buildLegalContent.ts`
- `config/links.ts`
- Update `lastUpdated` in `privacy-policy.ts`

Ask the user if privacy policy updates are needed for this provider.

### Step 7: Reverse-Engineered APIs (No Official API)

If using web scraping instead of an official API:
1. Use Firecrawl for discovery (`firecrawl_map` + `firecrawl_scrape`)
2. Add fragility warnings to documentation
3. Note: monitor for failures, re-test monthly, document selectors
4. Check `robots.txt` and ToS — implement rate limiting, cache aggressively

## Rules

- Providers must NOT depend on skill-specific code — pure API wrappers only
- Module boundary: `backend/shared/providers/` — no imports from `backend/apps/`
- Always use `httpx` (async), never `requests`
- Always vault-first, env-var-fallback for secrets
- Never commit API keys — use `<PLACEHOLDER>` values
