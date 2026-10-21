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

## Local Apple verification — 2026-10-09

The bound Mac session reconciled the published Apple feature into its existing
working source, preserving its ongoing Apple changes. The import receipt records
base `c6bed2ad4d895eb7772d0ff7046647b8047c9e4a`, feature head
`ac42c4be694816f59c73daf21a6d6df4a27497a0`, and native patch SHA-256
`5f7a3bdf945f1c153ebaf42ffae62985a077a858dcf76b08225bedbbb592637e`.
The approved notifications Specification matches the published contract.

Local Xcode compilation succeeds for iOS, its embedded Watch app and the selected
unit-test bundle. The SimulatorDebug binary identifies itself as **0.27.0 (12)**;
this is distinct from the installed TestFlight **0.27.0 (97)**, which predates this
feature import. Both build receipts record no Apple source drift. Source manifests
and SHA-256 hashes of the app executable and debug library bind compilation to
the tested candidate. These receipts are retained in the assigned workspace under
`.runtime/followups123/workflow-completion274/native-verification284.json`, with
the full source manifests in `native261` and `native273`.

The completed local iOS Simulator run passes all **68 required focused tests**:
`AppDeepLinkRoutingTests` (26), `NotificationPreviewCryptoTests` (9), and
`WorkflowsParityTests` (33). Their relevant implementation and test source hashes
match the later successful compilation. The complete selected run passes 515
tests, fails none, and skips one separate opt-in PII benchmark. This proves the
covered routing, encrypted-preview, exact-run and scoped owner-delivery logic in
Simulator; it does not establish delivery to an Apple device. New reconnect/header
regressions added afterward are not covered by this earlier result.

Three fresh focused test attempts stop before tests execute: Simulator/test-host
startup fails while the local 12 GiB disk reserve is crossed. The runner stops the
owned process group and retains each interrupted result and receipt. Cache cleanup
and verified lossless retention of historical source/symbol files have been
performed; the reserve has not been lowered or bypassed. Local Xcode capability is
available, so the Linux helper's unsupported-operation result is not treated as
proof that native verification is unavailable.

**Remaining native proof:** macOS compilation; actual scheduled-completion APNs
receipt and taps; cold launch and signed-out login handoff; Team-to-Personal
switching; deleted/unavailable/mismatched destinations without fallback; device
preview consent/privacy; owner claim/persist/acknowledgment and duplicate/competing
device handling; and the completion email Universal Link opening the same exact
destination. A new TestFlight binary containing this feature is needed for those
device checks under the authorized delivery route. Installed apps and account data
remain preserved. The Plan remains implementing and TASK-2444 remains in progress;
the feature is **not yet natively verified**.

## Apple release and evidence audit — 2026-10-14

The approved source was published as
`df80a02f4bf54d87120c85b161551639d31ba9c4`. All 1,174 published shipping
inputs match the local archive inputs. Both signed archive receipts bind native
content SHA-256
`95f6c934ead6751ecebcd27aa98cfabc0b35cb24f3a24c44c54ca2167fa862f8`;
their original local Git identity is retained separately rather than rewritten
to the publication commit.

**0.27.0 (98)** compiles and is available through TestFlight for iPhone, iPad,
the embedded Watch app, and universal macOS (Apple Silicon and Intel). The
existing Mac installation was updated through TestFlight and opens with its
account preserved. The Tasks board renders without the earlier cancellation
error. These observations close the previous compilation and delivery gaps;
they do not establish scheduled notification receipt or destination behavior.
Apple accepted the Mac upload with a missing-symbol warning for the bundled
ONNX framework. The app's signed archives, available symbols, logs and warning
receipt are retained.

The three focused test files and examined notification implementation files
remain hash-identical to the historical 68-test pass. Lifecycle, authentication,
socket and project inputs have changed, so the historical 515-test result is
not a fresh test of build 98 or all its dependencies.

