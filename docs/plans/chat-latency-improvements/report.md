# Chat latency investigation and implementation

Updated 2026-10-11. Diagnosis Task: `12fb2012-be42-46f1-958c-babc378f1d02`. The implementation and focused/isolated checks are complete in session `6d3f`; the revised processing-feedback Specification was explicitly approved on October 11. Product revision `8fff53e54ceae234f3643814b69e561e8390b2a6` was deployed to dev web, API and workers, with the Directus queue schema installed. The original matched AFTER benchmark and separate ordinary-chat measurements are complete. The additional Send-readiness repair was published as `23319f80fc1792bd483df322debb69d78829f0f8`; exact-source browser readiness 2/2 and composer regression 10/10 passed without retries. Its backend/config diff is empty, preserving the deployed API and worker source. The ordinary and zero-Workflow web samples used the repaired web source; the earlier ten-Workflow web samples used `8fff53e`.

The accepted changes are immediate web composer handoff, first-stage model/Mate resolution and typing feedback, bounded saved Workflow discovery, and metadata-only warm-up on composer focus. Typing-time AI requests were explicitly rejected and are excluded. Queued follow-up editing and safe steering are tracked in the [queued-follow-up Plan](../chat-queued-followups/plan.yml).

## Findings and implementation

| Finding in the original flow | Accepted change | Scope |
| --- | --- | --- |
| Web added the pending row before it cleared the composer, waiting for asynchronous preparation and sender acceptance. | Snapshot and clear synchronously; insert one provisional sending row with a stable ID. Sanitize/prepare asynchronously, replace that same row, and retain disconnected sends for reconnect. Failed preparation restores the submitted draft only if no newer draft or chat switch intervened. | Web |
| First Jev stage shortlisted apps/Projects; complexity and Mate selection waited for detailed preprocessing. | Stage one decides complexity, task area, sensitivity flags, Mate topic/shift, apps and Projects. Application code immediately resolves the permitted model/Mate and emits typing feedback. Detailed stage two reuses those decisions. | Shared backend for web, authenticated CLI and Apple |
| Saved Workflow discovery built every UI summary before applying the candidate cap, including individual blob reads and Vault decryptions. | Select up to 20 candidates using the existing ordering, retrieve routing title/description blobs in a batch and batch-decrypt them. Cache bounded metadata encrypted with the user's Vault key for 30 seconds with scope/revision invalidation; reauthorize selected graphs fresh. | Shared first-party path |
| Workflow data was cold when the user submitted a request. | Authenticated composer focus sends only the scope and tracing hint. A rate-limited background request warms eligible metadata without draft text or inference. Failure leaves normal cold discovery available. | Web focus hint; shared backend cache |
| Skill cards always appear together above assistant text. | The approved web redesign places cards at their canonical placeholder positions, grouping adjacent calls and collapsing completed groups into expandable summaries. | Web; [evaluation report](interleaved-skills-evaluation.md) and [implementation Plan](../assistant-response-ui/plan.yml) |
| Editing a queued message could change rendered history while its old queue payload still executed. | Same-ID revision compare-and-swap across client ciphertext, durable history and encrypted inference cache, with authoritative acknowledgements and claimed-message fencing. | Shared queue and web edit UI |

The focused composer shows the labeled Send button. A blurred nonempty draft shows only a round orange up-arrow button. The focused translucent gray background is removed. Web mic recordings now insert the corrected transcript as editable composer text, preserving surrounding notes and the mapped insertion point; they no longer create new audio embeds or upload permanent recording files. Historical audio embeds, uploaded audio and speech output remain compatible. Native Apple recording is a separate path and is unchanged in this web increment.

## Processing flow after the changes

```mermaid
flowchart TD
    F[Composer focus] --> W[Optional authenticated metadata-only Workflow cache warm-up]
    A[Send clicked] --> B[Immediate local history row and cleared composer]
    B --> C[PII/privacy preparation, encryption, persistence preflight and authenticated submission]
    C --> Q{Assistant already active?}
    Q -->|Yes| U[Durable queued follow-up, synced state and revision]
    Q -->|No| D[Worker admission, credits and minimal routing context]
    D --> E[Jev stage one: complexity, Mate topic, apps and Projects]
    E --> G[Resolve permitted model and Mate]
    G --> H[Emit selected-Mate typing feedback]
    H --> I[Authorized metadata and Jev stage two: skills, Focus modes, Project Focus modes and Workflows]
    W --> I
    I --> J[Safety, consent, budget and main prompt gates]
    J --> K[Main model and tool cycles]
    U -->|Ordinary queue| L[Process after active response completes]
    U -->|Steer instead| S[Preflight latest revision at completed-tool boundary]
    S -->|Compatible and authorized| K
    S -->|New gated context or no safe continuation| L
    K --> M[Final billing and answer persistence]
    M --> N[Awaited postprocessing: title, summary, suggestions and metadata]
```

