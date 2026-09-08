# TASK-16 investigation and deferred activity

Session: 37a6. Worktree: agent-37a6. Actual Codex thread: 01a080f6-cf4c-75c3-b1ce-11e2c225f50b. Assigned task: TASK-1503.

Existing task activity was read before investigation: creation only, no earlier worker result. Task connection encountered HTTP 429. Coordinator requested no Tasks API retries for at least ten minutes and serialized recovery; retain this milestone for later acknowledged posting. No account-memory or runtime mutation performed.

## Distinct findings

- Markdown: extractMathFormulas runs before Markdown parsing and treats the dollar before derived as the closing delimiter for state. It does not protect code spans or fences in extraction. Existing markdownParser.preprocess.test.ts is a focused extension candidate.
- Images: ImageResultEmbedPreview removes the failed img but keeps UnifiedEmbedPreview with an image-placeholder. ImagesSearchEmbedPreview hides failed images via offlineImageHandler without updating previewThumbnails or the full-width-image layout. Source result data should remain unchanged.
- PDF: pdf-view-page-layout.ts intentionally ships metadata only, without screenshot_s3_keys or AES credentials. PDFEmbedPreview requires screenshot key and credentials to load a thumbnail. This proves missing public media for that fixture, not a private-PDF decryption failure. Private-PDF failure remains unconfirmed.

## Gates

No product code changed. Existing Chats Specification is draft; check-approval reports missing approval for this session. No existing assertion specifically defines failed-result omission or literal dollar parsing. Compact chat-content-rendering Specification drafted for exact-artifact approval before authoritative test changes.

Focused checks should separately cover literal runes/code versus valid math/currency, mixed/all-failed image results and replacement sources, and PDF available/missing/failed media. Preview fixtures should use bare chrome=0 URLs. Automated tests must use canonical tests.py dispatcher; current dispatcher uses isolated GitHub execution, with focused units local.

## Probe and review evidence

A Node probe transpiled the two unchanged extraction functions from markdownParser.ts with the installed TypeScript compiler. Input `Use $state and $derived for reactivity.` extracted `state and` as inline math. Inline code and fenced JS containing the same runes were also incorrectly extracted. A delimited x-squared equation remained math. This is source-level diagnostic evidence, not the required authoritative red test or browser proof.

The canonical unit attempt (`scripts/tests.py run --session 37a6 --suite vitest --spec frontend/packages/ui/src/components/enter_message/utils/__tests__/markdownParser.preprocess.test.ts --detach`) failed before test execution: Unknown E2E spec. Inspection confirms the dispatcher only takes its local unit path without --spec; the current unit runner has no focused-file selection. No test pass or red gate is claimed.

Specification validation passed; generated registry/index/coverage refreshed. Review artifact: /tmp/opencode/specification-approvals/feature.chat-content-rendering-fb0f066cb26df271.approval.json. Fingerprint: fb0f066cb26df271846385bfcba211d86fc93e517cfaabbcb85c8d121329a250. Awaiting explicit exact-PDF approval before product edits. No deployment or browser proof yet.

Observed process inefficiency: a unit file passed through the documented --spec flag was treated as E2E only after publishing a CI source. Existing ci_dispatch.py separates unit routing only when --spec is absent. Smallest recommended deterministic audit/test improvement: reject unsupported unit-file selectors before ci-source publication (or provide focused unit selection); no prompt prose needed.

## Existing-contract recheck (supersedes prior draft)

The separate feature.chat-content-rendering draft and its approval PDF are withdrawn, unapproved. No product code changed.