The source audit found a remaining Personal-context handoff defect:
`MainAppView.openPendingWorkflowCompletion` resolves a Personal completion
without first completing initial Team restoration and switching to Personal.
Workflow list/detail calls capture the current Team, so a selected Team can
prevent the exact Personal run from resolving. A simple early context reset
would race cold-launch restoration. The scoped correction must wait for the
current owner's restoration, switch once before capturing destination scope,
and invalidate on identity changes or a later deliberate Team selection.
Focused regressions and physical-device proof remain required after correction.

**Still pending:** real scheduled-completion APNs receipt and native taps;
exact created/responded-to chat and message or exact no-Send run; cold launch,
login handoff and Team-to-Personal routing; unavailable/deleted/mismatched
destinations without fallback; encrypted preview consent/privacy; owner
claim/persist/acknowledgment and duplicate/competing-device handling; and actual
email Universal Link handoff. Intercepted provider dispatch, unit tests and
TestFlight availability do not prove these outcomes. TASK-2444 remains in
progress and the feature is **not yet natively verified**.


## macOS encrypted preview packaging defect — 2026-10-14

Read-only inspection of the installed TestFlight **0.27.0 (98)** confirms that
the app, notification service, widget and share extension configure an
unprefixed `OpenMatesKeychainAccessGroup`, while their actual distribution
signatures grant the team-prefixed shared group. The unsigned Mac archive
command omitted `AppIdentifierPrefix`; later signing resolved entitlements
without correcting the already-expanded Info.plists. The corresponding iOS
archive uses the correct prefixed configuration.

This is a confirmed packaging defect and a candidate cause of generic Mac
notification previews. Both platforms register through the APNs path, and the
examined server code includes encrypted previews and `mutable-content` for
Mac as for iOS. There is no observed Mac-specific content-consent exclusion.
A bounded unified-log query returned no retained entries, so it does not prove
whether the reported notification lacked ciphertext or failed local decryption.

The release helper now supplies the explicit configured prefix and rejects
incorrect app/extension Info.plist groups or missing signed grants before
signing, on archive resume, and after export. The focused Python release
suite passes **181 tests**. Existing notification-key migration preserves the
recipient key and uses the Mac shared data-protection Keychain; generic fallback
remains fail closed. Fresh native compilation, a corrected distribution archive,
and actual background/terminated Mac push receipt are still required.


## Fresh focused Simulator follow-up — 2026-10-14

The updated iOS app and embedded Watch app compile successfully. The
source-matched Debug Simulator binary is **0.27.0 (12)**, distinct from
TestFlight **0.27.0 (98)**. Its focused unit run passes **308 tests**, including
all **78** current notification destination/privacy/workflow regressions:
`AppDeepLinkRoutingTests` (33), `NotificationPreviewCryptoTests` (9), and
`WorkflowsParityTests` (36). The required test files, notification implementation
and Personal handoff source remain identical to that tested snapshot.

Native337 retains the successful build and its source manifest; native342
retains the matching test-product reuse receipt, finalized unit result bundle
and exact Xcode result summary. An earlier test start and the subsequent long
UI batch were interrupted by the unchanged 12 GiB disk reserve. The unit result
is complete; the interrupted UI result has no finalized Info.plist, so its
recordings cannot be exported through xcresulttool. That incomplete UI bundle
and the export failure remain retained. Fixture/test corrections and smaller
UI runs are pending; the unit pass does not establish those visual outcomes.

These Simulator tests cover the Personal-context correction and scoped
notification logic. They do not establish Mac extension invocation, real APNs
receipt, native notification taps, competing-device delivery, or completion
email Universal Links. TASK-2444 remains in progress and is not yet natively
verified.


## Source-bound native regression follow-up — 2026-10-20

The current iOS/embedded Watch build-for-testing succeeds with the new iOS
notification content extension. The tested Simulator product is **0.28.0 (12)**;
it is not a TestFlight delivery. Native475 records the successful build and
unchanged full release/test inputs; native478 records the finalized focused run.
Both use actual checkout HEAD `234ff583686c7a832845a8a65ba82c1217a2e7f4`
with the retained overlay, shipping content SHA-256
`835b7cfee53afba739ba9a9601c24da19d290da71429a5a25457fc29a03dddae`
(1,843 shipping files; 2,151 total release/test inputs).