Typing feedback is presentation readiness, not permission to execute tools. Explicit model/Mate overrides retain precedence; Project access, Focus consent, credits, safety and billing checks still apply before main execution. Stage two does not silently change the already resolved model. Failed or rejected turns terminate the early indicator.

A steer keeps completed tool results and the current assistant message. It does not cancel a running tool. The latest exact queued revision must pass the existing preprocessing gates and be compatible with the active model/tool/Focus/Project context before it is consumed once. Incompatible context remains an ordinary follow-up with a visible deferred status.

## Controlled BEFORE measurements

A separate disposable dev account and Project ran the same simple and complex prompts through authenticated CLI and web, using Gemini 3.8 Flash with auto routing. These are newly collected benchmark cohorts, separate from the original mixed diagnostic traces. Each cell contains three successful turns.

| Cohort | CLI median first visible text | Web median first visible text |
| --- | ---: | ---: |
| Zero saved Workflows, simple | 13.69 s | 15.12 s |
| Zero saved Workflows, complex | 20.09 s | Excluded: original probe timed visible reasoning |
| Ten disabled blank Workflow drafts, simple | 16.31 s | 16.78 s |

The old web composer cleared 3.0–4.4 seconds after Send. Matched backend logs measured preprocessing medians of 2.370 seconds for the zero-Workflow cohort (12 turns) and 4.328 seconds for the ten-Workflow cohort (6 turns). Client-separated medians were 1.982 versus 3.638 seconds for CLI and 2.645 versus 4.381 seconds for web.

A bounded retained-video audit verified that all six simple web turns timed authored answer text. All three complex web turns timed the visible reasoning section and are excluded from first-answer comparisons. The CLI and backend measurements are unaffected. Original raw metrics remain in the data with explicit eligibility annotations; visual frame intervals are not substituted as precise send-to-answer timings. The AFTER probe explicitly excludes thinking and skill activity editors.

The [BEFORE data](benchmark-before.json) contains sanitized aggregates. Account/chat IDs, private CLI state and raw logs remain local. All retained CLI and browser recordings, including failed attempts, were uploaded. AFTER used the same fixtures, prompts, model and client definitions: it first measured the ten-Workflow cohort, then removed only those benchmark drafts and measured zero Workflows after cache expiry.

Three samples per cell support a directional comparison, not a population p95 or provider-independent guarantee. Provider generation dominates first-visible-text time and can vary between runs. Backend phase durations and immediate composer paint measure the structural change more directly.

## Deployed AFTER measurements

These measurements used backend revision `8fff53e`, Gemini 3.8 Flash with auto routing and CLI `0.27.0-alpha.54`. The backend consumers were rebuilt from the explicit coordinated runtime target and passed their managed health checks. The ten-Workflow web calls used web revision `8fff53e`; the zero-Workflow web calls used the later Send-readiness revision `23319f8`, whose backend/config diff was empty. The matched AFTER sample contains nine successful CLI turns, nine successful web turns and 18 owned backend phase joins. Each client cell below contains three successful turns.

| Matched cohort | BEFORE first answer | AFTER first answer | Observed difference |
| --- | ---: | ---: | ---: |
| CLI, zero Workflows, simple | 13.686 s | 14.123 s | 3.2% slower |
| CLI, zero Workflows, complex | 20.087 s | 17.053 s | 15.1% faster |
| CLI, ten Workflows, simple | 16.311 s | 13.599 s | 16.6% faster |
| Web, zero Workflows, simple | 15.119 s | 13.712 s | 9.3% faster |
| Web, zero Workflows, complex | Excluded: original probe timed visible reasoning | 21.209 s | No authored-answer comparison |
| Web, ten Workflows, simple | 16.776 s | 11.440 s | 31.8% faster |

