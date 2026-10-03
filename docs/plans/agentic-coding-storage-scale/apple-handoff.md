# Apple storage compatibility handoff

The user assigned Apple implementation and verification to the existing Mac chat on 2026-10-03. That chat owns Apple changes. The backend chat keeps session `2f80` and the backend/web/CLI storage work. No product Apple file has been changed by the backend chat. An interrupted, uncompiled proposal remains in ignored scratch and is excluded from its candidate.

## Start on the Mac

Reuse the Mac chat's current Task and workspace. Inspect the canonical checkout before updating it:

```sh
git status --short
git branch --show-current
```

When the canonical checkout is clean and on `dev`:

```sh
git pull --ff-only origin dev
```

Preserve the Mac chat's existing changes and follow its session integration workflow for a dirty or detached task worktree. Read this handoff, the storage Plan, and `specifications/architecture/storage-lifecycle/specification.yml` when the backend changes reach dev. This handoff is published before the storage backend: its candidate `56bac1387c2c99309235033d70f3de53ddb31580` is under CI, not a published branch. Pull again after the backend chat announces its development commit.

## 1. Repair the live AI embed writer first

Production code: `apple/OpenMates/Sources/Core/Networking/WebSocketManager.swift`, `ChatEmbedStreamCoordinator.encryptAndPersist`. Focused tests: `apple/OpenMatesTests/StreamingClientFanoutTests.swift`.

The existing sequence sends `store_embed_keys`, accepts its request ID alone, then sends `store_embed`. The new database parent guard rejects wrappers when their canonical embed head does not exist. A confirmed event with `failed_count > 0` is a failed save, so the current native sequence can incorrectly mark an embed persisted without durable wrappers.

Implement this sequence:

1. Preserve local client encryption, wrapped master/chat keys, generation/scope/deletion checks, owner PII separation, and offline/retry state.
2. Register the matching receipt waiter before sending `store_embed`.
3. Await `store_embed_confirmed` for the exact `request_id` and `embed_id`. The new backend adds `canonical_digest`: lowercase SHA-256 of the UTF-8 **encrypted_content string**, not decoded ciphertext or plaintext. Require the matching digest for the new storage path. Current dev receipts lack that field: choose an explicit staged compatibility policy so a missing legacy digest cannot become evidence of new-path durability.
4. Only after that head receipt, send `store_embed_keys` and await its matching receipt. Require `failed_count == 0` and `created_count == sent keys.count` (normally two wrappers). Reject absent, malformed or partial counts.
5. Mark the finalized payload processed only after both saves succeed. Preserve retry on timeout, disconnect, head failure, digest mismatch, or wrapper failure. Retries must preserve the original encrypted identity and must not let an older payload overwrite a newer one.

Use the web sender in `frontend/packages/ui/src/services/embedSenders.ts` and its receipt tests as the reference once pulled. The backend receipt contracts are in `store_embed_handler.py` and `store_embed_keys_handler.py`.

Update the existing native ordering and deduplication assertions rather than weakening them. Add focused cases for head timeout/failure (no wrappers sent), digest mismatch, failed/partial wrapper counts, disconnect/retry, and duplicate finalized delivery. Update `ChatEmbedRecordingTransport` to emit realistic digest/count receipts.

Composer, background, and Watch attachments use bundled `chat_message_added.encrypted_embeds`; their server path writes the head before wrappers. Preserve those clients while checking their failure/acknowledgement behavior. The backend chat owns any server-side bundled persistence repair. Main-app `ChatViewModel` currently skips a persistable embed with missing content; fail the send instead of silently omitting a required attachment. Background and Watch builders already throw on missing required encryption inputs. Preserve the original encrypted bundle for retries of the same message identity so rebuilding encryption with a fresh nonce cannot mutate a partially persisted attempt. Verify that already stored references and actual artifact edits retain their intended behavior.

## 2. Complete native readers and unattended recovery compatibility

The writer fix alone is not an Apple storage compatibility receipt. Audit and implement the following against the actual pulled backend contracts:

- Paginated message and wrapper windows, compression checkpoint metadata, exact oversized-message fetches, and hot/S3 history boundaries. Use `/v1/chats/{chat_id}/messages/window` and the exact-message endpoint; preserve cursors, deduplication, full ciphertext and visible retry. A normal scroll must not fetch an entire transcript.
- Typed sealed recovery for original child prompts, transcript messages, summaries, compression checkpoints, embeds and diffs. The existing final-text-only recovery path is insufficient. Follow `frontend/packages/openmates-cli/src/client.ts`, `ws.ts`, `crypto.ts`, and `frontend/packages/ui/src/services/chatSyncServiceHandlersRecovery.ts`. Use the shared fixture `backend/tests/fixtures/chat_recovery_output_v2.json` for cross-client cryptographic compatibility.
- Bound recovery discovery to its pages and wait for `recovery_outputs_discovery_complete` before replaying dependent work. Persist each canonical client-encrypted output before its typed acknowledgement. Preserve pending outputs on partial failures, account changes, revoked Team membership, stale identity, or decryption failure. Client-only recovery ciphertext must not be treated as server-readable inference context.
- Paginated embed version metadata, on-demand old ciphertext, periodic client snapshots, and a bounded patch chain. Verify version 101+ and historical selection without downloading every payload.

The three recent main chats and active-child budgets apply to the **server Redis working set**. They do not instruct the native client to discard local chat history or pending writes. PostgreSQL retains all-chat encrypted metadata; cold transcript pages contain about 20 messages/256 KiB initially, with large bodies fetched separately.

## 3. Verification and return handoff

Keep existing Specification/test metadata; add the storage assertion IDs actually proved. Relevant assertions include `storage.background.complete-sealed-recovery`, `storage.background.saved-output-retention`, `storage.cold.independent-message-pages`, `storage.versions.bounded-reconstruction`, `storage.privacy.ciphertext-boundary`, and `storage.surface.semantic-parity`. Preserve the existing `chats.persistence.client-encrypted` metadata for the live writer tests. Regenerate Specification artifacts through the repository workflow.

Run `StreamingClientFanoutTests` with the installed Xcode on the Mac, then focused recovery, history-window, and version tests for changed behavior. Verify iOS and macOS compile; check Watch when shared inputs affect it. Use repository-local build artifacts and the Mac chat's coordinated native workflow. No real inference requests: use synthetic encrypted fixtures and the real isolated API/storage paths for integration evidence. Do not access/delete real account data for tests.

Return: Task/workspace, deployed dev commit, owned paths, platform/build/test results, exercised receipt and recovery scenarios, and unresolved compatibility/release blockers. Publish using the Mac chat's existing session rules. A TestFlight release follows that chat's existing authorization; code publication alone does not prove installed clients are upgraded.

## Activation dependency

Keep the backend's strict parent/key writer enforcement and archive rollout inactive on shared services until the supported native sender is verified and the release/compatibility policy is settled. All archive worker switches default off; real pruning additionally requires supported-reader receipts, the 24-hour source buffer, full zero-inference capacity/lifecycle tests, and per-unit safety fences. The current small CI runner cannot prove 500 simultaneous executions. No Apple receipt or full-scale capacity result has been claimed.
