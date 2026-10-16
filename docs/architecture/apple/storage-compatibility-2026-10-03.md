# Native storage compatibility audit — 2026-10-03

Task: TASK-8137. Apple session: `6dc7`. Backend owner: session `2f80`.
Reference: `docs/plans/agentic-coding-storage-scale/apple-handoff.md` on
canonical dev `8a0ec19683c2d1fa23cea1f46e57913b3d259222`.
The backend storage candidate has not been published to dev.

## Live writer

`ChatEmbedStreamCoordinator` saves the encrypted head before its wrappers.
The head receipt matches both request and embed identity. The strict policy
requires lowercase SHA-256 of the UTF-8 encrypted-content string. Wrapper
receipts require integer `failed_count == 0` and `created_count == keys.count`.
The strict policy also requires `canonical_source == "head"` and integer
`requested_count == keys.count`. Staged legacy mode permits those new fields to
be absent; present but malformed or incorrect values fail under both policies.
The prepared ciphertext and wrappers survive transport reconnect and exhausted
automatic retries. Account/session replacement clears them; deletion and newer
version fences reject stale writes. Owner PII remains in its separate sidecar.

Production explicitly uses staged legacy head receipts while current dev lacks
`canonical_digest`, `canonical_source` and `requested_count`. A malformed or
mismatching digest, source or requested count is always rejected.
Legacy receipt acceptance is diagnostic evidence of the old protocol only;
it is **not** verification of new storage durability or guard activation.
The default injected policy and synthetic new-contract tests require the digest.
The receipt followup adds synthetic source/count rejection and immutable retry coverage,
and realistic source/count receipts in the recording transport. Native execution
for these additions is pending; earlier passing receipts do not verify them.
Neither storage capability is advertised by this repair. Typed recovery wiring,
archive reader/version contracts and backend integration evidence remain blocked
on the matching API publication and verification.

V1 advertised completion jobs no longer treat a local encrypted assistant row
as proof of canonical server commitment. Their existing claim, lease, exact
ciphertext retry, commit-version and identity safeguards remain required.

## Reader audit

- ChatViewModel foreground opening and remote paging now use published v1
  message windows with compound timestamp/message-ID cursors. Partial pages
  merge stable identities, retain pending rows and deletion/scope fences, and
  never certify a complete offline snapshot. Visible embed hydration requests
  exact visible embed identities instead of a whole chat content batch.
- Watch foreground opening/refresh uses the latest 50 rows and older history
  uses paired before cursors. It retains pending messages and prior encrypted
  disk history without advancing complete-cohort or sync-version receipts.
  Full transcript reads remain in the separately scheduled complete offline
  cohort and terminal recovery reconciliation paths.
- `OfflineRecentChatCacheWriter` correctly requires advertised server message
  count to equal received count. A partial window must not satisfy that full
  snapshot receipt; window cursor/completeness needs a separate model.
- Embed historical selection currently changes a version number while showing
  the head. Restore is not implemented. Project hosted edits emit a v1 snapshot
  followed by patches without periodic snapshots or bounded reconstruction.

Available dev message windows have timestamp/ID cursors and a 30-row default,
100-row maximum. The new exact oversized-message endpoint, wrapper pagination,
archive references/byte bounds, paginated version metadata and bounded patch
reconstruction contracts are unavailable. Do not invent their response shapes
or claim version 101+ reconstruction compatibility. V1 windows bound message
count, not bytes; compression checkpoint arrays also lack a byte/page contract.

## Attachment sends and retries

Fresh attachments require encrypted content before filtering or transport.
Already saved references require explicit current account/server/Team provenance;
missing content alone never classifies an attachment as saved. This local
provenance does not substitute for the unpublished reference-availability API.

Prepared preflight/outbound pairs are sealed with the owner's master key before
optimistic insertion or edit deletion. An explicit retry of the same message ID
replays the original ciphertext, wrappers and turn identity; changed input, PII
choices, version, account/server/Team/key/deletion context or missing original
local ciphertext fails closed. There is no automatic replay or adoption of a
different message ID. Retained pairs are removed only after matching success.

The latest handoff adds compatibility requirements that remain blockers until
the matching backend contracts are published and native behavior is verified:

- Store extracted code/table references in the canonical encrypted user message,
  not only inference input. Reconcile optimistic ciphertext to that exact message
  before dispatch and preserve references after reload.
- Retain artifact IDs, exact encrypted bundles, turn/message identity, commitment,
  wrappers and preflight in a client-encrypted restart journal bound to account,
  chat, key and final content. An uncertain ACK must not create new ciphertext or
  another turn. Replay a partially saved original bundle even if its reference
  later reports ready; reject unusable references rather than overwrite them.