The ten-Workflow web composer cleared 13–27 milliseconds after Send and the user row painted 107–314 milliseconds after Send. In the zero-Workflow web cohort, the simple composer cleared at a 15-millisecond median and the user row painted at a 185-millisecond median. Matched backend preprocessing fell from 4.328 to 2.370 seconds for the ten-Workflow cohort, a 45.2% reduction across six completed calls; the zero-Workflow AFTER backend median was 2.175 seconds across 12 calls. The empty-Workflow complex CLI typing feedback fell from 12.559 to 7.980 seconds. The empty simple CLI first answer was 3.2% slower; these small samples do not support claiming every chat became faster.

The ten owned Workflow fixtures were removed only after all six ten-Workflow AFTER calls succeeded; the empty list was then verified after cache expiry. Two earlier empty-Workflow web attempts stopped before submission with the model-selection loading guard. Their recordings and partial timing records are retained, and neither attempt counts as a completed inference call. The repaired probe checked readiness in the same composer as the unique Send control and retained its readiness at the click; all six zero-Workflow web calls then passed on the first attempt. Authored first-answer timing is separate from completed UI attribution. The original ten-Workflow probe could briefly label completion while the active status later remained visible, so its final-status measurement is marked `completion_status_not_validated`. The newer zero-Workflow probe validated completed UI state for all six web turns.

The general routing changes apply without a Project or saved Workflows. Separate AFTER-only cohorts used the exact ordinary questions “Find AI events in Berlin” and “What's the capital of Spain?” through authenticated CLI and web, with no Project flag or mention, no forced model and an empty saved-Workflow list. The event question includes real skill execution; the capital question exercises a short factual answer. Six CLI turns, six first-attempt web turns and 12 owned backend phase joins completed. These newly requested prompts have no matched BEFORE baseline, so their measured times must not be reported as speedup percentages. The web turns used revision `23319f8`; the backend remained at `8fff53e`.

| Ordinary CLI question, three successful turns each | First authored answer | Selected-Mate typing | Command finished | Backend preprocessing |
| --- | ---: | ---: | ---: | ---: |
| Find AI events in Berlin | 19.83 s | 4.52 s | 51.84 s | 1.649 s |
| What's the capital of Spain? | 7.96 s | 4.56 s | 14.29 s | 1.621 s |

| Ordinary web question, three successful turns each | First authored answer | Completed UI state | Backend preprocessing |
| --- | ---: | ---: | ---: |
| Find AI events in Berlin | 23.235 s | 32.981 s | 1.372 s |
| What's the capital of Spain? | 11.238 s | 14.197 s | 1.288 s |

The exact owned-chat log join verifies no Project target in all six requests. Each Berlin request completed one tool cycle and rendered an `events/search` result; routing preselected `events-search`, `news-search` and `web-search`. Each capital answer identified Madrid, with zero selected apps or tools. Stage-one/stage-two medians were 483/1,011 milliseconds for events and 493/980 milliseconds for the capital. Main-stream medians were 18.026 and 3.022 seconds respectively. These phase medians are measured separately and must not be added to explain a client median; first prose also does not imply the tool-backed response or terminal command is finished. The [ordinary-chat data](ordinary-chats-after.json) records sanitized results and limits. Event listing usefulness and live scheduling were not independently reviewed.

The earlier ordinary web attempts revealed an enabled-Send race while a new draft's exact model preference restored. One retained click recorded model readiness false at dispatch and no optimistic row; the loading guard rejected it. The focused and minimized Send controls were aligned with the same readiness gate. All six subsequent ordinary web turns passed on the first attempt with a fresh two-message context, a ready model selector and one visible composer. Browser Send-click timing and CLI accepted-command timing start at different boundaries, so their ordinary medians are descriptive rather than a client-to-client speedup claim. The completed UI state is distinct from the last authored text change. The [matched AFTER data](benchmark-after.json) and [comparison](benchmark-comparison.json) preserve source identities, eligibility and sample limits.

## Original diagnostic evidence

Before implementation, retained traces showed preprocessing median 3.87 seconds (40 spans), main phase 18.61 seconds (45), final billing 681 ms (39) and postprocessing 2.97 seconds (42). These unpaired observations include different request types and terminal paths; their medians must not be added.

