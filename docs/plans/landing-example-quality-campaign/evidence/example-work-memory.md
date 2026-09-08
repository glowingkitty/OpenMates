# TASK-6 / TASK-8774 — writing-memory candidate evidence

- Session: `bce4`; distinct worktree: `.openmates-agent-worktrees/agent-bce4`.
- Actual Codex thread: `01a080f6-97c8-7df2-bead-3423cb53299b`.
- Assigned task UUID: `19654fc1-27ab-4d4e-a6c9-21a4d9100817`.
- Activation authorizes mail writing preferences only; travel preferences belong to another worker.
- Supplied coordinator Plan and handoff establish assignment. No prior candidate supplied; source_chat is null.
- Tasks history and connection initially failed with HTTP 429. A previously running history request later reported ambiguous short ID. No connection acknowledged. Coordinator has requested no Tasks API calls for at least ten minutes and will serialize recovery; milestones remain here until then.
- Real dev CLI scoped memory read returned an empty list for `mail.writing_styles`.
- Prepared fictional style: warm/professional/concise, plain English, short paragraphs, no exclamation marks, Hello greeting, Best wishes closing, practical questions as bullets, no sales language; used for event-photography client replies; fictional Lena Hoffmann signature.
- Memory creation acknowledged by real dev API: `2ed28612-907e-4f26-ade0-1000a75834c1`.
- Approved opening launched through supplied source CLI with slug `example-work-memory-bce4`, PII detection enabled. Startup reported settings API rate limiting with a built-in 61-second retry; no separate retry launched.
- No mailbox access is needed or authorized. No account-wide memory clearing or travel mutation.
- Speech held pending user-confirmed pilot. Candidate content, deployed phone/laptop browser inspection and proof remain pending.

## Opening (approved, verbatim)

Help me draft a reply to a customer asking whether I can photograph their event next Friday. I’m available, but I need the location, timings and approximate guest count before I can quote. Use my saved writing preferences and include lena.hoffmann@example.com as my contact email.

## Privacy verification scope

The source CLI defaults to PII detection before send (`cli.ts`, `redactWithMappings`). Real candidate evidence must confirm an email placeholder reaches the conversation and the private mapping restores the fictional email appropriately. Static source inspection alone does not certify this. Do not claim name or address protection, and do not hand-edit the source transcript.

## Live source outcome — hold for shared consent-history defect

- Source chat: `b63368d9-8ca5-4674-95bb-aab7ebcd3e69`.
- Opening user message: `b25a7a61-f213-40eb-9b86-59d4bdbe71a5`.
- Live CLI read: `chats show example-work-memory-bce4 --all --json --api-url https://api.dev.openmates.org`, exit 0.
- The stored opening contains `[EMAIL_1_com]` in place of the fictional contact email. This verifies actual replacement; browser restoration and inference-boundary inspection remain unverified.
- The assistant requested only `mail-writing_styles`. Without `--auto-approve-memories`, the CLI stopped with its explicit consent-required error. No memory approval was sent and no assistant draft was generated.
- The same consent request `4c3615d7-272d-4984-bbda-97cbe5e80c71` appears twice in live history: message ID equal to the request ID with entryCount 0, and `b7ebcd3e69-2292d567-53d6-4330-957c-3b2b82dc5ec0` with entryCount 1. Both target the same user message and were created at 1788870532.
- Expected: one coherent consent request per request ID. Actual: duplicate request records with conflicting category counts before approval.
- Likely cause from source inspection: CLI `buildAppSettingsMemoryRequestSystemMessage` uses `requestId` as message ID and entryCount 0; web `saveAppSettingsMemoriesRequestMessage` uses chat suffix plus random UUID and actual category counts. Both clients can receive the request broadcast. Cross-client origin remains an inference; the duplicate records are directly observed.
- Shared fix handoff: coordinator must assign memory consent-history/idempotency ownership. This candidate worker has made no CLI, renderer or backend changes. Do not clean up the transcript or conceal the duplicate during conversion.
- Candidate is held under the explicit worker rule to stop on clear defects. No further paid generation, share/publication, translation, browser pass or speech claim.
- Coordinator Plan now acknowledges this actual visible thread as running; Tasks connection/activity writes still await coordinator recovery.

## Recovery steps

1. Shared fix owner resolves duplicate consent persistence and verifies cross-client identity/count behavior.
2. Resume this same source chat with explicit approval of the writing style through the supported CLI flow, or create a replacement only if the repaired history cannot remain a natural example. Do not rewrite the transcript.
3. Inspect the complete draft, memory use, email restoration, realistic follow-up and source suggestions before conversion.
4. Publish candidate data/translations through catalog-owner integration; verify full deployed phone/laptop conversation and required proof. Audio waits for pilot approval.

