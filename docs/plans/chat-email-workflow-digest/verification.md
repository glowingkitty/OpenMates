# Verification receipt — notification emails

Workspace `agent-02ea`, session `02ea`, Task `TASK-7066`. The user lifted the webinar
runtime/web rollout hold on 2026-10-01. Product implementation is published to dev
as `ae48ac9fd6ce231375c1568c87a60e777c33d413`, from reviewed candidate
`aefbf566a15d3d3f66cef91c70f5c31bcd52b9dc` over base
`5e1b804cfba98dffaa19afce22c553d8751af1aa`. Its product source is unchanged from
the passing Team candidate `e1a390283f`; the final delta contains verification
documents only. Web readiness, compatible backend activation and packaged setup
migration completed on dev on 2026-10-02. Production rollout is outside scope.
Task `TASK-7066` is blocked on the remaining verification environment/scope gaps.

## Dev activation and migration

Web readiness succeeded for `ae48ac9fd6ce231375c1568c87a60e777c33d413`.
Coordinated restart `docker-c0525424` rebuilt CMS and the compatible API/worker/
scheduler cohort. Source-coherence expansion included 17 services, all running;
API and CMS configured health checks passed. Their backend source generation is
`a6d41dd62b6f1401870095e5f29578f6e0175b2b`. Packaged `cms-setup` operation
`docker-231aec75` completed successfully after the compatible code was active.
No notification SQL was run separately. Post-migration health checks passed.

The read-only aggregate check at 2026-10-02 03:23:40 UTC recorded 414 accounts,
413 master-enabled accounts (up from 15), zero explicit-opt-out/global-block
violations, and unchanged effective backup/webhook counts of 15 each. The exact
global unsubscribe remained disabled. PostgreSQL defaults now enable master,
chat and Workflow email, with previews and the unrelated categories off;
explicit choice provenance starts as an empty object. Real dev data had no
identifiable explicit/category opt-outs; isolated migration fixtures prove those
cases and repeat-application behavior.

Protected local receipts: `tmp/notification-verification/dev-product-deploy.txt`,
`dev-web-readiness.txt`, `dev-backend-activation.txt`, `dev-runtime-generation.json`,
`dev-cms-setup-migration.txt`, `dev-post-migration-invariants.{txt,json}`,
`dev-post-migration-defaults.txt`, and `dev-post-migration-health.json` in the same
verification directory. Only aggregate counts and service metadata were exposed;
no account identities, addresses or ciphertext were printed.

## Focused checks

174 backend and 9 CLI tests pass in the latest combined checks. The backend checks pass in one combined run,
after restoring the pre-existing handler test's temporary type-only module stubs
so they cannot poison later encryption/worker imports. They cover final-response eligibility, foreground
leases and stale sockets, Team recipient consent, bounded previews, verified contacts,
HTTP and application cache bypass, global blocks, queued opt-outs, durable settings
ACKs, concurrent preference writes, default/explicit choice separation, digest run
eligibility, computation versus acknowledged delivery, idempotent provider retries,
rejection of previous-window digest retries, and Team preview binding to the committed chat and author. CLI checks cover interactive chat
viewing, read-only fresh preferences, correlated errors, and Team preview fallback.

The latest backend run includes the 109 notification cases, 63 Team
preflight/receive/SDK cases and two unchanged published WebSocket authentication
regressions, with no skipped tests. The transaction extension passes 55 Node tests
separately. Five focused frontend tests cover persisted ordinary-Team retry packets
and correlation/cleanup in the actual preflight acknowledgement waiter.

Receipts: `tmp/notification-verification/backend-team-final-combined.txt`,
`/tmp/notification-current-full-backend-02ea.txt` (earlier notification subset),
`/tmp/notification-current-cli-units-02ea.txt`,
`/tmp/notification-cli-rejection-02ea.txt`, and
`/tmp/notification-renderer-network-after-02ea.txt` (overlapping subsets are counted once).
Python uses the existing backend virtual environment; CLI uses Node 24.20.0.
These focused tests use mocks/in-memory fixtures and do not prove external delivery.

