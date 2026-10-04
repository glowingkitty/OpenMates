# Immediate Mac action for the active development storage API

Development backend commit
`1e7b84c33ea33734ec53c85deda27b90aad3124d` is now public and active. The user
is the only Apple tester and does not require backward compatibility for this
development rollout, so the legacy-client compatibility hold is cleared on dev.
Production is unchanged. Do not use that decision to bypass capability checks or
to claim native reader compatibility.

1. On every authenticated WebSocket connection and reconnect, advertise
   `canonical_embed_receipts_v1` only when the ordinary canonical writer enforces
   the complete strict contract. Never infer this capability from epoch or
   protocol 1 and never accept it from an incoming event.
2. Main app and Watch must write the canonical head first. Accept
   `store_embed_confirmed` only for the exact `request_id` and `embed_id`, with
   lowercase SHA-256 of the exact UTF-8 `encrypted_content` string in
   `canonical_digest` and `canonical_source: "head"`. Then write wrappers and
   accept `store_embed_keys_confirmed` only for the exact request with
   `failed_count == 0` and `created_count == requested_count == keys.count`.
   `client_capability_required`, absent fields and any mismatch remain pending.
3. Preserve byte-identical ciphertext, wrapped keys and immutable saved-turn
   preflight data across rejection, disconnect and retry. Serialize normal and
   typed writes for the same embed and reuse verified canonical ciphertext; do
   not create a second head or retire pending data before the exact receipt.
4. Advertise `typed_recovery_outputs_v2` only after bounded discovery, exact get,
   canonical persist/reread and typed ACK handling are fully wired. Ordinary
   canonical capability does not imply typed capability. Typed recovery failures
   must retain every pending record.
5. Run zero-inference native fixtures covering main app and Watch head-before-keys,
   exact digest/source/request/count validation, retry identity, same-embed
   normal/typed serialization and capability rejection. Full typed readers,
   archive readers and cross-client concurrency remain pruning gates.

The active backend allows this native work against development now. The detailed
payloads and fixtures below remain authoritative. Return the public Apple commit
and focused iOS/macOS/Watch results; do not activate production behavior from
this handoff.

---

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

Preserve the Mac chat's existing changes and follow its session integration workflow for a dirty or detached task worktree. Read this handoff, the storage Plan, and `specifications/architecture/storage-lifecycle/specification.yml` when the backend changes reach dev. The approved Specification, Plan and backend implementation are published. Pull development commit `1e7b84c33ea33734ec53c85deda27b90aad3124d` or newer before implementing and verifying this contract.

## 1. Repair the live AI embed writer first

Production code: `apple/OpenMates/Sources/Core/Networking/WebSocketManager.swift`, `ChatEmbedStreamCoordinator.encryptAndPersist`. Focused tests: `apple/OpenMatesTests/StreamingClientFanoutTests.swift`.

The initial audit found wrappers sent before the head. The public 2026-10-03 Apple audit now confirms the main writer is head-first, while Watch still sends keys first. Main-app production still explicitly permits legacy receipts and advertises neither storage capability. The new database parent guard rejects wrappers when their canonical embed head does not exist. A confirmed event with `failed_count > 0` is a failed save, so the current native sequence can incorrectly mark an embed persisted without durable wrappers.

Implement this sequence:

1. Preserve local client encryption, wrapped master/chat keys, generation/scope/deletion checks, owner PII separation, and offline/retry state.
2. Register the matching receipt waiter before sending `store_embed`.
3. Await `store_embed_confirmed` for the exact `request_id` and `embed_id`. Require `canonical_source == "head"`. The new backend adds `canonical_digest`: lowercase SHA-256 of the UTF-8 **encrypted_content string**, not decoded ciphertext or plaintext. Require the matching digest for the new storage path. The active development API supplies those fields. A missing field cannot become evidence of new-path durability.
4. Only after that head receipt, send `store_embed_keys` and await `store_embed_keys_confirmed` with the exact `request_id`. Require `failed_count == 0`, `created_count == sent keys.count`, and `requested_count == sent keys.count` (normally two wrappers). Reject absent, malformed or partial counts.
5. Mark the finalized payload processed only after both saves succeed. Preserve retry on timeout, disconnect, head failure, digest mismatch, or wrapper failure. Retries must preserve the original encrypted identity and must not let an older payload overwrite a newer one.