All **78** required regressions pass: AppDeepLinkRoutingTests (33),
NotificationPreviewCryptoTests (9), and WorkflowsParityTests (36).
NotificationReplyContextTests also passes all 17 tests. The broader selected
run finishes with **519 passed, two failed, and one skipped**; it is not an
overall passing run. The failures concern a notification preflight test's
phase assumption and the Billing route inventory, with scoped repairs prepared
for focused rerun. The skipped opt-in Watch socket check is not device proof.
The run stays above the unchanged 12 GiB reserve and all captured inputs remain
unchanged during compilation and execution.

Expanded notification editing, sole-Send interaction, real APNs receipt,
notification taps and email Universal Link destinations still require native
UI/device evidence. Current source and unit tests do not close those gaps.
The installed Mac remains the earlier TestFlight build until a new delivery
and installed-binary check establish otherwise. TASK-2444 remains in progress
and is **not yet natively verified**.


## Native and publication checkpoint — 21 October 2026, 13:24 Berlin

TASK-2444 remains **in progress and not yet natively verified**. The managed
Apple integration is published to dev as
`c8e7d4f6f09bcb077cd9c940a27a52888853c17d`; its normal deployment and
wait-deploy checks pass. This establishes source publication and web deployment,
not Apple notification delivery or TestFlight availability.

Native509 passes all 78 requested iOS Simulator notification regressions:
AppDeepLinkRoutingTests (33), NotificationPreviewCryptoTests (9), and
WorkflowsParityTests (36). Its broader run has 597 passes, two failures and one
skip; it is not an overall pass. The two Project/Watch failures were repaired
and the focused native522 run passes 191 tests with one opt-in skip. Neither
run is a macOS unit result: the current Mac route has no unit-test runner;
retained Mac qualification is compile-only.

Native544 successfully builds the iOS/embedded Watch test product, with no
changed captured inputs. Its frozen shipping identity is
`c3be49edbbeb4a9f46046a4adad8eb2ded6fc330c557c8769c65916ab5c5b026`
(1,842 release inputs; 2,151 release/test inputs), mapped to original immutable
candidate `2add06a357e046b8d4b2edacfad64b9ed9d594f6`. The active archive uses
that frozen source. Published dev `c8e7d4f6…` separately includes upstream
reconciliation and auxiliary publication differences: derived locale and
Specification artifacts, the exact upstream lockfile, and Whistle packaging
test classification/lint fixes. These identities are not interchangeable;
publication does not prove every published auxiliary byte was in the archive.

Native545 UI execution stopped at the disk reserve (exit 143) without an
accepted proof clip. The query/activity/Loaded Memories corrections from the
native537 investigation are applied, but no final passing UI run establishes
their visible result. In particular, expanded notification editing, sole-Send
interaction, real APNs receipt, native taps, competing-device/duplicate/privacy
behavior and completion-email Universal Link destinations remain open.

At this checkpoint, the third release attempt (release557), version **0.28.0
(99)**, is still compiling. **No accepted upload, processing completion,
TestFlight availability or installed-binary verification is claimed.** The
release owner must append the final iOS/iPadOS/Watch result, then Mac result,
with accepted upload/processing receipts and the installed versions. This
checkpoint deliberately leaves those outcomes pending.


## Release-owner delivery checkpoint

At **21 October 2026, 13:39 Berlin**, release557 is still compiling the iOS production application after the embedded Watch app linked and signed. No iOS or Mac archive/upload completion receipt exists yet. **No new TestFlight upload, processing completion, availability or installed build is claimed.** The last confirmed installed/delivered release remains **0.27.0 (98)**. The requested new release is **0.28.0 (99)** for iOS/iPadOS/Watch followed by macOS, minimum OS26.2.

Two earlier attempts stopped at the unchanged12GiB free-space reserve; their logs and source checks are retained. This third attempt remains active with the same frozen native source. Its normal serial release helper will validate/upload iOS before building/uploading Mac. Signed archives, account data and recovery evidence are preserved.

The exact running stage and any subsequent accepted-upload outcome must be read from the release receipts and final release-owner report. This dated checkpoint is not a claim that the session's delivery objective is complete.
