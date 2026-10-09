# Scheduled Workflow completion verification

Specification: `feature.notifications@2`; approved fingerprint
`7d9314ad74bd36af9c17d653b251f75f4ad9e1fa88c74d68352b8158d3735128`.
Task: TASK-2444. Session: 40fc. Updated: 2026-10-09.

## Implementation

Successful scheduled runs dispatch independent enabled Apple push and verified
contact email. The first actual successful Send message pins the chat/message;
otherwise the notification opens its exact run. Clients reauthorize targets and
retain owner-device chat encryption. Workflow names require existing content
consent and remain encrypted in Apple previews. Run reference and completion time
remain available without email content consent. Durable channel ledgers recover
interrupted dispatch without repeating accepted channels. Daily digests remain
independent. Manual/test, failed and cancelled runs are excluded.

Personal completion links explicitly switch from a selected Team to Personal.
Ordinary Team run links retain their scope. Deleted, mismatched or unavailable
targets never fall back to another chat or the latest run.

## Focused checks

- 150 initial backend checks passed for scheduler, persistence, execution,
  completion recovery, idempotency, authorization, notification privacy and
  daily digests. Six existing owner claim/persist/acknowledge protocol checks pass.
- Reconciled backend coverage passed 47 checks, including Team authorization and
  personal-only durable completion projections. The final completion, probe and
  route follow-up passed 35 checks. Ruff and Python compilation pass.
- Reconciled web coverage passed 38 store, route and authentication tests.
  The subsequent startup/auth/context policy correction passes eight focused
  route/auth tests and independent review; the actual shared policy tests cover
  pre-ready Team restoration, ready Personal then deliberate Team selection,
  owner/hash changes, and leaving/reopening the same notification.
  Scoped ESLint and Svelte compilation pass. An earlier broad Svelte check
  reported 1,587 diagnostics; full repository
  checking is not claimed as passing. The final changed-file TypeScript/Svelte
  publication gate passes after the compatibility fixes.
- The managed translation artifact and schema-gated activation changes pass all
  88 initial focused tests and independent review. The final 12-test artifact
  suite also passes, including inherited Compose consumers and legacy artifact
  migration. They cover exact committed source,
  immutable hashes, all consumer mounts, stop-before-refresh ordering, strict
  CMS health and failure paths that keep refreshed consumers stopped.
- All 21 locales generated and validated outside publication. Completion emails
  rendered in English and German with/without consent and escaped titles.
  Generated locale JSON is excluded from the feature commit.
- 59 isolated CI environment and coverage checks pass. The private Workflow and
  Mailpit profile was published separately as `6a22845102f5f225e774f138fbe862a52843c808`.

## Isolated product evidence

