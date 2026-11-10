# Wire contract: an image change is a new version of the same embed

Lane A (backend) of `plan.yml`. Specification: `specifications/features/app-skills/images-generate/specification.yml`
(`images-generate.revision.same-embed-new-version`, `.message-shows-its-version`, `.each-version-billed-once`).
Line numbers refer to the Lane A working tree.

## Feature switch

- `IMAGE_EDIT_AS_EMBED_VERSION` is an env var on the app-images worker (`backend/apps/images/tasks/image_revision.py:32`, read at `:84`).
  If it is unset or not `1/true/yes/on`, the behaviour is unchanged: every call creates a new image embed.
- **Keep it off in every environment until the client lanes (web and Apple, via the Rust core) persist and read child versions** (see "Client blockers").
  With the switch on and today's clients, a change's version is sealed and charged, but no client stores it.

## When a call is a revision

Logic: `find_revision_target`, `image_revision.py:193-245`. A call is a revision only when all of these hold:

1. The switch is on, the request is not external (REST/developer API), and the chat id is known.
2. The active producer is `registered_ai` and its `target_chat_id` is this chat.
3. Exactly one `reference_images` id is a revisable image:
   - its canonical `embeds` row is unique for the owner hash;
   - that row has `hashed_chat_id == sha256(chat_id)` and a non-empty `parent_embed_id`;
   - its `upload_files` row has `ai_detection.source == "openmates_image_generate"`.
4. No other request of the same call claimed that image already (`run_with_batch_claims`, `image_revision.py:457`).

Anything else creates a new image embed, as today: uploads, images of other chats, a combination of two images, a second change of the same image in one call, legacy or volatile producers, and REST.

### Stored marker; a head without it fails closed before the charge

The Directus extension admits a revision only for a head with all of:
- a UUIDv5 id and a parent;
- `embeds.app_id == "images"` and `embeds.skill_id == "generated_image"` (`isGeneratedImageChild`, `operations.js:237-241`).

Those two columns are the server-derived catalog projection that `store_embed_handler.py:329-330` writes. They stay **null** when the chat had not synced when version 1 was stored (`store_embed_handler.py:308-311`).

For such an image, `assert_current_version` (`image_revision.py:248-260`) raises `RevisionNotSupported` **before the charge**. Nothing is charged and nothing is uploaded or published.
- The user sees: "This image cannot get a new version yet. Nothing was charged; please try again shortly." (`generate_task.py:1683`).
- A later store of the head that runs while the chat exists adds the marker; after that the image can be revised.

## Order of effects in the task (`generate_task.py`)

| Step | Where | Fails how |
|---|---|---|
| Generation, processing, vault wrap, encryption, S3 upload | before the charge (`:1287-1430`) | no charge; uploaded objects of a revision are unreferenced (gap below) |
| v1 only: `upload_files` create | `:1440-1470` | no charge; objects deleted |
| Revision: Redis sidecar `embed:{id}:s3_file_keys` = union of all versions' keys | `:1518`, `image_revision.py:277-288` | raises before the charge |
| Precondition: canonical version, parent, chat, creating-message hash, marker | `:1532`, `image_revision.py:248-260` | `RevisionPreconditionFailed` / `RevisionNotSupported`, no charge |
| **Charge** | `:1535-1543` | revision: a failed Personal or Team charge raises (`strict`); nothing is published |
| Publish and seal N+1 | `:1570-1583` | `RevisionRefused` (raised before anything is sealed): Personal charge refunded (below) |
| Revision: repoint `upload_files` row, then drop `embed:{id}` | `:1584`, `image_revision.py:444-454` | delivered and charged; failure is logged as an error, not raised |

## Billing

- **Deduplication.** The ledger deduplicates on the idempotency key alone: one settlement per `charge_id`.
  Reusing a key with a different payload hash is a 409 `settlement_identity_mismatch` (`sub-chat-orchestration-transaction/src/operations.js:1394-1400`).
  So the key must identify the change.
- **v1** keeps `event_id = embed_id`, so its key is `app-skill:{embed_id}` (unchanged).
- **vN, N ≥ 2:** `event_id = "{embed_id}:v{N}:{change_id}"` (`image_revision.py:88-105`).
  - `change_id = sha256("{message_id}:{producer_intent_id}")[:32]` (`:108-112`), taken from the producer of the changing message.
  - A retried task has the same message and intent, so it gets the same key and is charged once.
  - Two changes that both saw version N (the head did not advance because no client persisted the first) get different keys, so they are two charges.
