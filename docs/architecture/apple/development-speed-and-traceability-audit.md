# Apple development speed and Specification traceability audit

Audited 2026-10-06 from retained evidence for the current Apple development
chat. This is a bounded audit, not a new verification run. Native inputs were
frozen during the audit. No build, GUI test, profile, deployment, account
operation, cleanup, or production-source edit was performed.

## Highest-impact changes

| Priority | Concrete change | Evidence and expected effect | Completion check |
|---|---|---|---|
| 1 | Freeze one reviewed source fingerprint before the final native gate; use one native execution owner and source-bound build products. Complete cheap input, annotation, signing, CI capability and integration-base checks before native compilation. | Retained receipts contain repeated compilation and changed inputs. The release helper already supports fingerprints and archive reuse; consistently use those mechanisms. This reduces invalidated evidence, stale artifacts and preventable rebuilds. | Each test/archive/upload receipt identifies the actual local inputs and integration base. Reuse a completed operation only when its relevant inputs match. |
| 2 | Consolidate viewport reveal and safe tap logic in the existing native UI helper layer. Use measured bounds, short bounded drags and the actual interactive element; exclude overlay hit regions and wait for presentation completion. | Audio retry888 overshot the card by four full-page swipes; another recorded tap hit the floating scroll-to-top control. These were harness interaction defects, not established audio renderer defects. Candidate889 fixes the focused test; generalize only after its root-owned gate passes. | Preserve visibility, geometry, fullscreen, seeking and cold-boot assertions. A failing reveal reports viewport, target and overlay bounds before another expensive retry. |
| 3 | Isolate the welcome-card animated background and suppress unchanged privacy-model status publication. Keep semantic text outside the background TimelineView. | Matched installed Mac build93 Time Profiler shows SwiftUI/AttributeGraph and layout dominating five potential hangs of 296.8–575.2 ms. WelcomeResumeCard timeline has 770 ms inclusive sample weight; local-model progress → privacy status publication → graph work appears in a hang. Narrow edits address measured invalidation sources. | Preserve reduced motion, visibility, semantic identity, selection and model lifecycle. Verify background ticks do not rebuild card text; unchanged status emits no event, changed progress and terminal states still do. Compare an equivalent source-bound profile after the focused changes. |
| 4 | Treat Specification ownership, test mapping, test strength and current run evidence as separate gates. Correct overly strong metadata and use precise existing assertions. | The current generated registry has 500 required Apple assertions: 106 with direct tests, 100 supporting only, 294 without Apple tests. No verified-source run receipts have been ingested as current proof. Recent GUI and unit evidence still exists. Some direct unit tests only check parser output or constants. | Source headers cite existing paths and IDs. Partial tests stay supporting. Current proof is imported only from matching test/assertion fingerprints and a source-bound run. |
| 5 | Preflight the selected CI execution route before source upload, and resolve integration against the session's actual merged commit. | Current publication preparation encountered Mac/Linux process-owner compatibility and an unavailable local Docker uploader. Comparing with an old Task HEAD introduced a wrong baseline; integration owner892 is reconciling the session's actual merged commit. | A capability check selects the authorized dev-host uploader/coordinator before staging source. The source base comes from the session receipt, not cached Task text. Preserve existing serialized integration and runtime leases. |
| 6 | Add capacity estimates and recoverable retention decisions before large trace/archive operations. | The retained Animation Hitches capture is malformed after saving/trim ENOSPC. Approved cleanup recovered storage while retaining current archives, dSYMs, screenshots and logs. | Check free capacity against the planned operation; stop recording before exhausting reserve. Preserve current evidence and approved cleanup boundaries. Do not clear active caches and incur Simulator cold starts. |

These changes target observed work and defects. No total chat-time estimate,
model-time estimate or percentage speed improvement is claimed.

## Observed verification cost

The runtime audit summary extracts timestamps and exit status only, without
printing commands or private payloads. Groups below are disjoint filename
prefixes, not necessarily disjoint execution intervals. Summed operation time
can overlap, and includes unsuccessful work and useful engineering iterations.
It cannot be interpreted as avoidable elapsed time.

| Retained receipt family | Timed operations | Sum of operation minutes | Nonzero or absent exit status | Changed source during operation |
|---|---:|---:|---:|---:|
| build* | 56 | 113.4 | 17 | 8 |
| native-unit-build* | 69 | 172.7 | 34 | 0 |
| native-ui-build* | 88 | 130.2 | 12 | 0 |
| native-focused* | 21 | 42.4 | 11 | 0 |
| native-supplemental-ui* | 5 | 32.7 | 5 | 0 |

Seven retained focused/supplemental runs 750, 755, 770, 784, 811, 818, 822 each
took roughly 4.1–8.7 minutes. Extracting the cause from existing failure
attachments before rerunning therefore has material value. The count of
receipts alone does not show that every rerun was unnecessary.

Current evidence includes 197 focused unit passes in native877/unit-iphone3,
followed by GUI failures under investigation and a root-owned later gate.
That unit pass is useful supporting evidence; it does not prove the entire
native GUI scope or the latest source. Publication and final gate status belong
to the root's live receipts.

