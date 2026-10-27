# Apple progress and next implementation sequence

Planning snapshot: **19 October 2026**. Current web/backend source is fetched at
`78e8d99023c4a90ad06b2d1b35cd257c15cab8fc`. Latest dev was inspected directly
from Git objects; preserved Apple edits have not been merged or overwritten.
This planning turn performs no product implementation, native builds or uploads.

## Progress that is actually recorded

| Area | Delivered or implemented | Remaining evidence/work |
| --- | --- | --- |
| Delivery | 0.27.0 build98 accepted and available through TestFlight for iPhone/iPad with Watch and for Mac; Mac installed version is still98 on this check. Source `df80a02f4b`. | No later Apple upload is established by the retained receipts. |
| Build98 improvements | Guest examples on main Apple clients, model Documents management and per-capability controls, confirmed-action haptics, maps/hosting/search renderer work, teams/header/composer/recording fixes and offline workspace repairs are in the published patch. | Publication is not proof that every earlier reported issue is closed in the real app. In particular remote Project reads and full notification delivery remain open. |
| Reviewed followups after98 | Empty-draft/New Chat filtering, encrypted Daily Inspiration startup cache, all safe README images rather than eight, embed footer sizing, Personal notification handoff and Mac shared-Keychain-group packaging repair. | Source is retained; the old managed publication candidate expired on16October. Refresh integration and finish focused UI/device proof before delivery. |
| Tests | 308 focused Simulator unit tests passed, including78 routing/preview/workflow tests. Release-helper181 Python tests passed. | Native UI work encountered fixture/test issues and interrupted result capture under the disk reserve. Some passing core recordings exist; full required UI proof does not. |
| Watch guest/pairing | Independently reviewed retained proposal, including cancellation and scoped credential ownership. | Proposal remains unapplied; compilation, real pairing, free guest use, sending, recent20 offline chats/embeds and device proof remain. |
| Still open | Actual iPhone Storage per-chat reclamation, durable offline sends on each platform, free-budget guest parity and TASK-2444 native delivery/deep links. | Keep these explicit in TASK-8137/TASK-2444. |

The installed Mac's notification preview defect is concrete: its configured
shared Keychain group is unprefixed while the signed entitlement is prefixed.
The release helper repair is tested; a corrected uploaded/installed Mac binary
and actual decrypted push receipt have not yet been established.

The last remote Project investigation found its source host offline; the Mac
also showed the remote source as disabled. Restoration was stopped by an active
shared-runtime operation, before a source host was launched. This does not
establish its status today. Recheck the source and verify **README, remote
folders/files, and stored embed metadata/previews separately**.

## What changed in web and needs an Apple implementation

| Work | Web reference at the pinned source | Apple integration |
| --- | --- | --- |
| Confirmed Mate / Thinking lifecycle | `ChatMessage.svelte`, `chatSyncServiceHandlersAI.ts`; `chat-response-processing-ui.spec.ts` | Extend existing turn-fenced native reducers to render one transient assistant row and hand it to the stream. |
| Rainbow location | `ChatMessage.svelte`, bottom-only response `::after`; `chat-assistant-response-activity.spec.ts` | Replace `ChatProcessingRing` around the workspace and the separate streaming banner with response-owned presentation and reduced-motion behavior. |
| Minimized skill/thinking runs | `AssistantActivityGroup.svelte`, `assistantActivityRuns.ts` and completion/status/summary helpers | Add chronological activity runs in the render document. Preserve prose between calls, completed collapse, live expansion and manual disclosure. |
| Inputs, details and consent | `UnifiedEmbedPreview.svelte`, activity groups and Focus/Project cases | Reuse existing native skill input/detail renderers and consent services; retain access through minimized UI and correct live/history behavior. |
| Loaded Memories | `LoadedMemoryPills.svelte`, `associateLoadedMemories.ts`, history receipts | Associate receipts with the correct assistant response before authored text and render them in activity. |
| Queue editing / steering | `QueuedFollowupControls.svelte`, `queuedMessageLifecycle.ts`, queued-followup protocol tests | Add encrypted revision-safe editing, follow-up/Steer instead and conflict behavior. Native queue text alone is insufficient. |
| Faster preparation / terminal recovery | `preparedChatForSend`, `preparedPrivacyForSend`, send/recovery handlers | Adopt only missing current contracts, preserving native identity, crypto, ACK and recovery fences. Optional metadata cannot prolong or revive terminal presentation. |
| Other changed UI | Current connection header, composer/drafts, public guest/interests, recipe/wiki/media, Diagram/Jobs/trademark results | Audit actual registrations, preview/fullscreen/actions and responsive states; avoid assuming a generic renderer proves parity. |