- **Refused after the charge.** `verify_producer_revision` raises `RevisionRefused` before any output is sealed (`embed_revision_authority.py:32-84`, called at `embed_service.py:6806`).
  - Personal: refunded through `/internal/billing/refund` with key `app-skill:{event_id}:refund`, which is idempotent per change (`image_revision.py:408-441`).
  - Team: **there is no Team refund route.** The charge stays and is logged as an error (gap).

## File keys and storage

- **S3 object keys** are `{user_id}/{YYYYMMDD_HHMMSS}_{uuid8}_{format}.{ext}` in bucket `chatfiles` (`generate_task.py:1381`). Formats are `original` and `full_webp`/`preview_webp`, or `preview_webp` for SVG.
  Old versions' objects are never deleted by a revision. Only the display `filename` uses the embed id.
- **`embeds.s3_file_keys`** only grows for an image child: every write unions the stored and incoming lists, including same-version replays with a stale subset (`operations.js:1035-1039`).
  Malformed stored keys fail with 400 `invalid_s3_file_keys`.
- **Sealed recovery copy.** The `(embed, N+1)` output carries the union as `s3_file_keys` (`embed_service.py:7162`, `:6850`). The keys it carries:
  - must include every key the head already has (`embed_revision_authority.py:84`);
  - stay a storage reference until the output's assets are released on message, chat or account deletion (`chat-recovery-transaction/src/operations.js:4761`; read by `storage_reference_service.py:29`);
  - so the 1 h Redis sidecar is no longer the only durable copy.
- **`upload_files`** (`embed_id` is unique).
  - The one row is repointed at the newest version only after sealing.
  - Its `file_size_bytes` is the sum of all versions: the retained bytes plus the new ones (`generated_assets/service.py:165-191`).
  - The storage counter adds only the new bytes.
  - Deleting the embed frees `file_size_bytes` (`embed_methods.py:1404-1419`) and tombstones the objects found in `embeds.s3_file_keys` (`embed_methods.py:1481`) and `upload_files.files_metadata` (`storage_reference_service.py:251-305`). Earlier versions are found through the head union and the sealed output.

## Changed and new wire fields

### 1. `send_embed_data` for the revised image (new event shape; same event name)

Sent by `publish_revision` (`image_revision.py:355-405`) through `send_embed_data_to_client` (`embed_service.py:7127-7166`).

```text
payload.embed_id             = existing image id (UUIDv5 child of message 1's parent)
payload.type                 = "generated_image"
payload.status               = "finished"
payload.parent_embed_id      = ORIGINAL parent (message 1's app_skill_use)
payload.chat_id              = chat
payload.message_id           = the CHANGING message (message 2)  -- the head keeps message 1's hash, see persist step 2
payload.version_number       = N+1
payload.app_id / skill_id    = "images" / "generated_image"
payload.encryption_mode      = "client"
payload.content              = TOON of the full N+1 content (files, aes_key, s3_base_url, embed_ref = v1's ref)
                               + revised_from: {embed_id, version: N}
payload.version_history_rows = [{embed_id, version_number: N+1, snapshot: <same TOON>, created_at}]  -- snapshot-only
payload.revision             = {base_version: N, base_snapshot_required: bool}
```

`base_snapshot_required` is true when no `embed_diffs` row exists for version N. For N = 1 it is always true.

The same event arrives through recovery. The sealed `(embed, N+1)` output has `hashed_message_id` = the **head's** hash (message 1), not message 2's (`embed_service.py:6836-6856`). Recovery ACK compares that value to the head (`chat-recovery-transaction/src/operations.js:5062`, `:5388-5389`), so a client that keeps the stored hash passes both the ACK and `requireChildRevisionHead`.

### 2. Draft events during drawing (vector path)

`_VectorDraftPublisher` streams drafts on the new message's own placeholder child, never on the revised image. The draft content carries `revised_from`.
The placeholder is not listed in the final parent's `embed_ids`, so a client should treat it as temporary.

### 3. Final parent (`app_skill_use` of the changing message)

`finalize_generated_media_parent` (`generated_media_graph.py:570-620`):

```text
content.embed_ids     = owned new children only (a revision is NOT listed)
content.pinned_embeds = [{embed_id, version: N+1, embed_ref, previous_version: N}]
content.status        = "finished" when there are owned children or pins
content.result_count  = owned + pinned
```

### 4. Skill result for the chat model (continuation)

- `completed_results[i]` has `child_embed_id` = the revised image and `revision: true`. The revised image is excluded from `child_embed_ids` (`generated_media_graph.py:416-423`, `:497`).
- The model-visible result fields add `version`, `previous_version` and `revision_note` (`generated_media_graph.py:51-59`; note text from `image_revision.py:334-340`).