Use the web sender in `frontend/packages/ui/src/services/embedSenders.ts` and its receipt tests as the reference once pulled. The backend receipt contracts are in `store_embed_handler.py` and `store_embed_keys_handler.py`.

Update the existing native ordering and deduplication assertions rather than weakening them. Add focused cases for head timeout/failure (no wrappers sent), digest mismatch, failed/partial wrapper counts, disconnect/retry, and duplicate finalized delivery. Update `ChatEmbedRecordingTransport` to emit realistic digest/count receipts.

Composer, background, and Watch attachments use bundled `chat_message_added.encrypted_embeds`; their server path writes the head before wrappers. Preserve those clients while checking their failure/acknowledgement behavior. The backend chat owns any server-side bundled persistence repair. Main-app `ChatViewModel` currently skips a persistable embed with missing content; fail the send instead of silently omitting a required attachment. Background and Watch builders already throw on missing required encryption inputs. Preserve the original encrypted bundle for retries of the same message identity so rebuilding encryption with a fresh nonce cannot mutate a partially persisted attempt. Verify that already stored references and actual artifact edits retain their intended behavior.

### Preserve existing file references

For saved-message attachment preparation, use the new metadata-only `POST /v1/embeds/chats/{chat_id}/references/availability` against the active development backend. Send `{"embed_ids":["<id>"]}` in batches of at most 20 (4 KiB request, 8 KiB response); Team scope is the `team_id` query parameter. Response `results` entries classify each ID as `ready`, `missing`, or `unusable`. Validate one result per requested ID and fail on unavailable/malformed responses.

A fresh `ready` reference needs no new head. A `missing` ID requires a complete new encrypted bundle. An authorized `unusable` reference must stop the send rather than overwrite its head. Personal references can use their owner's master wrapper across owned chats; Team references need the authorized target-chat wrapper and live Team access. For a partially saved message, replay its retained original encrypted bundle even if the probe now reports `ready`: its immutable preflight and ciphertext identity must remain the same.

Do not fetch full ciphertext merely to probe availability. Exact embed GET and key continuation may legitimately return a readable head whose `hashed_chat_id` belongs to a different source chat. Use target-scoped wrappers and current permissions; do not reject solely on that origin hash. Add owner cross-chat reuse, Team wrapper/revocation, missing required content, and closed-app retry coverage.

### Candidate WebSocket payloads

The reviewed storage API candidate accepts a comma-separated WebSocket query value such as
`client_capabilities=canonical_embed_receipts_v1,typed_recovery_outputs_v2`.
Capabilities belong to that authenticated socket; reconnect with a new socket
must advertise them again. Never copy a capability from an incoming event or
persist it as account authority.

For an ordinary canonical head write, send:

```json
{"type":"store_embed","payload":{"request_id":"<uuid>","embed_id":"<embed-id>","encrypted_content":"<exact ciphertext string>","encrypted_type":"<ciphertext>","status":"finished","hashed_chat_id":"<sha256 chat id>","hashed_message_id":"<sha256 message id>","hashed_user_id":"<sha256 owner id>","version_number":1}}
```

Accept only:

```json
{"type":"store_embed_confirmed","payload":{"request_id":"<same uuid>","embed_id":"<same embed-id>","canonical_digest":"<sha256 of exact encrypted_content UTF-8>","canonical_source":"head"}}
```

Then send `store_embed_keys` with `{"request_id":"<new uuid>","keys":[...]}`
and accept only `store_embed_keys_confirmed` with that request ID and exact
`created_count`, `failed_count`, and `requested_count`. Recovery writes add
`recovery_record_id` to `store_embed`, `store_embed_diff`, and
`store_embed_keys`; those writes require both advertised capabilities. A
capable diff writer must also require `store_embed_diff_confirmed` with the
exact `embed_id`, `version_number`, `canonical_source == "version_row"`, and
lowercase 64-hex `canonical_digest`. An unsupported write receives `error`
with `code == "client_capability_required"` and the matching `request_id`; it
must remain pending and must not be reported as saved.

## 2. Complete native readers and unattended recovery compatibility

The writer fix alone is not an Apple storage compatibility receipt. Audit and implement the following against the actual pulled backend contracts:

- Paginated message and wrapper windows, compression checkpoint metadata, exact oversized-message fetches, and hot/S3 history boundaries. Use `/v1/chats/{chat_id}/messages/window` and the exact-message endpoint; preserve cursors, deduplication, full ciphertext and visible retry. A normal scroll must not fetch an entire transcript.
- Typed sealed recovery for original child prompts, transcript messages, summaries, compression checkpoints, embeds and diffs. The existing final-text-only recovery path is insufficient. Follow `frontend/packages/openmates-cli/src/client.ts`, `ws.ts`, `crypto.ts`, and `frontend/packages/ui/src/services/chatSyncServiceHandlersRecovery.ts`. Use the shared fixture `backend/tests/fixtures/chat_recovery_output_v2.json` for cross-client cryptographic compatibility.
- Bound recovery discovery to its pages and wait for `recovery_outputs_discovery_complete` before replaying dependent work. Persist each canonical client-encrypted output before its typed acknowledgement. Preserve pending outputs on partial failures, account changes, revoked Team membership, stale identity, or decryption failure. Client-only recovery ciphertext must not be treated as server-readable inference context.
- Paginated embed version metadata, on-demand old ciphertext, periodic client snapshots, and a bounded patch chain. Verify version 101+ and historical selection without downloading every payload.

The three recent main chats and active-child budgets apply to the **server Redis working set**. They do not instruct the native client to discard local chat history or pending writes. PostgreSQL retains all-chat encrypted metadata; cold transcript pages contain about 20 messages/256 KiB initially, with large bodies fetched separately.

### Typed recovery event contract

On a capable connection, the server sends zero or more
`recovery_outputs_available` pages with `payload.outputs`, followed by exactly
one `recovery_outputs_discovery_complete` with `payload.status` equal to
`completed` or `failed`. Buffer the bounded pages and begin dependent canonical
writes only after the `completed` marker; discard the batch on `failed`. Process
the completed batch serially in canonical dependency order: message (user before
assistant), embed, diff, summary, checkpoint. Do not infer completion from an
empty page, a disconnect, or a local row.

Each output index carries `record_id`, `root_chat_id`, optional
`root_hashed_team_id`, `target_chat_id`, `turn_id`, `subject_id`, `output_kind`,
`output_version`, `chat_key_version`, and optional `message_role`. Fetch the
sealed body with:

```json
{"type":"recovery_output_get","payload":{"protocol_version":1,"record_id":"<record>","request_id":"<uuid>"}}
```

Accept only `recovery_output_ready` with the same `record_id`, `request_id`, and
every indexed identity field unchanged. Decrypt and validate the identity
inside the v2 plaintext before any canonical write. The canonical operations
and success events are:

| Kind | Client operation | Required success event |
| --- | --- | --- |
| `message` | `recovery_output_persist_message` with `protocol_version`, `record_id`, `request_id`, `expected_messages_v`, and exactly one of `encrypted_user_message` or `encrypted_assistant_message`; include `encrypted_chat_key` and `encrypted_title` when creating the child | `recovery_output_persisted`, same record/request, `state == "ACKNOWLEDGED"` |
| `summary` | `recovery_output_persist_summary` with `expected_metadata_v` and `encrypted_summary` | `recovery_output_summary_persisted`, same record/request, `state == "ACKNOWLEDGED"` |
| `checkpoint` | First persist `store_chat_compression_checkpoint` and verify its canonical echoed identity, ciphertext and boundaries; then send `recovery_output_ack_checkpoint` with `encrypted_summary`, `compressed_up_to_message_id`, and `covered_message_ids` | `recovery_output_checkpoint_acknowledged`, same record/request, `state == "ACKNOWLEDGED"` |
| `embed` or `diff` | Persist and reread the exact canonical head/version row and exact required wrappers; then send `recovery_output_ack_embed` with `canonical_digest` and `canonical_source` | `recovery_output_embed_acknowledged`, same record/request, `state == "ACKNOWLEDGED"` |

For embed recovery, `canonical_source` is `head` when the digest is SHA-256 of
the exact encrypted head content string. For diff recovery it is `version_row`
and the digest is SHA-256 of the UTF-8 JSON serialization
`[encrypted_snapshot_or_null,encrypted_patch_or_null]`. Before the ACK, reread
and decrypt the canonical content, and require exactly one master wrapper and
one target-chat wrapper for the derived embed key. Parent embeds reuse the
parent key subject. A bad digest, wrong source, incomplete wrapper set, failed
discovery, Team mismatch, version conflict that cannot be safely refreshed, or
disconnect leaves the output pending for rediscovery. `error` with
`code == "client_capability_required"` is an update-required result and never
an acknowledgement.


### Native crypto can start before API activation