The backend/web processing task's final report confirms deployment to dev,
including `9f28425d57`, and also reports unresolved runtime checks. The published
timing evidence still misses some selected-Mate and authored-response targets.
Apple should now integrate the deployed contract while preserving these shared
gaps; it cannot promise a server-side1500ms result from UI work alone.

## Recommended order

1. **Reconcile and stabilize the baseline.** Preserve delivered/retained work,
   refresh the managed candidate against current dev, complete the known Mac
   notification packaging repair and verify remote Project reads. Establish a
   build that fits the existing reserve; serial Xcode jobs alone previously left
   Swift at eight workers. A supported serial-driver override has a dry-run
   receipt but has not yet completed a full build.
2. **Port current chat processing and activity UI.** Typed events and authority,
   one Thinking row, response-bottom rainbow, chronological compact activity,
   inputs/details/Memories/Focus, queue/steer and current recovery. Measure web
   and Apple phase timings on equivalent scenarios.
3. **Run Whistle and physical Watch call feasibility in parallel with step2.**
   Prove actual target linking, offline accuracy and device resource use, plus
   supported networking/audio behavior. This provides an early answer on the
   main Watch risks.
4. **Implement live calls across Apple.** Reuse the existing deployed broker,
   consent and encrypted chat persistence. Add duplex audio, context, tools,
   interruptions, mute, minimized controls and navigation continuity.
5. **Complete the Watch interaction.** One bottom component in both empty and
   existing chats: phone starts/controls a call, keyboard opens text editing,
   microphone records/transcribes. Connect Whistle to editable local dictation,
   preserve drafts/audio attachments, and prevent overlapping recording/calls.
6. **Verify and deliver in two increments.** First stable chat/UI parity, then
   calls/Watch/Whistle evaluation. Retain source-bound core recordings and
   failures/retries. Deliver through TestFlight for phone/tablet/Watch, then Mac.
   Continue the existing storage/offline/guest work and native notification proof
   under their Tasks alongside these increments.

## Whistle evaluation

