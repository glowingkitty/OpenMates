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

## Deployed source; browser dispatcher hold

Scoped deploy succeeded at `623274de5a3c0e68383f84f8a8aafd22a9ea7d15` after three upstream-advance restarts; Specification, lint, translations and SDK boundary gates passed. This is a pushed source commit, not evidence that Vercel is Ready or browser proof passed.

Canonical dispatch command: `python3 scripts/tests.py run --spec components/memory-consent.spec.ts --gate-deploy --expected-commit 623274de5a3c0e68383f84f8a8aafd22a9ea7d15 --session bce4 --proof-video-profile web-laptop`. Result: jobs empty, held spec `components/memory-consent.spec.ts`, exact reason **New spec requires dependency classification before dispatch**. The same classification blocks phone. No browser run/recording/upload/delivery occurred. Component fixture dependencies: static fictional URL props, local UI only; no login, memory mutation, inference, provider egress or backend writes. Coordinator/test-infrastructure owner must classify this spec before dispatch. No bypass attempted.

Process observations: the documented dry-run flag is unsupported by the current dispatcher; basename selection also failed because nested specs require tests-relative paths. Existing dispatcher validation exposed both safely. Deploy automatically reran gates after three concurrent upstream changes. These are workflow issues, not product test failures.

## Classification resolved; durable CI submissions

Coordinator authorized routine dependency classification. Under the exact WRITING lease, `components/memory-consent.spec.ts` was added to the existing `browser_component_contract` group. `partition` accepts it without holds. Metadata-only scoped deploy: `f3171e31e9ab3afb2035104fcef3ae61d0ec80d7`. Phone request `1e173df46f5d60d417ae85a2b726927ae6f98cfd2c81a636de9facc53ea302f6`; laptop request `e593903c770536ee02e41ca1799f648cc14e07a8566fd800ccd12adfb7876e05`. Both are durable accepted queue entries, not completed browser runs.

After the compute-setting interruption, terminal waiters no longer existed; canonical cached status confirmed both jobs remained queued. No resubmission occurred. Prior inference that historical failed-prerequisite metadata blocked admission was incorrect: coordinator code excludes terminal jobs, and four occupied slots explained waiting. The correction was acknowledged in Task activity `054ee4c55f099c3f52171a5d7caf191a218b88a54ca6c1b6ba1d73f615e98010`. No prerequisite change is needed.

## Cost-control handoff — waiting only

Session/worktree: `bce4`, `/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-bce4`. Codex continuations: GPT-6 Astra LOW. Approved fingerprint and one-audio-pilot gate remain unchanged.

Pending tested source commit: `f3171e31e9ab3afb2035104fcef3ae61d0ec80d7` (fix commit `623274de5a3c0e68383f84f8a8aafd22a9ea7d15`).
- Phone request: `1e173df46f5d60d417ae85a2b726927ae6f98cfd2c81a636de9facc53ea302f6`, last observed queued, no GitHub run ID yet.
- Laptop request: `e593903c770536ee02e41ca1799f648cc14e07a8566fd800ccd12adfb7876e05`, last observed queued, no GitHub run ID yet.

Next commands from this worktree (do not resubmit):
```bash
python3 scripts/ci_coordinator.py status 1e173df46f5d60d417ae85a2b726927ae6f98cfd2c81a636de9facc53ea302f6
python3 scripts/ci_coordinator.py status e593903c770536ee02e41ca1799f648cc14e07a8566fd800ccd12adfb7876e05
# Once terminal, retrieve each receipt and run its codex_evidence_command:
python3 scripts/ci_coordinator.py result 1e173df46f5d60d417ae85a2b726927ae6f98cfd2c81a636de9facc53ea302f6
python3 scripts/ci_coordinator.py result e593903c770536ee02e41ca1799f648cc14e07a8566fd800ccd12adfb7876e05
```

Then inspect failures or review successful phone/laptop proof using the canonical proof workflow. Deliver all available run media, including failed attempts. Only after consent web verification succeeds, resume existing real candidate `b63368d9-8ca5-4674-95bb-aab7ebcd3e69` naturally with explicit writing-memory approval; inspect the actual reply, email protection/restoration and follow-ups, then scaffold owned candidate data/translations and coordinate catalog registration. No travel-memory mutations or audio. No jobs cancelled. This handoff is local pending evidence, intentionally not a new deploy while waiting.

## Successful CI assertions; failed visual admission

Fetched original phone run `34239278192` and laptop run `34239936379`, source `f3171e31e9ab3afb2035104fcef3ae61d0ec80d7`. Both report one expected test, zero skipped/unexpected/flaky. Recordings plus captured images were uploaded through codex_evidence and all four links delivered in visible commentary, then acknowledged. No test was rerun.

Canonical proof import with `--run-id 34239278192` fails: `CI proof receipt rejected: Timeline checkpoint lacks its exact attached frame`. The shared video-proof runtime emits timestamp-only checkpoints when captureFrame is absent; CI proof importer requires an attached frame for every checkpoint. Original timelines and videos remain immutable. This is a proof-tooling mismatch, not a failed product assertion.

Bounded frame scan (frames extracted from original recordings in `/tmp/bce4-memory-review`, not new browser screenshots): phone 2s shows the complete permission card, aligned controls and count1; 4.5s shows the complete card with unknown count omitted; 6.5/7.5s show collapsed history/gradient strip; 8s shows writing-style row clipped to a narrow strip. Laptop 2s shows complete known-count card (mail icon absent at that instant); 4.5s shows unknown-count card during transition; 7.5s shows blank history region; 9.5s shows buttons clipped into a narrow strip. Scanned layout/readability/geometry/controls/assets/state/consistency/proof alignment: standalone card supports known/unknown claims; history frames fail geometry and proof alignment despite passing DOM assertions. Selection cannot be visually admitted. No claim of completed proof. Representative phone8s frame uploaded and visibly delivered.

Root cause: generic content-sized component mount does not supply ChatHistory its flex layout height. Added an isolated sized MemoryConsentHistoryPreview host, preserving real ChatHistory and the existing fictional records; no production CSS changed. Updated spec to use host and assert complete viewport intersection and non-collapsed bounds. Fixture repair lint pending. Existing runs preserved; user requested no rerun. Natural candidate remains held because visual review found this objective defect. Tasks read failed HTTP502 on resume; this milestone stays local pending acknowledged posting.