## How a client persists version N+1

Use the parent's embed key for every ciphertext; children inherit it (`embed_write_session.rs:181-185`).

1. **Base snapshot (only when `revision.base_snapshot_required`).** Send `store_embed_diff` with `{version_number: N, encrypted_snapshot: <the client's head at N>, encrypted_patch: null}`.
   The extension accepts history for an image child only (`operations.js:436-442`).
2. **Head at N+1.** Send `store_embed` with:
   - `version_number: N+1`, the original `parent_embed_id`, and `root_embed_id` null or the parent;
   - **the stored head's `hashed_message_id` and `hashed_chat_id`** (not `sha256(payload.message_id)`);
   - `app_id: "images"`, `skill_id: "generated_image"`, the same `encrypted_type`, and the new `encrypted_content`.

   The extension admits it under `requireChildRevisionHead` (`operations.js:276-289`). On an acknowledged head it uses the image-child advance (`operations.js:917-990`), which needs:
   - the version-N full-snapshot history row from step 1;
   - the parent's master and chat wrappers;
   - exactly one PENDING `(embed, N+1)` output.

   `s3_file_keys` is merged from Redis by the API within 1 h. After that it is absent from the payload and the stored union stays; the new keys remain referenced by the sealed output.
3. **History row N+1.** Send `store_embed_diff {version_number: N+1, encrypted_snapshot, encrypted_patch: null}`. Rows are refused more than one version ahead of the head (`operations.js:442`).
4. ACK `(embed, N+1)` and `(diff, N+1)`.
5. Do not add the image to the new message's `embed_ids` and do not re-parent it.

## How a client reads version K of an image

1. Version for message m = the `version` of the latest `pinned_embeds` entry for that `embed_id` in any message ≤ m, else **1**.
2. If K equals the head's `version_number` (missing means 1), use the head content.
3. Otherwise decrypt the `embed_diffs` row K's `encrypted_snapshot` with the parent's key (`sdk_embeds.rs:443-505`).
4. Version K's files come from that version's own content (`files`, `aes_key`, `s3_base_url`). `upload_files` names only the newest version.

## Client code that blocks child versions today (Lanes B and C)

1. `frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts:5071-5078` and `frontend/packages/ui/src/services/rustCore/embeds/rustStreamedEmbedWrite.ts:165`: sealed history handling is off for children (`!isChild && version > 1`).
2. `packages/openmates-rust/src/client/embed_write_payload.rs:92-96`: `sealed_history()` requires no parent. There is no base-snapshot step driven by `payload.revision.base_snapshot_required`.
3. `packages/openmates-rust/src/client/embed_write_history.rs:93` and `:122`: they assume patch rows for v>1.
4. `chatSyncServiceHandlersAI.ts:4592` hashes `payload.message_id`. A revision, live or replayed from recovery, must keep the stored head's hash, or it gets 403 `project_context_required`.
5. `chatSyncServiceHandlersAI.ts:4004-4026` always adopts the newest head. Message-scoped rendering must follow the read rule above.
6. No client reads `pinned_embeds`.

## Directus extension change (explicit exception)

All changes are in `backend/core/directus/extensions/embed-version-transaction/src/operations.js`. Every relaxed branch requires `isGeneratedImageChild` (`:237-241`); every other child and every root keeps the old 403/409.

