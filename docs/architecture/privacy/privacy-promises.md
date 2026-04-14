<!--
  Privacy Promises — architecture + workflow

  A single source of truth for user-facing privacy claims, each linked to the
  code that enforces it and the tests that verify it. Regressions are caught
  by a pytest meta-test, a vitest companion, and a warn-only Claude Code hook.
  The public privacy policy's "Technical Privacy Measures" section is
  auto-generated from the same registry.

  Created: 2026-04-14 (Phases 1-3 shipped)
  Related: compliance/gdpr-audit.md, compliance/top-10-recommendations.md,
           privacy/pii-protection.md, privacy/email-privacy.md,
           core/encryption-architecture.md, core/security.md
-->

# Privacy Promises

Every user-facing privacy claim OpenMates makes is declared in one registry file, linked to the code that enforces it, and verified by tests. If any of the three pieces drifts — the claim, the code, or the test — the meta-test fails and a Claude Code hook warns the next editor. The public privacy policy's "Technical Privacy Measures" section is generated from the same registry, so we can't publish a promise without wiring its enforcement.

## Why this exists

Historically, privacy claims lived in three disconnected places: the public policy (`shared/docs/privacy_policy.yml`), ad-hoc architecture docs (`docs/architecture/privacy/*.md`), and tests scattered across the backend and frontend. A change to encryption code or a removed test could silently invalidate a public-facing promise — with no automated signal. The Privacy Promises system closes that loop.

## The registry — `shared/docs/privacy_promises.yml`

A single YAML file with one entry per promise. Each entry declares:

| Field | Purpose |
|-------|---------|
| `id` | Stable kebab-case identifier used in test markers and hook output |
| `category` | `encryption` / `pii` / `logging` / `deletion` / `auth` / `payment` / `tracking` / `transparency` |
| `severity` | `critical` / `high` / `medium` |
| `i18n_key` | Canonical translation key (`legal.privacy.promises.<id>.{heading,description}`) |
| `verification` | `test` (needs linked tests) or `documentation` (contractual/structural claims) |
| `gdpr_articles` | List of GDPR articles the promise supports (e.g. `["Art. 32"]`) |
| `enforcement[]` | List of `{file, what}` pairs — the code that enforces this promise |
| `tests[]` | List of `{kind, path, marker, assertion}` — the tests that verify it |
| `architecture_doc` | Link to the deeper architecture doc (when one exists) |
| `surfaced_in_policy` | If `true`, auto-renders into the public privacy policy |

Shape enforcement lives in `shared/docs/privacy_promises.schema.json`.

### Terminology rules (meta-test enforced)

- `client-side encryption` is our accurate baseline claim.
- `zero-knowledge encryption` MAY be used only when the checklist in `core/encryption-architecture.md` is satisfied — and the meta-test asserts the linked architecture doc documents that checklist.
- `end-to-end encryption` / `E2EE` / `E2E encryption` is **forbidden** in any surfaced heading, description, or linked architecture doc. Disclaimers like "this is *not* end-to-end encryption" are allowed; affirmative claims are not.

## The promises (current set)

Twelve promises ship today — ten verified by runtime tests, two verified by documentation (contractual / structural). The authoritative list is the registry; this table is a summary.

| # | ID | Category | Verification |
|---|------|----------|--------------|
| 1 | `client-side-chat-encryption` | encryption | test |
| 2 | `email-encryption-at-rest` | encryption | test |
| 3 | `no-third-party-tracking` | tracking | test |
| 4 | `pii-placeholder-substitution` | pii | test |
| 5 | `telemetry-privacy-filter` | logging | test |
| 6 | `cryptographic-erasure` | deletion | test |
| 7 | `argon2-password-hashing` | auth | test |
| 8 | `payment-data-minimization` | payment | test |
| 9 | `logging-redaction` | logging | test |
| 10 | `prompt-injection-defense` | pii | test |
| 11 | `no-training-on-user-data` | transparency | documentation |
| 12 | `open-source-transparency` | transparency | documentation |

## Verification layers

### 1. pytest meta-test — `backend/tests/test_privacy_promises.py`

Thirteen checks validate the registry's integrity on every CI run:

1. YAML parses + matches the JSON Schema
2. Promise IDs are unique
3. Every `enforcement[].file` exists on disk
4. Every linked test file exists on disk
5. Every `verification: documentation` promise has valid `docs[]`
6. Every linked test file contains a matching `@privacy-promise: <id>` marker
7. Every `i18n_key` exists in `frontend/packages/ui/src/i18n/sources/legal/privacy.yml`
8. No orphan markers — every `@privacy-promise:` found in the repo maps to a registry entry
9. **Forbidden-terminology guard** — no affirmative `end-to-end encryption` / `E2EE` in registry strings or linked architecture docs (explicit disclaimers pass)
10. **Zero-knowledge gate** — if any promise claims `zero-knowledge`, the linked architecture doc must document the checklist
11. **Live tracking audit** — scans every frontend `package.json` for forbidden analytics SDKs (gtag, segment, mixpanel, posthog, plausible, amplitude, hotjar, fullstory, heapanalytics). Fragment-encoded to avoid tripping the `analytics-sdk-forbidden` hook on itself.
12. **Live logging-redaction check** — instantiates `SensitiveDataFilter` and asserts an email, bearer token, and password are redacted from a log record
13. **Cryptographic-erasure phase order** — static source check that `user_cache_tasks.py` destroys encryption keys before deleting user content

Runs on host (`python3 -m pytest backend/tests/test_privacy_promises.py`) and in CI. Skips gracefully in the `api` docker container because `docs/` and parts of `frontend/` aren't mounted there — the skip message points developers to the host / CI path.