The shared `backend/tests/fixtures/chat_recovery_output_v2.json` is published independently of the running API. Its private key and ciphertext are synthetic test material. Use it for a CryptoKit compatibility test now; it does not indicate that the development API emits v2 output yet. Its expected plaintext is `{"content":"sealed child output"}`.

For that v2 envelope, keep the existing X25519 / HKDF-SHA256 / AES-GCM primitives:

1. Decode canonical unpadded base64url fields. `epk` is a 32-byte raw X25519 public key, `nonce` is 12 bytes, and `ciphertext` includes the final 16-byte GCM tag.
2. Construct AAD as UTF-8 `OMCR2`, then the seven strings `owner_id`, `root_chat_id`, `target_chat_id`, `turn_id`, `record_id`, `subject_id`, `output_kind`, in that order. Each string has a four-byte unsigned big-endian UTF-8 byte length before its bytes. UUID strings must use canonical lowercase encoding. Append `key_version`, then `output_version`, each as a positive four-byte unsigned big-endian integer.
3. Derive a 32-byte symmetric key from the X25519 shared secret using HKDF-SHA256, salt `SHA256(UTF8("openmates:chat-recovery-envelope:v1"))`, and info `SHA256(AAD)`. The v2 envelope deliberately retains that existing salt; the authenticated identity has the v2 prefix.
4. Decrypt AES-GCM with that key, nonce and exact AAD. Require envelope version 2 for this reader. Reject identity changes and authentication failures rather than treating them as legacy final-text output.

The backend source in `backend/shared/python_utils/chat_completion_recovery.py` and web/CLI readers become the implementation reference when the backend commit reaches dev. The publication check verified the fixture plaintext, exact AAD construction and failure after a version-identity change, with no inference or real account data.

### Immutable saved-turn preflight

Retain one chat-key-encrypted journal containing the exact `chat_turn_preflight`
payload before its first send. Its required fields are `protocol_version: 1`,
`chat_id`, `turn_id`, `message_id`, `chat_key_version`, `encrypted_chat_key`,
`recovery_public_key`, `expected_messages_v`, `encrypted_user_message`, and the
exact `inference_request`; include `team_id` and `encrypted_chat_metadata` only
when applicable. Register the waiter first, then send the event. Accept only
`chat_turn_preflight_ack` with the same `turn_id` and a nonempty `preflight_id`.
Add that `protocol_version` and `preflight_id` to the unchanged inference
request. Do not rebuild randomized ciphertext, change the turn/message ID, or
mutate committed inference fields after the ACK.

Keep the journal through a timeout or disconnect. Clear it only after
`chat_message_confirmed` matches the exact `chat_id`, `message_id`, and
`new_messages_v == expected_messages_v + 1`. An earlier generic or unversioned
message confirmation is not durable admission proof. A retry with the same
immutable payload may return the same committed preflight; any changed key,
ciphertext, scope, content commitment, or identity must fail rather than create
a second turn.

## 3. Verification and return handoff

Keep existing Specification/test metadata; add the storage assertion IDs actually proved. Relevant assertions include `storage.background.complete-sealed-recovery`, `storage.background.saved-output-retention`, `storage.cold.independent-message-pages`, `storage.versions.bounded-reconstruction`, `storage.privacy.ciphertext-boundary`, and `storage.surface.semantic-parity`. Preserve the existing `chats.persistence.client-encrypted` metadata for the live writer tests. Regenerate Specification artifacts through the repository workflow.

Run `StreamingClientFanoutTests` with the installed Xcode on the Mac, then focused recovery, history-window, and version tests for changed behavior. Verify iOS and macOS compile; check Watch when shared inputs affect it. Use repository-local build artifacts and the Mac chat's coordinated native workflow. No real inference requests: use synthetic encrypted fixtures and the real isolated API/storage paths for integration evidence. Do not access/delete real account data for tests.

Check child lifecycle routing using the actual backend completion frame:
`sub_chat_completed` has `chat_id` equal to the child and `parent_id` equal to the
parent whose stream receives it. Scope that event by `parent_id`; preserve the
child ID in its payload. A synthetic native test must accept that frame for the
active parent and reject a completion with an unrelated parent. The CLI pilot
found and repaired precisely this mismatch; its old test incorrectly used the
parent as `chat_id`.

Use disposable native fixtures with unique account/chat/message/embed IDs and the
backend test setup/cleanup path. Each integration case must inspect the
canonical rows after the socket exchange; counting client events alone is not
sufficient. Run these without sending a provider-bound `message_received`:

