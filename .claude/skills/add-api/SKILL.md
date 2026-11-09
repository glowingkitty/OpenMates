---
name: add-api
description: Integrate a new external API provider (research, wrapper, test script, docs)
user-invocable: true
argument-hint: "<provider-name>"
---

## Arguments

Parse `$ARGUMENTS` as the provider name (e.g., `openweathermap`, `spotify`, `yelp`).

If missing, ask the user what API they want to integrate.

## Instructions

You are integrating a new external API provider. This is a research-first workflow — never rely on training data for API details.

### Step 0: Confirm an Official API

Follow the provider-specific data integration policy in `.claude/rules/provider-integrations.md`. Use only:

- The provider's official, documented API.
- An official open-data feed.

Confirm the official documentation supports the intended use. If that is
unclear, report the gap; do not contact the provider without user instruction
or implement an unsupported fallback.

Record the API documentation URL and review date, the endpoints used, and their
usage, attribution, privacy and rate-limit conditions. Never use a website's own
browser/mobile endpoints, a reseller of another platform's data, browser
automation or platform-specific scraping, and do not bypass access controls.

General on-demand public-page reading follows the separate `web.read` boundary
in `.claude/rules/provider-integrations.md` and the guide: honor applicable crawler exclusions, use no proxy
or access-control bypass, and preserve complete extracted text in saved embeds.
That boundary does not authorize a provider-specific connector or hidden API.

### Step 0b: Load the Full Guide

```bash
python3 scripts/sessions.py context --doc api
```

Read the guide output carefully — it contains the official-API policy, test script template, and documentation template.

### Step 1: Research

Before writing any code:

1. **Search for official API docs** — use web search, never assume from training data
2. **Check existing work** — look in `docs/architecture/`, `docs/apis/`, and `backend/shared/providers/`
3. **Identify key details:**
   - Official API documentation URL and review date
   - Authentication method (API key, OAuth2, etc.)
   - Endpoints needed and their request/response formats
   - Rate limits and pricing
   - Data freshness and geographic restrictions

4. **Present findings to the user and wait for confirmation** before proceeding to code.

### Step 1b: Create Provider Contract Spec

Before writing provider code, run `create-plan` or create an inline Plan according
to `docs/contributing/guides/spec-driven-development.md`.

New provider integrations normally require a full spec because they affect
privacy, contracts, rate limits, cost, error handling, and downstream skills.
The spec must include:

- Endpoint table with method, URL, auth, request fields, response fields
- Required normalized output shape
- Rate-limit and retry behavior
- Provider outage and no-results behavior
- Pricing/cost assumptions
- Privacy policy URL verification date when applicable
- Contract examples with sample request, sample response, and expected parsed output

When the provider powers a user-facing feature, app skill, focus mode, embed, or
memory behavior, the spec or inline contract must also define this phase gate:

1. Implement and test the provider wrapper and the OpenMates CLI behavior against
   the dev server first. Mocked OpenMates API calls, mocked SDK clients, stubbed
   servers, direct function calls, and fixture replay do not satisfy this gate.
2. Implement and test npm SDK and pip SDK parity locally against the dev server
   for the same provider-backed behavior when it is exposed programmatically.
   After local CLI and SDK evidence is green, reproduce or wire the same coverage
   into GitHub Actions for CI/daily tests.
3. Implement web UI, embeds, or Playwright coverage only after CLI and required
   SDK evidence are green.
4. Run deployed Playwright visual smoke for larger web/UI surfaces in both laptop
   and mobile viewports, fixing and redeploying any objective rendering, error,
   loading, or responsiveness issue, then ask the user to confirm the deployed dev
   web behavior works and looks correct before starting Apple parity. Use
   Firecrawl only as a recorded fallback when Playwright is impractical or
   blocked. `*.spec.ts` evidence alone is not enough.
5. Start Apple parity only after CLI, SDK, web, and user-confirmation evidence are
   complete, or after an explicit waiver/blocker is recorded. This applies to
   Apple UI parity; Apple client logic comes from the Rust core and is not
   sequenced behind web.

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

Use the template from the guide loaded above.

### Step 5: Create API Documentation

Create `docs/apis/{provider_name}.md` with:
- Overview and purpose
- Official API documentation URL and review date
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

### Step 7: When No Official API Exists

Report the capability gap and suggest an official API alternative. Do not
reverse-engineer consumer website/mobile interfaces or replace the missing
interface with a scraper, proxy, browser workflow or platform-specific agent
instructions.

## Rules

- Providers must NOT depend on skill-specific code — pure API wrappers only
- Module boundary: `backend/shared/providers/` — no imports from `backend/apps/`
- Always use `httpx` (async), never `requests`
- Always vault-first, env-var-fallback for secrets
- Never commit API keys — use `<PLACEHOLDER>` values