A separate 250-span query contained 37 completed first-token records, with median worker-start-to-first-token 12.38 seconds. That excludes client preparation and may count a non-prose token. Four matched worker-log turns took 3.25–3.76 seconds before Jev, versus 0.433–0.534 seconds across the two Jev stages. Their Workflow preparation intervals contained 38 reads and 35 Vault decryptions. The source independently confirmed hydration before the 20-candidate cap.

Read-only diagnosis began at `64c9ff539162308ce50ee0d03c1f7d438f7f0770`; runtime checkout reported `1ec68002178408634781ff9fd653c12694ac91e2`; the initial workspace base was `faae158b110cc1b20aa2861ea35c7fec3305e990`. Suspect files matched byte-for-byte, but historical traces are not proven to use those exact loaded revisions. Sanitized diagnostic aggregates remain in [baseline-summary.json](baseline-summary.json).

## Remaining performance opportunities

Web rendering still deserves separate profiling. Normal private history loads 30-message pages and prunes its decrypted window toward 60 rows, with a 90-row cap and exceptions for preserved context. A 500-row TUI measurement therefore cannot be applied directly to a typical private web chat. Within each loaded window, streaming updates still rebuild cumulative PII mappings and call `messages.find` for every incoming row; unchanged documents are reused, but row lookup remains quadratic. Histories above the 160-row virtualization threshold disable virtualization while any message streams. An ID index, narrower row updates and pinned streaming-row virtualization are candidates for larger or expanded histories, with scroll, embed, privacy-window and final-content convergence evidence required before implementation. These are source findings, not measured web speedups.

The independent TypeScript TUI work in Task `TASK-8491`, session `8a64`, reports a synthetic 500-message layout improvement from 300.2 to 17.3 milliseconds at 160×50 and a task draft redraw improvement from 124.5 to 29.0 milliseconds. It was published to dev as `117b9fd9ba7377c0352353d7f624a72b49f7d415` and npm `0.27.0-alpha.53`, using an optimistic sent row, a transient assistant row and an animation timer that paints one cached row without parsing history. Its caption-only follow-up is `aa2839f576bdb1ba3024a5ca42ceb5ff541ca74b`. These peer-reported local rendering results support profiling similar web update costs; they measure neither server processing nor deployed web latency. Its isolated streaming and authenticated workspace checks passed; a saved-chat check failed before rendering on service availability and pairing. The TUI owns its separate verification and publication. The BEFORE server benchmark used global CLI `0.27.0`; the matched AFTER benchmark used `0.27.0-alpha.54`. That client-version change limits attribution of CLI elapsed-time differences to backend changes.

Shared API history reconstruction performs sequential decryption/re-encryption and awaited WebSocket handlers can delay later control frames. Batch authorized history reads and ordered asynchronous admission are candidates for later work. Another active Task owns catalogue deduplication and telemetry; that work is excluded here.

Main-provider reasoning delay, tool-first responses and SDK output behavior need separate cohorts. API-key CLI/SDK sends currently wait for complete responses; faster backend preprocessing does not make that API emit partial text. Apple benefits from the shared backend changes, but native composer handoff and queued edit/steer controls are separate client work. The native backend event fields retain compatibility.

Ordinary-chat measurements also expose a completion tail: the capital CLI first-answer median is 7.96 seconds while command completion is 14.29 seconds; event-search medians are 19.83 and 51.84 seconds. Source shows that finalization awaits billing, encrypted recovery preparation and AI cache persistence before the final response marker. Queue ownership can clear before postprocessing, but postprocessing still runs as an awaited step in the same worker task. The CLI waits up to 12 seconds for its postprocessing event after the final frame, then waits for encrypted recovery and metadata persistence acknowledgements. These are separate response-ready and command-complete boundaries. The medians alone do not identify which step caused each observed tail. Timestamping final-marker reception, postprocessing arrival, collector resolution and persistence acknowledgements is the next bounded investigation; optional suggestions, inspiration and debug work should leave the terminal critical path only after durable enqueue and without weakening billing, queue ownership or metadata convergence.

## Verification and rollout

The accepted permanent Specifications cover immediate handoff, focused/minimized actions, early routing, typing lifecycle, metadata-only warm-up and queued revision/steering semantics. Focused local unit and syntax/lint checks run in the worktree. Rendered component checks precede broader authenticated browser/WebSocket/CLI checks through isolated GitHub CI. Real inference comparisons run only on dev with disposable state.