## Source and Specification mapping findings

The source scan found 483 Swift files under Apple Sources, 254 containing a
Specification path in their first 6000 characters. This includes generated
files, fixtures and support code; the remaining 229 are discovery candidates,
not 229 confirmed compliance failures. The following production files were
read and have concrete ownership gaps. They already implement behavior in
existing Specifications; these mappings need no invented assertions or YAML
source-path fields.

| Production file | Exact existing Specification and assertion links to add to its header | What the file owns |
|---|---|---|
| apple/OpenMates/Sources/Shared/Components/ChatHistoryRenderDocument.swift | specifications/features/chats/specification.yml; chats.rendering.assistant-document-convergence; chats.rendering.inline-entity-interaction | Stable semantic block order, identity, embed references and inline entity representation. Other files own live presentation and actual interaction. |
| apple/OpenMates/Sources/Features/Embeds/Views/EmbedPreviewCard.swift | specifications/features/chats/specification.yml; chats.layout.responsive-history; chats.rendering.inline-entity-interaction | Compact card sizing, preview dispatch and interactive opening. This header is implementation ownership, not proof of every assertion clause. |
| apple/OpenMates/Sources/Core/Networking/SyncManager.swift | specifications/architecture/sync/specification.yml; sync.startup.bounded-phases; sync.surface.semantic-parity | Requests the bounded phased protocol and consumes its phases. Redis readiness and server-side payload restrictions are owned elsewhere; do not attach those assertions to this file. |

architecture.sync is approved in the inspected source; feature.chats is draft
with existing implementation authorization. Adding links does not create a
fingerprint approval receipt or change the Specification's status. These exact
mechanical header edits were handed to the parent for application after its
native freeze. This audit did not modify frozen source.

## Test mappings that need correction

The generated assertion index provides reciprocal assertion → test path/line
links, but the scanner cannot determine whether an assertion is actually proved.
Two inspected examples demonstrate why a semantic review is required:

| Existing test declaration | Current metadata | Required correction and reason |
|---|---|---|
| ChatHistoryRenderDocumentTests.testStableMessageBuildsOrderedWebSemanticBlocksOnce | direct for chats.rendering.assistant-document-convergence, chats.rendering.inline-entity-interaction, chats.surface.semantic-parity | Change to supporting and retain the same IDs. It constructs a final synthetic message and checks semantic blocks/identity; it does not exercise progressive presentation, mounted interaction, live completion, reopen, sync or shared reconstruction. |
| ChatHistoryRenderDocumentTests.testResponsiveChatLayoutMatchesWebBreakpoints | direct for chats.layout.responsive-history, message-input.layout.responsive-parity | Change to supporting and retain the same IDs. Four policy constants do not establish rendered hierarchy, wrapping, clipping, composer clearance or cross-device geometry. |

Other parser/policy tests marked direct for broad chats.surface.semantic-parity
need the same focused review before their results are imported as direct proof.
Do not remove useful tests or promote fixture tests to fill a registry count.
The task-board assertions context-menu, drag-move, workflow-run and edit have
supporting UI/unit maps but no direct map; this is an honest coverage gap, not a
missing-comment defect. Their assertions combine UI, lifecycle and encrypted
write behavior, requiring more than a local fixture to prove the full contract.

The required Apple 500 count spans both approved and draft bundles and many
shared/backend assertions. It must not become a demand for 500 new Apple tests
or an unapproved expansion of this release. Determine each surface's actual
applicability and existing accepted verification scope before adding coverage.

The exact runtime-only patch is
.runtime/followups98/development-audit893/mechanical-linkage.patch. After
frozen inputs are released: apply the three source headers and two
supporting classifications, regenerate the assertion index/coverage with
scripts/specifications.py generate, validate affected bundles and annotations,
and check the scoped diff. Metadata edits do not require a new GUI execution
solely for their comments. Existing successful runs can be attached only where
their tested source, assertion fingerprints and mapped tests remain valid.

## Retained evidence and limits

- Runtime quantitative audit: .runtime/followups98/development-audit893/summary.json.
- Current registry: specifications/generated/assertion-index.yml and coverage.yml.
- Source-bound Mac profile: .runtime/followups98/mac-perf857/analysis-report.md and analysis-followup.md. CPU categories are inclusive sample weights and overlap; accessibility traversal adds overhead. The malformed Animation Hitches trace cannot establish a frame-budget pass.
- Audio harness failure analysis: .runtime/followups98/native877/audio-retry889-investigation.md. Candidate's parse/diff checks passed; root owns GUI outcome.
- Existing Specification gates: specification-inventory874.log and specification-changed879.log. Passing scanner checks do not resolve the semantic strength defects above.
- Publication integration: .runtime/followups98/publication880/integration-review892/actual-source-base/report.json. Its owner is reconciling the actual integration baseline; this audit starts no publication work.

Remaining work is the scoped mapping corrections, root-owned current GUI gate,
and accepted publication checks. Broader source inventory and full Apple
contract coverage are follow-up work, not silently added release gates.