- **Registered child write.** A revision output (producer primary ≠ the child's parent) needs `requireChildRevisionHead` (`:276-289`): image child, same owner, parent, chat hash and creating-message hash, the same `app_id`/`skill_id` if sent, root null or the parent, and head version N or N+1.
- **Acknowledged advance** of an image child (`:917-990`): wrappers checked on the parent; version-N history must be a full snapshot; parent and message unchanged.
- **`s3_file_keys` union** on every image-child write (`:1035-1039`; parser at `:243-270`).
- **`writeLegacyEmbedDiff`** (`:436-442`): UUIDv5 history and snapshot-only rows for v>1 only for image children; version ≤ head + 1.

Tests: `test/operations.test.js` (`childRevisionFixture`, 7 tests). The extension's two test files pass, 99/99.

## Known limits

- **Team charge on refusal.** A refused revision stays charged to the Team because no Team refund route exists. It is logged as an error.
- **Other failures after the charge.** If publication fails after the charge for any reason other than `RevisionRefused`, the charge stays. Examples: the project-item check, pinning the working context, an error while saving a sealed output, Redis publish. Part of the output may already be sealed, so a refund could make the change free.
- **Unreferenced objects.** S3 objects of a revision that stops before sealing are not referenced by any row: not by `upload_files` (not yet repointed) and not by any sealed output. The Redis sidecar names them for 1 h. They are not counted in the storage counter, but they are never deleted (storage leak).
- **Index repoint after sealing.** If the repoint fails after sealing, it is logged as an error. The next change then reads the previous version's pixels from `upload_files`.
- **Two changes in one message.** Two calls that change the same image within one message before any client persists both seal an `(embed, N+1)` output. The canonical head can take only one of them: the acknowledged advance needs exactly one PENDING output, so the second fails with 409. Both are charged under different change ids.
- **Base snapshot.** It comes from the client, because the server cannot read the client-encrypted v1 content.

## Core API for shells

Lane B (Rust core). Logic: `packages/openmates-rust/src/client/embed_child_revision.rs` (persist) and
`embed_pinned_version.rs` (read), on `EmbedWriteSession`. Web glue: `BrowserEmbedWriter` methods and free functions in
`packages/openmates-browser-bindings/src/browser_embed_revision.rs`. Errors reject with a stable code string.
Tests: `embed_child_revision_tests.rs` with the fixture `tests/crypto_fixtures/image_revision_wire.json`.

### Durability markers (local only, never sent)

- `embed_diffs` row: `server_confirmed: true` once the server stored that exact row. It is omitted when false, so
  other rows keep their shape.
- `embeds` head: `revision_pending_version: N+1` while the N+1 head is stored locally but its `store_embed` is not
  confirmed. Synced and confirmed heads have no such field.
- The existing sealed-history path persists no marker. It uses the in-memory `durableHead` send result and the
  bounded-v1 canonical read, which do not survive a crash, so revisions carry these markers instead.

### Persisting version N+1 (resumable)

`BrowserEmbedWriter.prepare_child_revision(payload_json, stored_head_json?, existing_rows_json) -> Promise<string>`
- `payload_json`: the `send_embed_data` payload with `revision` (plus `team_id`; `local_only` must be false).
- `stored_head_json`: the child's local `embeds` row (`embed_id`, `parent_embed_id`, `hashed_chat_id`,
  `hashed_message_id`, `encrypted_type`, `encrypted_content`, `encrypted_text_preview?`, `version_number`,
  `revision_pending_version?`), or `undefined` when there is none.
- `existing_rows_json`: the child's local `embed_diffs` rows, as stored:
  `[{id, embed_id, version_number, encrypted_snapshot?, encrypted_patch?, created_at, server_confirmed?}]`.
- The same call serves the first run and every replay (crash, reload, recovery delivery). It returns only the
  writes the server has not confirmed, in contract order.
- Resolves to `PreparedEmbedWrite` JSON (`sealed_history: true`, `server_keys` absent) plus:

```text
child_revision = {
  base_version: N, version_number: N+1,
  steps: [                     // only the missing ones; run strictly in order, stop at the first failure
    {op: "store_embed_diff", role: "base_snapshot", local_row, server_payload, confirmed_row},  // if base_snapshot_required
    {op: "store_embed", store_payload, confirmed_entry},
    {op: "store_embed_diff", role: "history", local_row, server_payload, confirmed_row}
  ]
}
```
- For each step:
  1. store the local value (`local_row`, or the top-level `local_entry` for `store_embed`, which carries
     `revision_pending_version`);
  2. send the payload;
  3. when the send succeeded, store `confirmed_row` / `confirmed_entry`.
- Then ACK the sealed outputs as usual. Do not call `prepare_stream_completion` or `reconcile_sealed_history` for this
  event.
- Resume rules:
  - head at N: fresh plan; a confirmed base row is skipped;
  - head at N+1 with the event's content:
    - the head step is included only while `revision_pending_version` is set; it resends the stored ciphertext byte
      for byte;
    - the base row comes from the local row stored before the head;
    - the history row is skipped once it is confirmed.
- The core already applies persist rules 2 and 5:
  - the head's `hashed_message_id`, `hashed_chat_id` and `encrypted_type` are the stored head's;
  - `parent_embed_id` stays the original parent;
  - content is encrypted with the parent's key, and nothing is re-keyed.
- The base snapshot reuses the stored head's `encrypted_content` ciphertext. `writeLegacyEmbedDiff` treats
  `encrypted_snapshot` as an opaque bounded string (at most 4 MiB, `boundedString`) with no format check. Head and
  history ciphertext are the same `base64(IV||ciphertext||tag)` of `encrypt_text` with no AAD, so the same bytes open
  as a v1 snapshot.