The [verification status](verification.md) maps accepted outcomes to actual evidence and remaining checks; passing local helper tests alone do not imply passing product or deployed checks.

Deployment must use the managed session integration and explicit runtime coordinator lease. The Directus queue metadata schema and transaction extension must be installed before API/AI consumers use the new durable revision APIs. Record immutable CI source, deployed source, failures and all video links; complete implementation Tasks only after verification and deployed AFTER measurements.

## Source references

References below are pinned to the initial review commit. The suspect files were also compared with the runtime and Plan workspace.

- [Web optimistic history dispatch and later composer clear](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/frontend/packages/ui/src/components/enter_message/handlers/sendHandlers.ts#L2088)
- [Web durable preflight acknowledgement](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/frontend/packages/ui/src/services/sendersChatMessages.ts#L2312)
- [Apple accepted-send composer clearing](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift#L4580)
- [Apple send pipeline](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/apple/OpenMates/Sources/Features/Chat/ViewModels/ChatViewModel.swift#L5973)
- [Jev stage-one app/Project routing](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/backend/apps/ai/processing/jev_preprocessing.py#L361)
- [Detailed Jev decisions](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/backend/apps/ai/processing/jev_preprocessing.py#L404)
- [Blocking saved Workflow discovery](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/backend/apps/ai/processing/preprocessor.py#L2414)
- [Workflow discovery service construction](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/backend/apps/ai/processing/context_preselection.py#L76)
- [Candidate cap applied after summary hydration](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/backend/apps/workflows/skills/saved_workflow_context.py#L31)
- [Unbounded persisted Workflow list](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/backend/core/api/app/services/workflow_service.py#L719)
- [Workflow summary decryption](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/backend/core/api/app/services/workflow_service.py#L2610)
- [Existing Vault batch decryption utility](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/backend/core/api/app/utils/encryption.py#L999)
- [Tier defaults and thinking levels](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/backend/apps/ai/processing/model_routing.py#L28)
- [History reconstruction on the API critical path](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py#L1645)
- [History rendering and streaming virtualization](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/frontend/packages/ui/src/components/ChatHistory.svelte#L913)
- [Authenticated CLI sender](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/frontend/packages/openmates-cli/src/client.ts#L8181)
- [TypeScript SDK full-response path](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/frontend/packages/openmates-cli/src/sdk.ts#L2208)
- [Python SDK full-response path](https://github.com/glowingkitty/OpenMates/blob/64c9ff539162308ce50ee0d03c1f7d438f7f0770/packages/openmates-python/openmates/sdk.py#L3176)

## Further ordinary-chat optimization

The user requires authored streaming to start within 2–3 seconds for a simple no-skill request. The 7.957-second CLI and 11.238-second web capital medians miss that target. An additional ordinary web diagnostic found roughly 2.9 seconds of client preparation before persistence preflight, including redundant active-focus reads. It is a separate single CPU-profiled run, not part of the comparison samples. Worker logs show two Jev calls even with no app or Project candidates; the capital's stage-two median was 980 milliseconds. Main agentic-context preparation took roughly 0.7–0.8 seconds before provider admission. The previous CLI terminal setup and backend wall clocks were not synchronized precisely enough to attribute their remaining gap; no exact provider time-to-first-token or network-ingress duration is inferred from those clocks.

The current local increment moves the required independent public safety/language/model/presentation decisions into the first routing response, validates them and reuses them. The detailed stage still discovers authorized candidates and runs its own Jev request when any exist or discovery is uncertain. Only a confirmed empty inventory with complete valid public decisions omits that second request. Default model/thinking settings, safety and consent stay in effect.

A draft-free warm-up now uses web composer focus and the TUI's existing authenticated activity connection; saved CLI sends also hint on their existing request connection. Encrypted Workflow routing metadata receives sliding two-hour Dragonfly retention and a persistent scoped mutation generation. Browser Project/Task prefetch uses existing bounded, mutation-invalidated tab caches. Project access, active Focus and accepted Plan checks stay fresh: broad two-hour server caching of those records would miss mutation paths and authorization changes. This increment has not yet been deployed or timed. The new probes capture submission wall time after terminal setup and distinguish authored text, reasoning, tool activity and final metadata.
