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