- Require the matching committed message version (`expected_messages_v + 1`)
  before clearing an AI-turn journal. Generic legacy metadata confirmation is
  insufficient. Preserve the separate ordinary-Team preflight contract.
- Verify saved code after reload, lost-ACK/restart exact replay, stale/legacy/
  cross-chat ACK rejection and no journal resurrection after later sync writes.
  The metadata-only reference-availability endpoint remains unpublished.

## Unattended recovery audit

Canonical dev publishes v1 final-text and generated-metadata recovery only.
The shared synthetic `backend/tests/fixtures/chat_recovery_output_v2.json` and
its exact native crypto construction are now published independently. Typed
output handlers and the `recovery_outputs_discovery_complete` barrier remain
unpublished; the fixture does not authorize new replay or acknowledgement shapes.

The standalone native v2 envelope reader authenticates the published fixture
with the exact OMCR2 identity, canonical base64url/UUID encoding and positive
UInt32 versions. Seven synthetic CryptoKit tests pass, including all identity
fields, malformed encodings/lengths, invalid keys, authentication failures and
UTF-8 length framing. V1 is unchanged. This reader has no replay, persistence or
acknowledgement wiring and is not a complete unattended recovery receipt.

Remaining compatibility work after publication:

- Integrate the authenticated v2 reader with the published typed contract;
  discover all bounded pages before dependent replay. Persist each client-encrypted
  output canonically before its typed acknowledgement.
- Hydrate exact recovered rows with bounded readers rather than whole-chat
  terminal reconciliation after separating exact-row hydration from the current
  full-content coverage receipt. Preserve pending outputs across partial failure,
  scope changes, revoked Team membership and decryption errors.
- Retain Watch completion lease and prepared ciphertext across persist failures;
  Watch currently claims/encrypts anew on retry. Add sealed metadata recovery.
- Capture Team identity/epoch in typed recovery alongside account/server,
  generation, deletion, lease and commit-version safeguards.

## Activation hold

Hold deployment of handlers requiring strict backend parent/key writer checks
until new-contract native tests, backend integration receipts and supported-client
release policy are verified. Turning archive switches off does not gate writer
checks. Old installed clients are not upgraded by a source commit. Archive
pruning additionally needs supported-reader receipts, the
24-hour source buffer, lifecycle/capacity tests and per-unit safety fences.
No 500-execution capacity result or complete Apple storage receipt is claimed.

The remote backend chat is unavailable until the user's Monday SSH recovery.
Deliver this audit and exact native test/build receipts to its owner before
activation. Verification uses synthetic fixtures and zero real inference.

The proposed `feature.billing@6` logical-storage categories, Team payer policy
and expiration workflow await approval and the matching API release. No native
billing or expiration implementation is authorized by this proposed handoff.

## Native verification — 2026-10-04

The following receipts belong to prior source. They do not verify the subsequent
319/320 changes described below.

235 unique synthetic native unit cases have passing evidence across
`native-focused256` and corrected258. The retained log hashes and deduplicated
cases are recorded in `.runtime/followups98/cumulative-native-unit-evidence306.json`;
this is not a single all-green run, and repeats do not increase the count.
Four unique Watch UI cases passed across
`native-watch-ui286` and `native-watch-ui296`: bounded foreground paging,
unopened offline history, cached category/icon rows and the repaired Share flow.
Run 286 retains its failed Share case; run 296 passed after clipped scroll bounds,
targeted gestures and close-button zIndex repair. The production widget manual
Run App Intent fixture case passed in `native-ui266`, whose other case failures
remain recorded. No real workflow execution or inference was performed.

Final `native-mac316` built successfully with exit 0 and unchanged source;
`.runtime/followups98/native-mac316-unwind-sections.txt` proves `__eh_frame`
remained present after the Mac link repair. Earlier Mac287 build and unwind
evidence remain retained.

Final normal `native-ipad315` passed all three cases with unchanged source:
cold Apps to Tasks, initial Tasks to narrow resize, and external-selection to
Apps to Tasks. The dedicated normal `WorkspaceTabButtonStyle` consumes
`configuration.isPressed`; temporary diagnostics were removed. The exact
SwiftUI cause remains unproven. Earlier cold wide Tasks301 and cold initial
Apps304 failures remain in their historical receipts. Native UI/build results
do not certify the unpublished storage backend or complete Apple storage compatibility.