## Shared fix ownership and confirmed persistence

The coordinator assigned this worker the duplicate-consent investigation and fix. No further generation or travel-memory mutation has occurred.

The real CLI `chats show b63368d9-8ca5-4674-95bb-aab7ebcd3e69 --json --api-url https://api.dev.openmates.org` (without `--all`) reads the direct authenticated `/v1/chats/{id}/messages/window` endpoint through `getChatMessagesWindow`. It returned two separate server row IDs: `1fbb379e-87bf-593a-90e5-c9b7b3deacda` and `a67c4bf5-606f-512b-a14b-ad98ed02d2b8`, matching the two client message IDs already recorded above. Both encrypted rows locally decrypt to the same request identity with counts 0 and 1. This confirms actual server persistence rather than CLI-only display duplication.

`ChatHistory.svelte` builds its request map by `user_message_id` with unconditional `map.set`, retaining the last row. Source inspection therefore identifies order-dependent count selection rather than two separately rendered request cards. No browser verification claim is made.

Access boundary: the existing chat window is an authenticated first-party encrypted-chat surface; ciphertext is decrypted locally by the owner CLI. No new endpoint, auth scope, rate-limit or credit change is proposed. Memory use still requires explicit per-conversation approval.

Specification search found `feature.app-memories@1` in draft status. `specifications.py check-approval specifications/features/app-memories --session bce4` reports missing approval (despite exit code 0). The chat assertion `chats.message.identity-idempotent` expressly addresses duplicate terminal messages and does not define count semantics or consent convergence. The drafted `app-memories.conversation.request-convergence` addition requires one stable persisted request identity across clients, accurate known counts/explicit unknown counts, and a single logical presentation of legacy duplicates without changing approval. No authoritative new test or product fix will be written before exact-artifact approval. Existing CLI memory-request and web app-settings handler tests are the intended regression extension points.

Specification validation passed for fingerprint `278c09756fdcbea75f367a73951e2a08f60cb76f64507d27f9459e30a33a959f`; generated registry/index/coverage refreshed. Canonical approval PDF publication succeeded. Review artifact: `/tmp/opencode/specification-approvals/feature.app-memories-278c09756fdcbea7.approval.json`. Its eligibility flag is true and highlight policy is changed-text-only inline green additions, red deletions, neutral unchanged text. Approval remains pending; no receipt has been recorded.

## Process retrospective

Task reads/connect repeatedly encountered HTTP 429 before the coordinator established the shared cooldown; full-ID use also resolves through the task list, so it did not avoid the same endpoint. Quickstart already prescribes bounded task history, and current coordinator serialization addresses this incident. Follow that existing coordination rather than adding a competing worker retry mechanism. CLI memory consent help should have been consulted before launch to select explicit approval for this authorized fixture; existing help already covers it, so no new instruction is needed.

## Approved implementation and live verification

Exact Specification approval was recorded with the unchanged 278c09756fdcbea75f367a73951e2a08f60cb76f64507d27f9459e30a33a959f fingerprint. Shared CLI/web request identity, known-or-unknown category counts and local legacy history convergence are implemented. Six focused CLI regressions pass after the expected red count failures; the web persistence regression passes. Full Vitest has seven unrelated failures (890 passed of 897); no unrelated fixes attempted. Scoped session lint passed.

Real dev WebSocket concurrency plus retry persisted one encrypted request in fictional verification chat `b1be223e-3365-4347-8ad2-36473ed2e3b2`, request `a889c2b7-2de4-4cbb-bfe1-741fd5ca99d9`, count 1, no automatic approval or inference. CLI history now projects legacy duplicates as one request with known count 1.

SDK auth investigation: the generic `sdk_cli_parity_live_smoke.py` CLI creation command requests full access, so it was not used. Existing `OpenMatesClient.createApiKey` supports `fullAccess:false`, `scopes:{chat:["chat:read_existing"]}`, and short expiry. The bounded runner `/tmp/bce4-memory-sdk-preflight.mjs` followed the established create / approve exact matching device / verify / revoke lifecycle using supported client methods. No secret files were inspected or credentials printed. Both public npm and pip SDKs read the real encrypted SDK message window and locally decrypted one request with count 1 and no action. Temporary key `89ed65fb-d25b-4c20-b9ad-d6043277b5f0` was revoked successfully. No access surfaces expanded.

Component preview fixtures and phone/laptop proof spec are prepared but deployed browser verification remains pending. No runtime lifecycle mutation, travel mutation, audio generation, or further candidate inference occurred.