1. **Capability admission:** connect once without either capability. Attempt
   untagged `store_embed`, `store_embed_keys`, and `store_embed_diff`, then typed
   get/persist/ACK calls. Require `client_capability_required`, no normal success
   event, and no head, wrapper, version, lease, or ACK mutation. Confirm the
   pending typed record is still discoverable by a later capable connection.
2. **Canonical writer:** on a capable socket, write a synthetic encrypted head,
   verify its exact `head` digest receipt, then write two wrappers and verify all
   three counts equal the sent set. Reread the head and wrapper set. Exercise
   wrong digest, wrong request ID, partial count, keys-before-head, disconnect
   after head, and exact retry; none may mark local persistence early or create
   conflicting canonical rows.
3. **Reference probe:** seed owned `ready`, owned `unusable`, and absent IDs.
   Verify one ordered result per requested ID, Team revocation behavior, the
   20-ID/request limits, and that the response contains no ciphertext. A
   malformed, missing, duplicate, or extra result fails the send.
4. **Immutable preflight:** send only `chat_turn_preflight` for a disposable
   encrypted message and stop before inference dispatch. Drop the ACK locally,
   reconnect, replay the byte-equivalent retained payload, and require one
   canonical user row and one durable preflight identity. Mutating ciphertext,
   key, version, message, turn, chat, or committed inference payload must not
   create another admission. Verify the local journal survives stale/unversioned
   `chat_message_confirmed` and clears only on the exact versioned receipt.
5. **Typed recovery:** seed signed pending records for message, embed, diff,
   summary, and checkpoint with synthetic ciphertext. Verify paginated discovery
   plus its completion marker, v2 identity validation, canonical persistence,
   reread, and exact typed ACK. Inject bad envelope identity/tag, digest/source,
   wrapper count, Team scope, and a disconnect between save and ACK; each record
   must remain pending until a capable client completes the exact flow.

Also run the local CryptoKit fixture test against
`backend/tests/fixtures/chat_recovery_output_v2.json`: require the published
plaintext, then independently alter every AAD identity field, `output_version`,
`key_version`, nonce, ephemeral key, and ciphertext and require authenticated
decryption failure. This local fixture complements the disposable row tests; it
does not advertise either capability by itself.

Return: Task/workspace, deployed dev commit, owned paths, platform/build/test results, exercised receipt and recovery scenarios, and unresolved compatibility/release blockers. Publish using the Mac chat's existing session rules. A TestFlight release follows that chat's existing authorization; code publication alone does not prove installed clients are upgraded.

## Activation dependency

### Explicit client capability checks

The 2026-10-04 audit of candidate `07e1ecf8f71129748db77346ff62a642c8a3d50d`
confirmed that recovery epoch 1 and `protocol_version: 1` also occur in the
current Apple client. Neither proves the new writer or typed-output support.
The backend chat is preparing explicit capability guards; these guards are not
yet published or verified. The intended capability names are:

| Capability | Advertise only after native verification |
| --- | --- |
| `canonical_embed_receipts_v1` | Head before wrappers, exact encrypted-content digest, exact successful wrapper counts, and retained original ciphertext on retry. |
| `typed_recovery_outputs_v2` | Authenticated v2 envelopes for every required output, bounded discovery, exact canonical persistence, typed acknowledgements, and retained pending records on failure. |

Include the verified capabilities in the WebSocket `client_capabilities` query
parameter; do not advertise them merely because the client has a recovery key.
These capabilities identify readers and canonical writers. The existing
protocol-1 admission already binds the recovery public key to the durable
preflight; it can seal v2 outputs without the original client understanding v2.
Another capable device of the same owner can derive the recovery private key
from the synced root chat key. Existing SDK admission and v1 final-text recovery
remain supported; a new REST capability header is not required for those paths.

An unsupported client must receive an explicit update-required response before
an affected canonical embed write or typed recovery operation. Connecting it must not
claim, acknowledge, downgrade or delete typed pending recovery records. Keep
ordinary authorized reads available. The backend chat will verify these cases
with synthetic data before activation. The Mac chat should return focused
native evidence for both advertised capabilities and a concrete installed-client
release/cutover policy; publishing source alone is insufficient.