| Requested behavior | Existing contract | Disposition |
| --- | --- | --- |
| Preserve prose/code and authored formatting | chats.rendering.assistant-document-convergence; models.AssistantRenderDocument | Existing owning contract. Add chats.rendering.literal-dollar-markdown to define delimiter boundaries explicitly, with two examples covering runes/prose/code and currency/escape/math. |
| Hide failed image render slots | chats.rendering.assistant-document-convergence; public-example-chats.transcript.safe-rendering | Existing ownership and broad safe rendering. Exact slot omission is new semantics: add chats.rendering.failed-image-slots, with two examples for mixed/replacement and all-failed results. |
| Available PDF embed previews | chats.rendering.assistant-document-convergence; public-example-chats.transcript.safe-rendering; PublicExampleChat.embeds | Reuse existing requirements; no new PDF requirement. Investigate media availability before deciding any implementation change. |
| Public PDF private-media safety | public-example-chats.transcript.safe-rendering; PublicExampleChat.embeds renderable_without_provider_credentials | Exact current bundle has explicit reviewed approval in session 6365, fingerprint e53c1ac327993825e19716c865be2aff5f1e37dd8f79f1f01035d1113463ec4e. Prior session-only approval lookup was insufficient to identify this existing approval. |

Chats currently has no explicit per-bundle approval receipt in the shared store inspected; existing draft requirements are ownership mappings, not claimed approved behavior. The revised approval artifact contains the full existing Chats bundle with only two added assertions, their required example-group references, and exactly two examples per assertion highlighted. Public Example Chats remains unchanged. Exact always-visible PDF error copy and new PDF states from the withdrawn draft are not proposed.

## Independent public PDF investigation

Continued under approved public-example-chats.transcript.safe-rendering; pending Chats additions untouched.

Two distinct causes:
1. `pdf-view-page-layout.ts` deliberately supplies metadata only. Import sanitization in `scripts/create-example-chat-from-share.mjs` removes screenshot_s3_keys, aes_key and aes_nonce. PDF preview and fullscreen correctly require authorized screenshot data; no public page-image field is supported here. Restoring original private keys or fabricating source page images is not a valid fix.
2. `PdfViewEmbedPreview.svelte` uses `icon_rounded visible` for missing-media fallback. `styles/icons.css` has no matching rule. The existing `icon_rounded view::after` rule draws visible.svg. This is an implementation-level wrong-class defect explaining the empty fallback tile. Minimal intended repair after red proof: reuse `icon_rounded view`. Original uploaded-PDF card and fullscreen use the already-defined `icon_rounded pdf` and do not share this wrong class.

Prepared isolated `PdfViewEmbedPreview.preview.ts` and `components/pdf-view-preview.spec.ts`. Added only a test id to source; the incorrect class remains intact for RED. Fixture contains no screenshot credentials and uses legacy synthetic id to avoid embed-store lookup. Test checks actual ::after image, page information, positive icon geometry, hover/focus and Enter callback. Contract metadata validation passed. No new semantic requirement.

Canonical test dispatch for source d934853e64c6700f5a8d94959b8bdf1d1d3dd04f returned jobs=[] and held_specs=[components/pdf-view-preview.spec.ts]: "New spec requires dependency classification before dispatch". No browser run, recordings, or red/green evidence exist. Current canonical ci_coverage.partition reads its canonical manifest, so editing only the worker copy cannot admit execution. Required shared CI admission: add components/pdf-view-preview.spec.ts to scripts/ci_coverage_manifest.json groups.browser_component_contract.specs (public, no account, provider or cloud dependency), under coordinator ownership of shared runtime. Then dispatch phone/laptop, inspect RED, apply the one-class repair, rerun GREEN and deliver evidence. No shared runtime change performed by this worker.

The initial basename-only component dispatch was rejected; nested spec paths must be relative to tests/. Existing dispatcher selection code already defines that behavior. A proof-runtime call signature was corrected during review before any browser execution. Existing helper example is sufficient coverage; no new workflow prompt is warranted.

## Admission and first RED

Coordinator explicitly authorized dependency classification. Scoped admission deployed as e82d4816679d3cd8e00e1bcc0d626c8aa6872cf7, preserving committed admissions from other workers. Initial 3-way integration conflicted on adjacent manifest insertions; using a separate insertion location preserved both entries and deployed normally. No pending Specifications deployed.