### 2. vitest companion — `frontend/packages/ui/src/legal/__tests__/privacyPromises.test.ts`

Three checks on the frontend side:

- The generated registry module is populated and all IDs use the canonical `legal.privacy.promises.` prefix
- `buildPrivacyPolicyContent` emits a level-3 heading + description for every `surfaced_in_policy: true` promise
- The legacy `legal.privacy.protection.*.description` keys are no longer referenced (prevents regression to the old hard-coded list)

### 3. Claude Code hook — `.claude/hooks/privacy-promise-guard.sh`

A `PreToolUse(Edit|Write)` hook. When an agent edits a file listed in any promise's `enforcement[]`, the hook emits the affected promise IDs, their headings, and the linked tests. If a linked test file has been removed, the hook escalates with `🚨 LINKED TEST REMOVED`. Never blocks (warn-only, exit 0). Registered per-developer in `.claude/settings.local.json`.

### 4. Per-test marker — `@privacy-promise: <id>`

A one-line comment in each linked test. The meta-test scans all `.py/.ts/.tsx/.js/.svelte` files under `backend/` and `frontend/` for these markers. Two invariants:

- Every marker maps to a registry ID (no orphans)
- Every listed test in the registry contains the expected marker (language-agnostic regex, same syntax in Python `#` and JS/TS `//` comments)

### 5. Legal-compliance auditor cross-check

The twice-weekly `legal-compliance-auditor` agent (`.claude/agents/legal-compliance-auditor.md`) runs Step 8 — Privacy Promises cross-check — on every full and delta scan. On the Thursday delta scan, if an enforcement file was modified in the commit window but its linked tests were NOT re-run (per `test-results/last-run.json`), the auditor emits a high-severity `code-fix` finding titled *"Privacy-promise enforcement file changed without test rerun"* referencing the affected promise IDs.

## Public privacy policy integration

The "Technical Privacy Measures" section of the public privacy policy is derived from the registry, not hand-written.

```
shared/docs/privacy_promises.yml
          │
          ▼
frontend/packages/ui/scripts/generate-privacy-promises.js   (build step)
          │
          ▼
frontend/packages/ui/src/legal/privacyPromises.generated.ts (typed module)
          │
          ▼
buildLegalContent.ts iterates SURFACED_PRIVACY_PROMISES
          │
          ▼
Public privacy policy renders heading + description per promise
```

The generator runs as part of `npm run prepare` / `prebuild` / `build` in `frontend/packages/ui/package.json`. The emitted TS module is committed so the browser never parses YAML at runtime.

i18n keys for each promise live under `legal.privacy.promises.<id>.heading` and `.description` in `frontend/packages/ui/src/i18n/sources/legal/privacy.yml`. Editing the registry bumps `lastUpdated` in `privacy-policy.ts` per GDPR Art. 13 transparency (enforced by the existing `legal-text-lastupdated-bump` hook).

## Adding a new promise

1. Append an entry to `shared/docs/privacy_promises.yml` following the schema. Pick a kebab-case `id` and matching snake_case `i18n_key` suffix.
2. Add `legal.privacy.promises.<id>.heading` and `.description` entries (English at minimum) to `frontend/packages/ui/src/i18n/sources/legal/privacy.yml`. The auto-rebuild-translations hook fills in other locales.
3. Add a `@privacy-promise: <id>` comment to at least one existing or new test file, and reference that file under `tests[]` in the registry.
4. For a `verification: documentation` promise, reference real files under `docs[]` and leave `tests: []`.
5. Run `python3 -m pytest backend/tests/test_privacy_promises.py` — it will fail informatively until steps 1–3 are consistent.
6. Run `npm run generate-privacy-promises` in `frontend/packages/ui` — that emits an updated `privacyPromises.generated.ts`.
7. Commit all three files in the same change (`sessions.py deploy` is the normal path).

## Removing / deprecating a promise

Remove the entry from the registry **and** the linked i18n keys in the same commit. The meta-test will catch any orphan markers left behind. If the promise had `surfaced_in_policy: true`, bump `lastUpdated` in `privacy-policy.ts` so the public policy re-renders.

## Downgrading a claim

If a promise previously claimed `zero-knowledge` but the enforcement code no longer satisfies the checklist in `core/encryption-architecture.md`, the meta-test's Zero-Knowledge Gate will fail. Resolve by either:

- Strengthening the enforcement code until the checklist is satisfied again, or
- Downgrading the user-facing claim to `client-side encryption` in the i18n description and removing the term `zero-knowledge` from the registry entry.

Never downgrade silently — every change to a public promise belongs in the commit history.

## File map

**Registry + schema**
- `shared/docs/privacy_promises.yml` — source of truth
- `shared/docs/privacy_promises.schema.json` — JSON Schema

**Verification**
- `backend/tests/test_privacy_promises.py` — pytest meta-test (13 checks)
- `frontend/packages/ui/src/legal/__tests__/privacyPromises.test.ts` — vitest companion

**Guards**
- `.claude/hooks/privacy-promise-guard.sh` — PreToolUse warn hook
- `.claude/agents/legal-compliance-auditor.md` — twice-weekly cross-check

**Policy integration**
- `frontend/packages/ui/scripts/generate-privacy-promises.js` — YAML → TS build step
- `frontend/packages/ui/src/legal/privacyPromises.generated.ts` — generated module
- `frontend/packages/ui/src/legal/buildLegalContent.ts` — iterates `SURFACED_PRIVACY_PROMISES`
- `frontend/packages/ui/src/i18n/sources/legal/privacy.yml` — `legal.privacy.promises.*` subtree
- `frontend/packages/ui/src/legal/documents/privacy-policy.ts` — `lastUpdated` field