[Cactus's model card](https://huggingface.co/Cactus-Compute/whistle) describes a
**16.9MB** CPU model with English/German among seven languages. Its
[device guide](https://cactuscompute.com/blog/needle-supported-devices) lists iOS
and Watch static-library targets. The published file metadata reports SHA256
`b6e02f048568ac5d01a2042556c658061e699acbc0aa2a1439f52f3d461dffeb`.
These are upstream claims/metadata, not local execution proof.

Bundle the model in both apps so evaluation is available offline immediately.
Reuse the existing PCM transcription seam with explicit Watch target support.
Keep Whisper selectable until comparison proves replacement quality. Measure
actual packaged size and peak runtime RAM separately from the model file size;
test the same English/German speech, names, noisy wrist recordings, silence,
longer clips, cold/warm latency and device battery/thermal behavior.

Whistle handles local dictation/transcription and optional call captions. Live
Gemini audio still follows the broker's audio path; canonical encrypted call
transcripts must not be duplicated by a second local transcript submission.

## Watch device gate

The handset in the current empty-chat Watch layout is decorative; existing
chats do not have the requested persistent three-action controls. Native
recording/transcription and ordinary assistant TTS exist, but native live
calling does not.

[Apple TN3135](https://developer.apple.com/documentation/technotes/tn3135-low-level-networking-on-watchos)
restricts low-level Watch networking, including WebSockets, to qualifying use.
Simulator networking does not establish physical-device permission. Test genuine
streaming/call lifecycle, mute, idle, wrist-down, Wi-Fi/cellular and absent-phone
operation early. Preserve the server's idle/billing behavior; continuous silent
audio is not a valid keepalive workaround.

The source audit, timing gaps and device gate inform this plan; no successful
native call, Whistle benchmark or new end-to-end run is claimed in this snapshot.


## Retained implementation and verification update — 21 October 2026

This section supersedes the historical 19 October planning status above.
The retained source implements response-owned activity/rainbow presentation,
minimized chronological skill runs, queued editing/steering,
Send-to-authoritative-Mate timing instrumentation, native call/tool
continuation, bundled Whistle/model package preparation and management,
authenticated Usage routing, expanded iOS notification replies, remote Project
folder/cloud metadata persistence and the Watch first-turn read fence.
Implementation does not establish complete visual, physical-device or timing
proof. The deferred voice provenance/activity follow-up (528) is excluded.

### Source publication and native provenance

Managed dev publication **`c8e7d4f6f09bcb077cd9c940a27a52888853c17d`** and
wait-deploy pass. The frozen native544 iOS/embedded Watch build-for-testing
also passes, with unchanged captured inputs: shipping SHA-256
`c3be49edbbeb4a9f46046a4adad8eb2ded6fc330c557c8769c65916ab5c5b026`,
1,842 release inputs and 2,151 total release/test inputs, original immutable
candidate `2add06a357e046b8d4b2edacfad64b9ed9d594f6`.

The active archive remains bound to that original candidate and frozen source.
Published dev additionally retains newer upstream reconciliation and auxiliary
publication differences: derived locale/Specification artifacts, the exact
upstream lockfile and Whistle packaging test classification/lint fixes. Do not
identify the archive as a byte-for-byte build of published dev. The retained
publication and native input manifests preserve the separate mappings.

### What the checks establish

| Evidence | Result and limit |
| --- | --- |
| Native509 notification regressions | All 78 requested iOS routing/preview/Workflow tests pass. The broader run has 597 passes, two failures and one skip; it is not an overall pass. |
| Native522 focused repaired Project/Watch classes | 191 pass, one opt-in skip; the skip is not physical Watch proof. |
| Native544 build-for-testing | iOS with embedded Watch compiles; no captured input changes. |
| Mac qualification | Compile-only evidence. The current route has no Mac unit-test runner; iOS Simulator units do not count as Mac runtime tests. |
| Native545 UI | Resource-interrupted at the disk reserve, exit 143; no accepted clip and no final passing UI result. |
| Publication tooling | All five selected Python files pass Ruff; seven packaging tests and 71 selected test annotation checks pass. Normal managed publication gates pass. |

The query/activity/Loaded Memories fixes identified during native537 are applied.
Their final visible behavior still needs a successful source-bound UI run and
recording. Prior failures/interrupted captures remain evidence, not passes.

### Material unfinished work

- Actual iPhone Storage per-chat deletion/reclamation remains unimplemented;
  preserve keys, drafts and outbox records when implementing it.
- Model package preparation/management is implemented. Physical-device Whistle
  linking, offline accuracy, memory/thermal/battery behavior and Watch execution
  remain unproved.
- Personal remote Project README/files/images and same-container offline reopen,
  durable offline sends, free-budget guest parity and real Watch pairing/call
  behavior still need their accepted device/product evidence.
- TASK-2444 still needs actual push receipt, notification editing/taps and exact
  destinations, login/Team handoff, privacy/claim/duplicate behavior and email
  Universal Links. See its verification document for retained checks.
- Default-routed Send-to-visible-Mate timing at or below 1,500 ms, current native
  core UI recordings and Apple camera parity with the published web camera
  toggle remain open.

### Delivery checkpoint — 13:24 Berlin

Version **0.28.0 (99)** is in its third release attempt (release557) and is still
compiling at this checkpoint. No accepted upload or TestFlight delivery is
established. Keep **iOS/iPadOS with Watch first, then Mac**; the release owner
must record each platform's archive validation, accepted upload, processing and
installed-binary result after it actually completes. Build98 remains the last
established delivered version in this document until those receipts are added.


## Release-owner delivery checkpoint

At **21 October 2026, 13:39 Berlin**, release557 is still compiling the iOS production application after the embedded Watch app linked and signed. No iOS or Mac archive/upload completion receipt exists yet. **No new TestFlight upload, processing completion, availability or installed build is claimed.** The last confirmed installed/delivered release remains **0.27.0 (98)**. The requested new release is **0.28.0 (99)** for iOS/iPadOS/Watch followed by macOS, minimum OS26.2.

Two earlier attempts stopped at the unchanged12GiB free-space reserve; their logs and source checks are retained. This third attempt remains active with the same frozen native source. Its normal serial release helper will validate/upload iOS before building/uploading Mac. Signed archives, account data and recovery evidence are preserved.

The exact running stage and any subsequent accepted-upload outcome must be read from the release receipts and final release-owner report. This dated checkpoint is not a claim that the session's delivery objective is complete.