RED: request db88daf98b95318d8346456577b31eebabea46214c12a1912fc326bca02c3165, source efee2eeab4b26d55dc5ff4bfd54f2796ecb45700, GitHub run 34236422711. Both attempts reached intended assertion: expected background image containing visible, actual none. Real isolated browser run; no auth provisioning; 1 unexpected case, 0 skipped. Both video.webm recordings and both test-failed-1.png images uploaded through codex_evidence.py and linked in this thread. Delivery receipt requires an actual chat message ID unavailable in the tool response; do not invent it.

Applied class repair visible -> view, submitted laptop/phone source 2ad415a4397bd744dd535ec3294724a56b295749. Visual inspection of RED revealed a second aspect of the same fallback defect: global .icon_rounded position:absolute; bottom:0; left:0 anchors the fallback over the footer app icon, leaving the details area blank. Added geometry assertions and pdf-view-details selector to reproduce this without changing positioning. These newer checks supersede the initial icon-only green attempts as completion evidence.

Local lint unavailable: worktree lacks eslint/tsc/svelte-check and generated theme CSS. Installed compiler syntax probes passed for the two TS files and Svelte compiled without warnings. These are supplemental, not browser or full lint evidence.

## Cost-control handoff — waiting only, 2026-09-08

Coordinator instructed ending the turn while external CI is the only remaining action. Preserve all jobs; do not cancel or resubmit. Continue with GPT-6 Astra LOW in session 37a6 and agent-37a6.

| Pending request | Source commit | Profile | Purpose |
| --- | --- | --- | --- |
| cb89c6ca506a345b05661bf5210dd5a26eadff10799c228676d741f5e73446e9 | 8919b1800a82834c636f7c9bd64de1904f7db0f2 | web-laptop | Authoritative next RED: icon fixed, inherited absolute-position footer overlap still present; containment assertions added. |
| 8a7eb3b047d95602f20bb6d9635927645dc8a98264e9ee07262148c3f66c137d | 2ad415a4397bd744dd535ec3294724a56b295749 | web-laptop | Earlier icon-only check; superseded for completion by containment check. Preserve and deliver any resulting evidence. |
| 36e5fc090a781ccea6d33a95179cf5566f7e066ccf1d7e986258197d4eca6d94 | 2ad415a4397bd744dd535ec3294724a56b295749 | web-phone | Earlier icon-only check; superseded for completion by containment check. Preserve and deliver any resulting evidence. |

All three were queued at last reconciliation; no run IDs assigned then. Completed first RED is db88daf98b95318d8346456577b31eebabea46214c12a1912fc326bca02c3165, run 34236422711, source efee2eeab4b26d55dc5ff4bfd54f2796ecb45700. Do not repeat it. All four available failure media links were delivered in this thread.

Next command (canonical current control plane, to preserve new evidence tooling):

```bash
python3 /home/superdev/projects/OpenMates/scripts/ci_coordinator.py result cb89c6ca506a345b05661bf5210dd5a26eadff10799c228676d741f5e73446e9
```

If still nonterminal, leave waiting for coordinator wake-up. Once terminal, execute emitted codex_evidence_command, deliver all recordings/images with the exact component URL, and inspect the assertion failure. Expected: icon bounds outside pdf-view-details due to global .icon_rounded position:absolute; bottom:0; left:0. After actual RED, add position:relative to this component's .icon-center .icon_rounded rule (do not change global icon styles), then submit the same focused spec for web-laptop and web-phone. Review frame evidence before scoped product deployment/completion. Browser route: https://app.dev.openmates.org/dev/preview/embeds/pdf/PdfViewEmbedPreview?chrome=0.

Preserve the unapproved Chats specification fingerprint 43daf9ddea432473f4438980cb74934aba51816796e879c89cb1bd3004e4ac01; dollar/image semantic changes remain pending approval. No audio generation. Only deployed change so far is CI classification e82d4816679d3cd8e00e1bcc0d626c8aa6872cf7. One-class icon repair, fixture, test, and selectors remain in this worktree.

Process note: repeated unchanged CI polling/commentary consumed turns without advancing work. Coordinator now supplies explicit ten-minute wake-up monitoring; existing cost-control instruction is sufficient, no new workflow mechanism proposed here.
