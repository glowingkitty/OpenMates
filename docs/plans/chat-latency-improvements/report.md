# Chat latency investigation and implementation

Updated 2026-10-11. Diagnosis Task: `12fb2012-be42-46f1-958c-babc378f1d02`. The implementation and focused/isolated checks are complete in session `6d3f`; the revised processing-feedback Specification was explicitly approved on October 11, and deployment and AFTER measurements are in progress.

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
    M --> N[Deferred title, summary, suggestions and metadata]
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

The [BEFORE data](benchmark-before.json) contains sanitized aggregates. Account/chat IDs, private CLI state and raw logs remain local. All retained CLI and browser recordings, including failed attempts, were uploaded. AFTER uses the same fixtures, prompts, model and client definitions once the scoped change is deployed; it first measures the ten-Workflow cohort, then removes only those benchmark drafts and measures zero Workflows after cache expiry.

Three samples per cell support a directional comparison, not a population p95 or provider-independent guarantee. Provider generation dominates first-visible-text time and can vary between runs. Backend phase durations and immediate composer paint measure the structural change more directly.

## Original diagnostic evidence

Before implementation, retained traces showed preprocessing median 3.87 seconds (40 spans), main phase 18.61 seconds (45), final billing 681 ms (39) and postprocessing 2.97 seconds (42). These unpaired observations include different request types and terminal paths; their medians must not be added.

A separate 250-span query contained 37 completed first-token records, with median worker-start-to-first-token 12.38 seconds. That excludes client preparation and may count a non-prose token. Four matched worker-log turns took 3.25–3.76 seconds before Jev, versus 0.433–0.534 seconds across the two Jev stages. Their Workflow preparation intervals contained 38 reads and 35 Vault decryptions. The source independently confirmed hydration before the 20-candidate cap.

Read-only diagnosis began at `64c9ff539162308ce50ee0d03c1f7d438f7f0770`; runtime checkout reported `1ec68002178408634781ff9fd653c12694ac91e2`; the initial workspace base was `faae158b110cc1b20aa2861ea35c7fec3305e990`. Suspect files matched byte-for-byte, but historical traces are not proven to use those exact loaded revisions. Sanitized diagnostic aggregates remain in [baseline-summary.json](baseline-summary.json).

## Remaining performance opportunities

Web rendering still deserves separate profiling. Normal private history loads 30-message pages and prunes its decrypted window toward 60 rows, with a 90-row cap and exceptions for preserved context. A 500-row TUI measurement therefore cannot be applied directly to a typical private web chat. Within each loaded window, streaming updates still rebuild cumulative PII mappings and call `messages.find` for every incoming row; unchanged documents are reused, but row lookup remains quadratic. Histories above the 160-row virtualization threshold disable virtualization while any message streams. An ID index, narrower row updates and pinned streaming-row virtualization are candidates for larger or expanded histories, with scroll, embed, privacy-window and final-content convergence evidence required before implementation. These are source findings, not measured web speedups.

The independent TypeScript TUI work in Task `TASK-8491`, session `8a64`, reports a synthetic 500-message layout improvement from 300.2 to 17.3 milliseconds at 160×50 and a task draft redraw improvement from 124.5 to 29.0 milliseconds. It was published to dev as `117b9fd9ba7377c0352353d7f624a72b49f7d415` and npm `0.27.0-alpha.53`, using an optimistic sent row, a transient assistant row and an animation timer that paints one cached row without parsing history. Its caption-only follow-up is `aa2839f576bdb1ba3024a5ca42ceb5ff541ca74b`. These peer-reported local rendering results support profiling similar web update costs; they measure neither server processing nor deployed web latency. Its isolated streaming and authenticated workspace checks passed; a saved-chat check failed before rendering on service availability and pairing. The TUI owns its separate verification and publication. The BEFORE server benchmark used global CLI `0.27.0`; the host now has `0.27.0-alpha.53`. Record the actual AFTER client version and treat this version change as a comparison limitation rather than attributing all CLI elapsed-time differences to backend changes.

Shared API history reconstruction performs sequential decryption/re-encryption and awaited WebSocket handlers can delay later control frames. Batch authorized history reads and ordered asynchronous admission are candidates for later work. Another active Task owns catalogue deduplication and telemetry; that work is excluded here.

Main-provider reasoning delay, tool-first responses and SDK output behavior need separate cohorts. API-key CLI/SDK sends currently wait for complete responses; faster backend preprocessing does not make that API emit partial text. Apple benefits from the shared backend changes, but native composer handoff and queued edit/steer controls are separate client work. The native backend event fields retain compatibility.

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