- Refusals:
  - `embed_revision_head_required`: the ordinary path got a revision;
  - `embed_revision_head_missing`;
  - `embed_revision_base_mismatch`: the head is at another version, at N+1 with other content, or at N with its own
    revision still pending;
  - `embed_revision_base_unavailable`: the head is at N+1 but the required base row is not stored locally;
  - `embed_revision_already_applied`: the head and every required row are confirmed. Nothing to write; just ACK;
  - `embed_revision_head_mismatch`: another parent, chat or type, or a missing message hash or ciphertext;
  - `embed_parent_key_pending`: retry after the parent key loads;
  - `conflict`: a local row at that version holds other plaintext or is not snapshot-only, or a different key is
    cached for the child;
  - `protocol`: a malformed `revision`, marker or history rows.

`BrowserEmbedWriter.adopt_child_revision_row(local_row_json, page_json) -> string`
- Call it when a step's `store_embed_diff` fails with `embed_diff_conflict` or `immutable_version_mismatch`, meaning
  another tab or device stored that row first.
- `page_json` is the bounded-v1 page `GET /v1/embeds/{id}/versions/{v}` (`{embed_id, version_number, rows}`).
- Returns the canonical `EncryptedDiffRow` JSON to store locally, with `server_confirmed: true`. It is adopted only
  when it opens to the same plaintext as `local_row`; otherwise the call rejects with `embed_revision_row_diverged`.

### Reading the version a message shows

`embed_versions_by_message(messages_json, embed_id) -> string` (free function)
- `messages_json`: `[{message_id, parent_contents: [<decrypted app_skill_use TOON>]}]` in chat order.
  Use an empty list for a message without a skill use.
- Returns `[{message_id, version, pinned_here}]`.
- `version` comes from the latest pin up to that message, or 1 when there is none.
- `pinned_here` means the message's own parent pins the image, so render it there even though it is not in that
  parent's `embed_ids`.

`embed_pinned_embeds(parent_content) -> string` (free function)
- Returns `[{embed_id, version, embed_ref?, previous_version?}]` for one parent.

`embed_head_version(stored_head_json) -> number` (free function)
- Returns `version_number` of a stored head, with missing meaning 1. Rejects with `protocol` when malformed.
- Shells must not read `version_number` themselves.

`embed_synced_head_regresses(stored_head_json, incoming_json) -> bool` (free function)
- True when a synced or fetched server row would lower the version of the stored child head (`parent_embed_id`
  set); the shell then keeps the stored row. A server row can still be at N while this device holds the N+1 head it
  wrote. Root embeds and equal or newer rows return false. Rejects with `protocol` for rows of different embeds or a
  malformed version.
- A stored head still marked `revision_pending_version` is never kept: the revision write owns it and stores the
  confirmed head after the send. When a row is kept, the shell skips only the IndexedDB put and memory pin; it still
  drops the memory copy, bumps embed availability, indexes refs and runs the caller's write guard.
- A card whose message pins a version above the local head waits; the web shell re-reads the heads it waits for on
  every stored-embed change and re-resolves the cards once the head reached the pinned version.

`BrowserEmbedWriter.embed_version_content(embed_id, version, head_json, rows_json) -> string`
- Returns the plaintext TOON of version K.
- When K is the head version, the content is the head's. Otherwise it comes from the `embed_diffs` chain from the
  latest snapshot at or below K; for a child that is row K alone.
- It uses the parent's key when `head.parent_embed_id` is set. Load the parent key as for any child read.
- Rejects with `embed_version_unavailable` when K is outside `1..=head` or row K is not stored locally.
  In that case fetch the page and cache it (below), then retry.
- Files of version K come from this content (`files`, `aes_key`, `s3_base_url`), never from `upload_files`.

`BrowserEmbedWriter.cache_version_page(embed_id, head_json, page_json) -> string`
- `page_json` is a fetched bounded-v1 page:
  `{embed_id, version_number: K, rows: [{version_number, encrypted_snapshot?, encrypted_patch?, created_at}]}`,
  with K at most the head version and row K present.
- Every ciphertext must open with the head's key owner (the parent for a child) before anything is returned.
- Returns local `embed_diffs` rows (`[{id: "<embed>_v<n>", embed_id, version_number, encrypted_snapshot?,
  encrypted_patch?, created_at, server_confirmed: true}]`), sorted by version, to store.
- Rejects with `protocol` (identity, range, duplicate or missing rows) or `crypto` (wrong key).