Hold deployment of handlers requiring the new parent/key writer contract until
the supported native sender is verified and the release/compatibility policy is
settled. Turning archive switches off does not gate these writer checks. All
archive worker switches default off; real pruning additionally requires
supported-reader receipts, the 24-hour source buffer, full zero-inference
capacity/lifecycle tests, and per-unit safety fences. The current small CI
profile cannot prove 500 simultaneous executions. No Apple receipt or full-scale
capacity result has been claimed.

The source audit of candidate `b1cb1fe84b3b5f529e169985f2bf0c02da2dfc0f`
also confirms that `protocol_version: 1` and recovery epoch 1 do **not** prove
support for typed sealed-output replay: older Apple clients already send that
preflight version. The release must identify an explicitly capable client or
hold unsupported binaries from paths needing the new writer and recovery
contracts. Code publication alone does not upgrade installed apps. Retained
outputs must remain available until their canonical save acknowledgement or
authorized deletion; matching privacy copy must change with that API behavior.


## Additional sender and storage-billing requirements

These corrections are in the reviewed Linux candidate and still require its
source-bound CI and coordinated backend/web release. Pull the implementation
commit when it is announced; the Mac chat keeps ownership of native changes.

### Saved message references and uncertain ACKs

- Extracted code/table references must be present in the **canonical encrypted
  user message**, as well as the message supplied to inference. Encrypting the
  original editor markdown while only inference receives the artifact reference
  loses that reference after reload.
- Preserve each extracted artifact ID and its exact encrypted bundle across
  retry/restart. Retaining random IDs is acceptable. If deriving IDs, use a secret
  chat-key HMAC with domain separation; a public plaintext SHA mapping exposes a
  guessing oracle.
- Before dispatch, retain the exact turn ID, encrypted user message, commitment,
  wrappers, and preflight identity in client-encrypted retry storage. An uncertain
  ACK cannot generate another turn ID or another ciphertext under the committed
  message ID. Bind the journal to account, chat, message, key and final content.
- For AI turns, a generic legacy `chat_message_confirmed` status may precede turn
  acceptance. The web candidate clears its exact preflight journal only for the
  matching chat/message and committed `new_messages_v == expected_messages_v + 1`.
  Native must likewise distinguish a canonical accepted receipt from an earlier
  metadata status, and preserve pending data when the proof is absent. Keep the
  existing separate ordinary-Team preflight path compatible.
- Reconcile the optimistic local encrypted message to the exact canonical
  artifact-reference ciphertext before dispatch. A synced local status must not
  preserve original editor fences while rejecting canonical hydration on reload.
- Add tests for saved code after reload, exact replay after lost ACK/restart,
  legacy/stale/cross-chat ACK rejection, and no retry-journal resurrection when
  a later sync write replaces the message row.

### Weekly storage settings

The additional `feature.billing@6` contract is awaiting user review. This section
is a proposed API handoff, not authorization to activate native billing behavior
before that review and the matching backend release.

`GET /v1/settings/storage` keeps `total_bytes`, `free_bytes`, weekly price, and
legacy uploaded-file breakdown. The candidate additionally returns:

| Field | Native handling |
| --- | --- |
| `logical_s3_bytes` | Optional on older APIs; included in authoritative personal `total_bytes` only under the active billing policy. |
| `metering_categories` | Optional map of additional billable category bytes; display positive recognized entries as storage, not as uploaded-file counts. |
| `metering_source_version`, `metering_policy_version` | Preserve for consistency/debugging; do not show raw internal identifiers as category names. |

Recognized category labels:

| API key | User label |
| --- | --- |
| `chat_pages` | Saved chat history |
| `chat_oversized` | Large chat messages |
| `cold_chat_graphs` | Older chat archives |
| `embed_versions` | Artifact history |
| `sealed_recovery` | Outputs waiting to sync |

`total_bytes` remains authoritative. Legacy `breakdown` and `total_files` describe
uploaded/generated files; archive pages are not additional uploaded files.
Example native fixture: 256 MiB uploaded files plus logical categories of 128,
64, 32, 16 and 8 MiB gives 504 MiB total. Also test an older API response with no
new fields. Personal pricing stays 1 GiB free and 3 credits per started excess
GiB per week. New logical-S3 charging defaults off in the backend; Team payer and
allowance remain pending approval, so native must not invent a Team storage bill.

The four-warning notices and final-payment/reference-safe expiry workflow must
be released with matching policy and backend behavior. Do not add native
expiration actions or assume the inactive archive-billing rollout is enabled.
