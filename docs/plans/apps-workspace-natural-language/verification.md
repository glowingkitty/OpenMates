# Apps workspace implementation verification

Task: TASK-7174. Specification: `feature.apps-workspace@4`.

The implementation replaces app parameter forms with natural-language requests
on web and TUI. Web Apps and chat share the fullscreen result view. The TUI shows
child previews and supports opening a child and returning to its parent.

## Accepted behavior

| Area | Implementation and evidence |
| --- | --- |
| Native requests | A dedicated JEV decision route selects an app skill, chat, or Workflow authoring. Bounded parameter choices and Mercury 3 extraction run separately from ordinary chat processing; accepted native arguments pass authoritative schema validation. Focused request/metadata tests pass. |
| Request privacy | Existing client PII settings protect model-bound text, prior context, and ranking text. Replacement maps remain local. Native values restore locally and revalidate; opaque identifiers and upload capabilities retain their exact values. Owner mismatch guards reject before inference. Web service tests, TUI tests, and the cold root-module import pass. |
| Presentation | Clipped home carousels, saved/recent/example sidebar ordering, one settings gear, responsive child grids, and pinned filters/composer are covered by component and browser checks. The map/header scrolls away; the TUI omits the map. |
| Personalized daily searches | Only the latest saved search per app and account scope is eligible. Runs charge the user, require activity in the last seven days, and respect the persistent opt-out. First save explains daily charges with OK and Turn off. Focused billing, scope, idempotency, notification, and scheduler tests pass. |
| Retention | Durable saved queries/preferences are encrypted in Directus. Private recommendation batches are Vault-encrypted on temporary disk excluded from backups. Successful replacement deletes the old batch; expiry purges batches after 24 hours, including for inactive users. Focused storage/repository tests pass. |
| Public recommendations | Fixed, nonpersonal app searches are OpenMates-funded and separated from private libraries. Public reads enforce freshness and expose no user scope. Real example chats remain the fallback. Focused public-service tests pass. |
| TUI | The exact mocked CLI/TUI harness passes 286 tests. Real terminal proof opens a persisted parent with an encrypted child, renders the child preview, opens child detail, returns to the parent, and preserves a follow-up draft. |

## CI evidence

All product/API/browser E2E checks use isolated GitHub CI with replay fixtures;
focused mocked unit checks run locally. The final browser candidate is
`eeedae66edfbf598de30d53283299da67e865961`. Its backend and CLI source trees are
unchanged from `f02851e52a165a94605c113d62a167e0062cb3c5`, which passed the API
and CLI/TUI suites below.

| Check | Result / run |
| --- | --- |
| Backend/CLI build and cold-schema preparation | Passed; run 39511980807. The current web build also passed in the Apps browser run. |
| Local CLI executable and declarations | Build passed; the built CLI starts successfully. From this task checkout, run `node frontend/packages/openmates-cli/dist/cli.js` to use it without waiting for npm publication. |
| Apps workspace component preview | Passed, 17 cases; run 39499096623. |
| Shared fullscreen/composer preview | Passed, 5 cases; run 39482588914. |
| Optimistic full-message renderer preview | Passed, 2 cases at 390 and 820 px; run 39523678501. A normal click expands the complete in-memory user message before database persistence; privacy toggles and sending/processing/synced replacements preserve the full view. |
| Real terminal child-preview proof | Passed; run 39509143295, source `0f1377140370c7193bc859f2e936279014f6824d`. The later request-privacy edits do not change terminal rendering. |
| Final combined Apps browser suite | Passed, all 25 cases; run 39529429346. The native Health search-to-chat handoff passes on its first attempt. One navigation snapshot needed a retry while feature flags loaded; the exact desktop/mobile list assertion now uses the shared navigation-readiness helper, with a test-only CI rerun pending. |
| Final combined Apps API suite | Passed, 3 cases, no retries/skips; run 39513853143. |
| Final combined CLI/TUI harness | Passed; run 39513858037. The wrapper runs the focused 286-test CLI/TUI harness and requires its contract markers. |
| Automatic chat handoff focus and supplied-context lifecycle | Passed, 18 focused cases (14 handoff and 4 URL/send cases), plus 5 send-readiness cases. Accepted auto-sends do not acquire editing focus; rejected drafts stay editable. Context-only URLs remain literal data across immediate/deferred/retried sends, while explicit request links keep ordinary behavior and context keeps PII processing. |
| Draft writes preserve first-send key headers | A deterministic real-handler regression pauses a stale raw draft snapshot, commits the first-send header, and resumes the draft write. Both missing-key and older-key snapshots fail with the old whole-row writer and pass with the atomic draft-only update. Conditional cleanup rechecks the current chat and messages in the same transaction. Rejected stale text remains unsaved and a later save advances beyond the clear watermark. The six focused suites pass 116 cases; sender key and durable-preflight guards remain unchanged. |
| Deployed laptop/mobile visual smoke | Pending dev rollout. |

Selected recordings are maintained in the CI evidence inventories. Only the
latest successful recording for each requested flow is linked in the final chat.

## Limits

Live JEV/Mercury provider inference and real daily billing were not invoked during
these checks. Tests mock paid inference/provider boundaries while preserving
native validation and real isolated API/storage behavior. The full repository
type checks have existing unrelated errors; changed-file lint/compile checks and
the scoped builds are the relevant checks for this patch. Figma MCP/API access
was unavailable, so the supplied design screenshots were the visual reference.
The changed send-lifecycle suite passed 25 cases and failed three
Project-read expectations. All three failures were reproduced against the
unchanged canonical modules; no unrelated Project behavior was changed.

The existing CLI publication workflow is separately failing
`serverCaddyUpdate.test.ts`: it expects two upload-origin scopes while the current
template contains three. Runs 39487871954, 39474405121, and 39465745716 each built
the CLI successfully, passed 839 tests, failed that one test, and skipped package
publication. This task does not change that unrelated Caddy test. The TUI source
and isolated build/proof remain covered; a global CLI upgrade requires a
successful package publication.

## Deployment

Pending scoped dev deployment, coordinated schema/backend rollout, and reviewed
deployed screenshots. Production deployment is outside this task's authorization.