| Check | Run | Result |
| --- | --- | --- |
| Scheduler baseline | [37779188274](https://github.com/glowingkitty/OpenMates/actions/runs/37779188274) | Passed |
| Daily digest baseline | [37779193320](https://github.com/glowingkitty/OpenMates/actions/runs/37779193320) | Passed; nonvisual |
| Completion status component | [37794194749](https://github.com/glowingkitty/OpenMates/actions/runs/37794194749) | Passed first attempt |
| Exact-run component | [37794200824](https://github.com/glowingkitty/OpenMates/actions/runs/37794200824) | Passed first attempt |
| Actual scheduled completion, SMTP and APNs boundary | [37818253956](https://github.com/glowingkitty/OpenMates/actions/runs/37818253956) | Passed first attempt; cleanup verified |
| Four destination cases before fixture correction | [37818245563](https://github.com/glowingkitty/OpenMates/actions/runs/37818245563) | Three passed first attempt; Team picker fixture stopped one screen early |
| Four destination cases after fixture correction | [37822894813](https://github.com/glowingkitty/OpenMates/actions/runs/37822894813) | Three passed first attempt; Team-to-Personal startup overwrote the completion hash with Workflows Home; startup defect later corrected |
| Explicit handoff-token correction | [37826934956](https://github.com/glowingkitty/OpenMates/actions/runs/37826934956) | Three passed first attempt; Team restoration navigates Home before authentication/feature readiness permits the handoff |
| Startup-context correction | [37831941228](https://github.com/glowingkitty/OpenMates/actions/runs/37831941228) | All four passed first attempt; no skips/retries; cleanup verified |
| Combined Team-sync source | [37835271548](https://github.com/glowingkitty/OpenMates/actions/runs/37835271548) | All four passed first attempt; no skips/retries; cleanup verified |
| Overnight web/Apple reconciliation | [37903227269](https://github.com/glowingkitty/OpenMates/actions/runs/37903227269) | All four passed first attempt; no skips/retries; cleanup verified |

The successful scheduled integration uses source
`9ed9dbdd54f79436367d994e8a9481e3da587b33`. It completed two real schedules,
accepted two emails in disposable Mailpit, verified actual exact email links,
independent intercepted APNs dispatch, privacy, replay/dedupe and durable targets
after encrypted-content pruning. Source `80f74af65f115a231acc1e136d4be3f6804f0b8e`
changes only the Team fixture and its generated assertion index; all product code
is identical to that successful integration source. SMTP proves transport
acceptance, not external inbox receipt. The APNs probe uses an intercepted
provider boundary with a synthetic token, not an Apple device receipt.

The selected-Team cold-open case, signed-out login handoff, exact new message in
an existing chat, and Check-false exact run all pass on their first attempt in
the three final browser runs. The one-shot initial-link policy protects Team
preference restoration before authentication/feature readiness and expires at
the first authenticated route decision. It records an already-Personal link to
preserve later deliberate Team selection, and resets on hash departure so
reopening the same notification permits a fresh handoff. These successful browser
runs also reject stale targets and unavailable runs without fallback.

The tested source `e5a8283ae5e6681ee43e12151952f4831d21a90e` passes all four browser cases after
reconciling current Team-first navigation, guest Workflow browsing, and Apple
authentication/push catch-up changes. Its 29 affected web unit tests, scoped lint,
Svelte compile and independent web/Apple merge review pass. Read-only backend
comparison confirms personal scheduled execution and the completion outbox are
unchanged by upstream Workflow skill Team guards; the successful scheduled
integration remains applicable. Later independent AI history-cache and balance
admission changes were preserved during publication after focused web/backend
compatibility review. Notification product sources and tests preserve the
tested candidate except three equivalent TypeScript-compatible own-key
checks and removal of an already-invalid CSS border. These mechanical changes
preserve behavior and computed appearance; all 12 affected store tests, scoped
lint, Svelte compilation and token validation pass. The managed publication's
changed-file TypeScript/Svelte and design-token gate also passes. Generated
Specification indexes were refreshed without changing the approved contract.

Earlier failures exposed startup chat cleanup stripping target IDs and an effect
cancelling its own verification after a run-cache update; both have focused
regressions and all four browser destination cases now pass. Earlier integration
failures were incorrect test assumptions about routing metadata after content
pruning and counting mail from previous attempts; the corrected probe passes.
Initial component startup timeouts were corrected through shared readiness
helpers, preserving assertions; clean component runs pass first attempt.

Every available recording, including failures and retries, is uploaded using the
CI receipt evidence command and delivered in the Codex response. Two cancelled
completion integration runs (37798388984 and 37803528451) ended before a test
attempt and supplied no recording. Superseded queued checks had no test
capture. The daily digest baseline is nonvisual. The scheduler baseline supplied
a browser pairing recording, without a CLI terminal recording.

## Dev activation and remaining native verification

The approved runtime repair generates commit-matched translations outside the
protected checkout and mounts them read-only. One admitted `dev-stack` operation
stops live backend consumers before refreshing source, creates the notification
schema, requires healthy CMS, and then recreates/health-checks the original
consumer cohort. The feature was published to dev as
`19b735913b0d51ba9b9ca9c49c5bf281d49b7827` and activated from
`ac42c4be694816f59c73daf21a6d6df4a27497a0`. The managed setup/restart completed
with all 16 backend consumers
running, API and CMS healthy, and the notification collection plus unique-run
and pending indexes present. The protected checkout is clean. A validated
commit-matched artifact contains 21 locales with all four completion email text
keys; all 16 translation consumers mount it read-only. APNs credential fields
are present on the API, Workflow and task workers; configuration presence does
not prove device delivery. An initial activation stopped at the translation
consumer consistency check;
four inherited worker consumers were added with a regression against actual
Compose inheritance. A second preflight failure exposed selection of the legacy
12-service artifact before source refresh. Versioned immutable artifact paths
resolve that migration while preserving prior files and strict source/hash
validation. The corrected coordinated activation succeeded. The read-only
activation proof records source and artifact identity, locale hashes,
schema/indexes, mounts and container health.
The public dev Apple association endpoint serves JSON matching activated source
and advertises both completion email fragment patterns. This verifies deployed
configuration; native OS handoff and device receipt still require native proof.

The Mac is reachable, but typed source-transfer, doctor/build and native workload
operations return `UNSUPPORTED_REMOTE_OPERATION`. Linux has no Swift compiler;
configured private-candidate CI workflows have no macOS/Xcode mode. Apple route,
preview decryption, exact-run, pending owner-delivery and no-inline-Reply tests
are implemented but unexecuted. A native compiled build and real APNs device
receipt remain unverified. The main Plan remains implementing until that
capability is available or the user grants an explicit verification waiver.