Final source preservation, scoped inventory review, actual CI disk reserve,
isolated product CI and coordinated publication remain pending. No deployment
or new TestFlight delivery is claimed.


## Followup 319/320 — native evidence, publication pending

Canonical dev is `046e28be58d3ba80d7dfc5912ee33321362e4bd6` after Directus
accountability updates; the storage API implementation remains unannounced. Session `6dc7`
contains unpublished followup changes. Each receipt below belongs to its recorded
source; later repairs do not rewrite failed runs. Native321 failed on the new
read-only renderer actor annotation with source unchanged during that run.
Unit-build322, build330, unit-build332, UI-build334, build343 and iOS349 passed.

The new focused unit evidence covers **174 unique passing cases** across323,
331 and333, not one all-green run. Unit323 ran 173 cases with 172 passing and
one annotation-owner fixture failing two assertions; draft, read-only and
speech cases passed. The synthetic foreign-account fixture repair preserved
the production guard, and selection331 then passed all 15. Unit333 passed all
20, including the production native-range precedence regression and read-only
coverage. Repeats are not additional cases. Prior235 cumulative cases, Mac316,
iPad315 and Watch296 remain prior-source evidence; no combined cumulative
count is claimed without cross-set deduplication.

The iPhone evidence covers **14 unique passing UI cases** across326 (eight
passing/six failing),335 (seven passing/one failing) and337 (Fork passed).
Exact copy, highlight/comment and Fork were confirmed. Run326's passing groups
were speech (2), code (2), welcome draft filter (1), selection Explain/read-only
copy (2) and README controls (1). Later fixes and passing receipts do not turn
326 or335 into all-green runs; their failed receipts remain retained.

On iPad, Wide and Short inspiration passed in338; its gutter case failed from
wrong accessibility bounds. AX-union340 and metric-lookup342 also failed.
After DEBUG actual-geometry instrumentation and lookup repair, build343 passed
and gutter344 passed with observed landscape 20-point gutter geometry and
keyboard avoidance. That run did not conclusively prove both orientations:
its loop could advance before asynchronous rotation changed the window. Root
added an aspect guard to the test after Mac345. Portrait348 failed because
device orientation changed while the actual app window remained landscape
with correct 20-point gutters. Fresh-launch351 failed with the same OS window
orientation, including a sideways Simulator home screen. Root restarted only
the iPad Simulator without erase. Unchanged-source352 passed in 43.161 seconds
after actual Portrait then LandscapeRight transitions. Its strict actual-aspect
guard and equal 20-point side/bottom gutters passed both orientations, along
with keyboard avoidance. Product source remains unchanged after Mac345; no
product defect is inferred. Earlier348/351 failed receipts remain retained. These are source-bound receipts, not a
retroactive successful338 run.

`native-mac-build345` and `native-watch-build346` **passed with exit zero and
unchanged source**, proving compilation only. The installed Mac app and
authentication were untouched; no new Watch runtime evidence is inferred.
The requested native stages are complete with source-bound receipts, including
both iPad orientations in352. The actual isolated product CI attempt awaits safe cache cleanup;
the uploader lacks Docker and SSH is prohibited until Monday. Product CI and
publication outcomes remain **PENDING**. No deployment or new TestFlight
inclusion is claimed.

The new scope covers native selection handles and exact selected-text copy,
read-only embed TextKit source selection/copy, the measured web Daily card's
300-by-200-point equal-column layout, iPad bottom inset and keyboard repairs,
and Lexend README Create with shared toast feedback. Assistant-response speech
adds retry and canonical-source readiness with response, ownership, deletion
and cancellation fences; its production provider and eager native send contract
remain unchanged. Spoken-paragraph highlighting is still unimplemented because
projected speech chunks lack an exact displayed-text mapping. Block annotation
text segments and raster boundaries remain required selection/copy boundaries;
ordinary prose proof alone does not establish their coverage.

Empty-draft work filters metadata hydration and permits tombstoning only the
exact decrypted-empty row under current owner fences. Read-only personal dev
CLI inspection found 25 drafts, zero semantically empty drafts and five media
markers. Root aggregates the private marker checks; these observations neither
authorize account cleanup nor prove native behavior.

The legacy draft-delete request contains only `chatId`. Exact native row and
owner fences do not establish atomic server deletion: another device can add
content between the local check and application of the legacy delete. This
cross-device concurrent-delete limitation remains unresolved.

Strict backend writer activation and archive pruning remain held under the
existing supported-client, native/backend receipt and per-unit safety gates.
All canonical-reference, restart-journal, commitment-bound acknowledgement,
reference-availability and full v2 recovery integration blockers above remain.