Automatic-upgrade checks pass separately: 137 current-dev integrated CLI server/Caddy tests
and 10 sidecar tests. The integrated CLI bundle and TypeScript declarations build
successfully. Failure cases keep the API and email consumers stopped; both image
and source update plans require fresh setup. Receipts are retained under
`tmp/notification-verification/{cli-current-upstream-units,cli-current-upstream-build,sidecar-units}.txt`.

Scoped lint and diff checks passed, including the final Watch changes and late send gate.
Materialized Specification and Python preflight passed. Temporary materialized
Svelte validation lacked prepared dependencies. Isolated runner preparation
[36949443772](https://github.com/glowingkitty/OpenMates/actions/runs/36949443772)
subsequently built the final web source `258922ecb7` successfully; this is build
evidence, separate from the final Team product pass and unexecuted native checks. The earlier 16-file materialized unit gate passed. Final normal deployment
gates passed against the reviewed integration: Specification, scoped lint, locale
build/validation, SDK cleartext boundary, and the 25-file Python test gate.
The advisory test mapper reported four unmapped files and a broad related-spec
list; focused product checks are recorded below, and no test gate was bypassed.
Receipt: `tmp/notification-verification/dev-product-deploy.txt`. Independent source
review found no remaining material issues. Added Watch XCTest/UI assertions are unexecuted.
The settings contract audit found 12 pre-existing CSS/test-ID violations and no
new callback/privacy-sync violation. Unrelated baseline typecheck errors were not repaired.

## Isolated product checks

The materialized candidate preserves `TASK-3503` Send message delivery changes,
including its later published integration `a454ddc89`. Email readers never acknowledge or
mutate those delivery rows. Product checks run in isolated GitHub CI, using a
private subject artifact rather than a deployed web build.

| Check | Source | GitHub run | Result |
| --- | --- | --- | --- |
| Chat worker and Team preview SMTP Mailpit capture | 245beddcf6 | [36927903076](https://github.com/glowingkitty/OpenMates/actions/runs/36927903076) | Passed; 1 expected, 0 skipped/unexpected/flaky; cleanup verified |
| Preference migration against PostgreSQL | d706ce9776 | [36911361856](https://github.com/glowingkitty/OpenMates/actions/runs/36911361856) | Passed; 1 expected, 0 skipped/unexpected/flaky; cleanup verified |
| Settings across clients/reload, including chat/Workflow preview disclosure | 8d8e8e39dc | [36940461898](https://github.com/glowingkitty/OpenMates/actions/runs/36940461898) | Passed; 1 expected, 0 skipped/unexpected/flaky; coverage complete; cleanup verified; strict console gate passed |
| Scheduled digest and SMTP Mailpit capture | cb0487676f | [36923312588](https://github.com/glowingkitty/OpenMates/actions/runs/36923312588) | Passed; 1 expected, 0 skipped/unexpected/flaky; cleanup verified; final cutoff/fresh sweep covered |
| Populated signed-in chat/settings/run destinations | 245beddcf6 | [36927908298](https://github.com/glowingkitty/OpenMates/actions/runs/36927908298) | Passed; 1 expected, 0 skipped/unexpected/flaky; cleanup verified; Personal chat/settings and exact queued Workflow run |
| Web foreground/background lifecycle | ef37ac911a | [36931970975](https://github.com/glowingkitty/OpenMates/actions/runs/36931970975) | Failed strict console teardown on both attempts; lifecycle transitions observed; cleanup verified |
| Encrypted Team transport and context link | 3bda742d9b | [36932754846](https://github.com/glowingkitty/OpenMates/actions/runs/36932754846) | Failed rich-editor fixture equality on both attempts; 0 skipped; cleanup verified; fixture corrected |
| Encrypted Team transport and context link | bad4088e1c | [36939385537](https://github.com/glowingkitty/OpenMates/actions/runs/36939385537) | Ordinary/fenced encrypted send checks succeeded; failed overlap geometry on both attempts; 0 skipped/flaky; cleanup verified; corrected to measure visible bubble |
| Encrypted Team transport and context link | da698df808 | [36942845856](https://github.com/glowingkitty/OpenMates/actions/runs/36942845856) | Encrypted ordinary/fenced sends, More action, bubble geometry and Personal/Team list isolation passed; authenticated Team link GET returned 404 on both attempts; 1 unexpected, 0 skipped/flaky; coverage complete; cleanup verified |
| Ordinary Team commit, lost ACK and context link | 258922ecb7 | [36950574030](https://github.com/glowingkitty/OpenMates/actions/runs/36950574030) | First ordinary/fenced send assertions passed; third send produced no preflight frame within 30 seconds on both attempts, before an ACK could be dropped; 1 unexpected, 0 skipped/flaky; coverage complete; cleanup verified; fixture sequencing corrected |
| Ordinary Team commit, lost ACK and context link | 9d0b6bf56f | [36954051820](https://github.com/glowingkitty/OpenMates/actions/runs/36954051820) | Prior send cleanup and retry/sync wait passed; raw frame equality failed on both attempts; 1 unexpected, 0 skipped/flaky; coverage complete; cleanup verified; corrected comparison excludes only per-send transport tracing |
| Ordinary Team commit, lost ACK and context link | e1a390283f | [36957138464](https://github.com/glowingkitty/OpenMates/actions/runs/36957138464) | Passed; 1 expected/passed, 0 skipped/unexpected/flaky; coverage complete; cleanup verified; all recovery, durable-row, no-AI and authenticated Team navigation assertions reached |
| Automatic self-host upgrade/install | bad4088e1c | [36938027998](https://github.com/glowingkitty/OpenMates/actions/runs/36938027998) | Fresh setup/cohort assertions passed; overall suite failed later exact CLI URL fixture check: 3 expected, 1 unexpected, 0 skipped/flaky; coverage complete; cleanup verified; fixture corrected |
| Automatic self-host upgrade/install | c8082fd6e3 | [36942950264](https://github.com/glowingkitty/OpenMates/actions/runs/36942950264) | Passed; 4 expected, 0 skipped/unexpected/flaky; coverage complete; cleanup verified; actual setup/cohort and installed CLI assertions passed |

Candidate `bad4088e1cf1513c8f4a66aa28d118ab486b8c60` integrates the automatic
updater and corrected Team code-embed fixture on current dev base
`3c8cce3e507888d1226a73c511d4ebf6fee5aa4a`. Its self-host and Team failures are recorded above. The subsequent preview
disclosure settings scope passed on source `8d8e8e39dc`. Corrected Team bubble
measurement passed on source `da698df808`, which then exposed an actual authenticated
Team-link read-access 404. Its chat read endpoint returned `Chat not found` with
the matching Team ID and an authenticated cookie. The server logs establish
missing durable chat metadata, rather than a failed Team role or mismatched Team
hash; transport/render assertions alone do not establish a committed chat.
The repair makes ordinary Team preflight commit chat metadata and ciphertext
atomically even at epoch zero, then verifies the exact committed message before
relay/confirmation and notification enqueue. Lost-acknowledgement retries reuse a
tab-session ciphertext snapshot and stable authenticated device identity. The final
browser regression on source `258922ecb7` failed before reaching the lost-ACK and
authenticated-link assertions: the third send never emitted preflight within 30
seconds. Earlier ordinary/fenced send assertions passed. The empty composer and
Cancel control led to a confirmed fixture sequencing race: the outbound frame
precedes completion of the composer send guard. The fixture now waits for matching
server confirmation, a successful correlated draft-delete receipt, the settled
bubble, and an idle empty composer before the third turn. Draft deletion is the
post-send awaited dependency that holds the guard. No product code changed for
this failure. This failed run is not durable replay or link proof.
The subsequent source `9d0b6bf56f` reached retry or sync after ACK loss, but its
raw-frame comparison failed. The WebSocket transport rewrites only the top-level
`_traceparent` per send; the committed nested inference trace remains retained.
The fixture now compares the full type/payload serialization excluding only that
transport field, including any unexpected Team preflight after ACK loss. Ciphertext,
turn identity, Team scope and all committed inference fields still require exact
equality. This failed run is not a passed replay or authenticated-link check.
The final source `e1a390283f` passed the complete Team spec, including lost-ACK
recovery, every emitted committed payload (excluding only transport tracing), one
durable row, no AI invocation, Personal/Team isolation, and signed-in reopening
of the Team link with both ordinary messages visible. Its exact-source preparation
[36956121177](https://github.com/glowingkitty/OpenMates/actions/runs/36956121177)
also passed. Artifact: [11206905851](https://github.com/glowingkitty/OpenMates/actions/runs/36957138464/artifacts/11206905851).
The corrected installed CLI URL expectations passed on source `c8082fd6e3`.
Queued jobs are not verification.

The ordinary encrypted Team transport spec explicitly asserts no AI invocation.
Its stale live-inference classification was moved to authenticated isolated CI.
The send path now decides invocation once from the final content transmitted to
the server. An ordinary encrypted turn passed, then reached a stale Details
fixture after TASK-3503 moved it under More. That fixture was corrected without
removing its visibility or non-overlap assertions. The next run reached the
fenced-text fixture, whose plain-text helper incorrectly expects literal Markdown
from the rich editor. The fixture now asserts the actual code embed. The next run passed ordinary
and fenced encrypted send, preflight and no-AI checks, then failed the no-overlap
geometry assertion. The assertion is retained while its measurement target is
corrected to the visible message bubble (`user-message-content`), preserving
exact no-overlap and visibility assertions. The previous target was a full-width
ChatHistory row rather than the styled bubble.

The final Team read check then established a persistence defect: epoch-zero
ordinary Team preflight returned `LEGACY`, and the following ciphertext relay
confirmed without creating a durable chat. The repair uses the existing atomic
preflight for ordinary Team turns, preserving pause and version guards. A new
transaction operation binds the relay to committed preflight, sender, Team,
chat, message and ciphertext. The SDK's atomic write also retains the authorized
Team hash and runs the notification hook after commit. Focused Python and
extension regressions pass; the real browser commit/read/link check passed on
source `e1a390283f`.

The digest and Personal/run-link scopes match their recorded passing sources;
settings match their final passing disclosure source. Chat mailer/candidate services
are unchanged; its preflight/WebSocket integration differs by the reviewed Team
durable-commit and stable-device changes covered by the combined unit and Team
browser checks. Migration differs only by a schema note;
`tmp/notification-verification/passing-scope-comparison.json` records those comparisons.
A schema documentation note does not change migration SQL or preference
behavior. New updater checks are recorded separately; previous CI passes are
not relabeled as exact-source runs of later candidates.

Later Team checks bind previews to the committed author/chat and add authenticated
Team context to email links. Unit regressions pass; a synthetic committed Team
message now exercises real Vault staging/fanout/SMTP. Populated Team navigation
from Personal context passed the focused transport test on `e1a390283f`.

Mailpit probes use real isolated Redis/Directus/Vault/SMTP. Chat dispatch executes
through the real Celery worker; digest invokes production services in the API
container. They inspect privacy-safe and preview HTML, opt-outs while queued,
duplicate events, returning/viewing before dispatch, empty periods, half-open daily
boundaries, manual/test exclusions, and separate pending-delivery outcomes.
They inspect authenticated route targets and reject anonymous API access. They do
not prove signed-in browser navigation to a populated chat or run from every link.

Earlier failures remain failures, not coverage: private-stack gates skipped until
the tooling manifest registered Mailpit; migration setup needed explicit UUID/text
casting; chat initialization unnecessarily required Invoice Ninja configuration;
SQL snapshot formatting selected JSONB concatenation; the original digest empty
fixture included the run before the target lower boundary. These were corrected
without weakening the relevant assertions. Settings helpers now tolerate an
already-open profile menu and correlate their own request ACK/error. The rejected
write still must show its error and restore confirmed preferences.
The previous settings attempt reached this assertion and failed only because its
toast selector referenced a nonexistent test ID; the final spec uses the actual
message element. The previous chat probe failed when Premailer tried to fetch a
Google Fonts stylesheet; network-free rendering now has a regression that fails
before the fix and passes after it. The probes now order full Mailpit records by
the listing's capture timestamp and clean their own deterministic digest reservations.

Web lifecycle [36931970975](https://github.com/glowingkitty/OpenMates/actions/runs/36931970975)
again observed foreground/background transitions, but strict console teardown
failed on anonymous usage 404 and Team-context cancellation during account/key
transition. Both attempts failed; no further retries or assertion suppression
were performed. A bounded unrelated login fix awaits user authorization.

## Actual limitations

- **External provider acceptance: unverified.** No external sample has been sent.
  Mailpit acceptance is isolated SMTP integration evidence only.
- **Controlled external mailbox receipt: unverified.** No inbox access is configured;
  the user deferred setup. No recipient was guessed.
- **Apple compilation and runtime: unverified.** Typed remote build operations
  reported unsupported; no raw remote bypass was attempted. Native/Watch source
  changes and mock-socket XCTest coverage are added, but not executed here. Older
  Apple clients require the lifecycle heartbeat update for idle foreground use:
  control pings do not reach the ASGI handler, so their legacy lease expires after
  75 seconds without received application messages. Old Watch sends no lifecycle
  declaration. Header compatibility cannot infer foreground state safely.
- **Apple Team preview staging is absent.** Its existing Chat/send model lacks a
  safely scoped Team identity. It falls back to content-free email; Web and CLI
  implement consent-gated preview staging without stored chat/Team keys.
- **Actual live-inference completion: unexecuted.** Synthetic isolated completion
  probes do not prove a real model turn. The bounded dev-host route requires
  activated code and an authenticated disposable test account. Existing dev-host
  scripts require already authenticated isolated state; the supported fresh-account
  provisioner is runner-private. Dev signup requires a controlled external
  verification inbox, which is unavailable. Existing personal/E2E state is not borrowed.
- **Signed-in email-link navigation:** populated Personal chat, settings, and exact
  Workflow-run navigation passed. Team context/navigation passed on `e1a390283f`.
- **Dev integration/migration: completed.** The source preserves the overlapping
  delivery-confirmation implementation. Live inference, external mail and native
  behavior remain unverified; runtime health does not prove those outcomes.

Legacy master-off values have no provenance. The authorized clean transition may
enable a deliberate master opt-out never separately recorded; identifiable explicit
choices, category opt-outs and global unsubscribes remain disabled. Only the requested
categories are enabled. Accounts without a matching verified Vault contact are skipped;
client-only encrypted addresses and stored chat keys are never decrypted by this worker.
Missing consent/material falls back to content-free email. SMTP stops after ambiguous
failure, and Team recipient fallback lookup is capped at 20,000 account IDs.

Team source `245beddcf6c6859317414b66e5f21af4705a8baa` preserves upstream
`b4fa7361f09b8e57507c82ac5ca564991e950137`. Chat SMTP and Personal/run link
regressions passed. Encrypted Team transport and authenticated navigation passed on `e1a390283f`;
its previous failures are recorded above.
The Team SMTP fixture calls production staging/fanout services on a synthetic
committed ciphertext row; it does not prove a real client commit hook. Team link
coverage checks authenticated access and visible committed content, but does not
force the later cold-device repair branch.

Read-only dev inventory before migration: 399 legacy master-off accounts, zero
identifiable explicit master opt-outs, one exact-hash global block, 398 transition
candidates, of which 37 have matching verified contacts and 361 do not. No addresses
or account identities were printed.

A read-only aggregate invariant receipt records 414 accounts, 15 master-enabled
accounts, zero explicit-opt-out/global-block violations, and 15 effectively enabled
accounts in each unrelated backup/webhook category. The post-migration check must
keep those unrelated category counts at or below 15 and all opt-out/block violations
at zero. Receipts: `tmp/notification-verification/dev-pre-migration-invariants.txt`
and `tmp/notification-verification/post-migration-invariants.sql`. The later
post-migration receipt above verifies those invariants after packaged setup.

The production upgrade requires installing the released CLI with the
`coreSetupGate` capability before its first core rollout. The supported updater
then runs fresh, packaged `cms-setup` automatically; no notification SQL is run
by an operator. Production deployment and CLI release publication remain outside
this task's dev-integration scope.

The self-host fixture now explicitly expects the installed CLI API endpoint
`http://127.0.0.1:8000` when its installer omits `VITE_API_URL`. Browser transport
continues using `http://localhost:8000`; neither exact persisted/fresh CLI URL
assertion is relaxed. Current upstream host-notifier/Caddy and speech-handoff
fixes are preserved. Private candidates contain product/contract sources; normal
scoped deployment regenerates and validates shared Specification artifacts from
the final integrated source. This prevents unrelated generated-index changes
from replacing another task's metadata.
