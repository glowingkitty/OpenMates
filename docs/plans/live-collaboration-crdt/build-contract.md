# Live collaboration: build contract (phases 1–4)

This is the shared contract that the parallel implementation lanes build against.
Owner decisions: 22 Nov 2026 (receipt 14ec110bcfa6810c) and 10 Nov 2026 (see
`plan.yml` decisions). Share links stay view-only. Guests and comments come later.

## Invariants

- The Rust core holds the authoritative replica of every open live item.
- Sheets and decks change only through typed operations sent to the core.
- The web app may keep a JS Yjs mirror only for typing: in TipTap (documents) and
  CodeMirror (code). The mirror exchanges opaque update bytes with the core and
  makes no decisions.
- The server stores and relays ciphertext only. It never sees item keys and never
  decrypts a live packet. Plaintext reaches the server only during an assistant
  request, as today.
- The human wins. An assistant change never overwrites a newer human change.

## 1. Core (`packages/openmates-rust/src/client/live/`)

Owner: lane CORE.

- **Item kinds:** `LiveItemKind = Doc | Sheet | Deck | Code`. The wire strings are
  `doc`, `sheet`, `deck` and `code`.
- **Schema adapters:** one shared engine, one adapter per kind. Each adapter
  parses its text form into the Yjs doc (`from_text`) and writes the doc back to
  that form (`to_text`). Round trip: text → model → text is identical for
  canonical text.

| Kind | Yjs root | Text form | Notes |
|---|---|---|---|
| Doc | `Y.XmlFragment` named `default` (the TipTap Collaboration default) | The document embed's stored content format | — |
| Sheet | `Y.Array` `rows` and `cols` (stable ids) plus `Y.Map` `cells`, keyed `"{rowId}:{colId}"`, each value a map `{v, f?}` | Markdown table in A1 notation | Formulas are stored by id and shown as A1. A formula that refers to a deleted row or column renders `#REF!`. |
| Deck | The existing `shared_items/deck*.rs` model | Slides markup | — |
| Code | `Y.Text` named `content` | The file text | — |
- **Sealing:**
  - AES-256-GCM with the item's existing embed key, through `crypto/aead.rs`.
  - Fresh 12-byte nonce per packet.
  - Packet bytes: `version(1)=1 | packet_type(1) | epoch(u32 BE) | nonce(12) | ciphertext+tag`.
  - Packet types: 1 = update, 2 = snapshot, 3 = presence.
  - AAD: `"om-live-v1|" + item_id + "|" + kind + "|" + epoch + "|" + packet_type`.
  - A packet whose AAD does not match (another item, kind, epoch or type) fails to
    open, and the error is typed.
- **Engine API (pure, no I/O, unit-testable):**
  - `LiveItem::open(kind, item_id, key, epoch, snapshot?, updates[])`
  - `apply_local_op(op) -> SealedUpdate`: typed ops for sheet and deck.
  - `apply_mirror_update(bytes) -> SealedUpdate`: doc and code only.
  - `apply_remote(seq, sealed) -> ViewChange`
  - `seal_snapshot() -> (covers_seq, bytes)`
  - `text_form()`
  - `state_vector()`
  - `outbox()`: pending local updates kept across offline periods and restarts,
    through the core cache.
  - `merge_offline()`: on reconnect, send the outbox. If edit access was lost, the
    result is `AccessLost { private_copy_text }`.
- **Presence:**
  - Sealed with packet type 3.
  - Payload: `{user_id, display_name, color, kind_cursor}`.
  - `kind_cursor`:
    - Doc and Code: relative positions for anchor and head.
    - Sheet: `{rowId, colId}`.
    - Deck: `{slideId, elementId?}`.
  - The assistant appears as `{mate_name, editing_scope}`, the "<mate> is editing
    here" lock.
  - Presence expires 30 s after the last heartbeat. It is never stored.
- **Assistant change sets** (`live/assistant.rs`):
  1. Input: the pinned base text form (frozen when the assistant read it), the
     assistant's new text form, and the current live doc.
  2. The core computes the hunks between base and new and anchors each hunk to
     content: Yjs relative positions for Doc and Code, ids for Sheet and Deck.
  3. It applies the hunks as one transaction with origin `assistant:{turn_id}`.
     That transaction is one undo step for the requester and one timeline entry.
  4. Per hunk:

| Case | Result |
|---|---|
| The target range is unchanged since base | Applied. |
| A human changed the same range since base | `Conflict::SameSpot`. The caller re-reads and regenerates once, then shows a suggestion card. |
| The target was deleted | `Conflict::TargetDeleted`. The change is dropped and reported in chat. |
| Sheet: a cell a human changed since base | That cell becomes a suggestion. Other cells apply. |
| Large human changes elsewhere since base (more than about 20% of the text form) | The result carries `needs_recheck: true`. |

  5. Two assistants on one item take turns. A per-item assistant lock in the core
     holds a second change set until the first one commits.
- **Timeline (versions):**
  - Version kinds:
    - `session`: grouped edits, closed after 3 idle minutes or 30 minutes of
      continuous editing;
    - `assistant`: one per assistant change set;
    - `restore`;
    - `named`: a user-given name;
    - `commit`: a Project commit.
  - Each version records its contributors (user ids, the assistant's mate name).
    The core writes each version as one `embed_diffs` row through the existing
    user-revisions route, so the existing timeline and previews keep working.
  - Restore applies the old text form as a new change for everyone and writes a
    `restore` version. Nothing is deleted.
  - Compaction merges `session` versions older than 30 days into one per day and
    keeps `named`, `assistant`, `restore` and `commit` versions. This is a server
    job on metadata only; it re-points to existing ciphertext rows and never
    decrypts.
- **Bindings:**
  - wasm: `openmates-browser-bindings/src/browser_live_item.rs`, exposed through
    the shared Worker.
  - CLI: `openmates live open|edit|watch <embed-id>` for code files and
    documents. The CLI uses the core directly.

## 2. WebSocket protocol (existing `/v1/ws`, lane SERVER)

All `payload` fields are base64 of the sealed packet bytes.

| Client → server | Fields |
|---|---|
| `live_item_subscribe` | `item_id, kind, since_seq?` |
| `live_item_unsubscribe` | `item_id` |
| `live_item_update` | `item_id, client_msg_id, epoch, payload` |
| `live_item_snapshot` | `item_id, covers_seq, epoch, payload` |
| `live_item_presence` | `item_id, payload` (relay only, never stored) |

| Server → client | Fields |
|---|---|
| `live_item_state` | `item_id, role (view\|edit), snapshot? {seq, epoch, payload}, updates [{seq, sender, epoch, payload, ts}], head_seq` |
| `live_item_update_ack` | `item_id, client_msg_id, seq` |
| `live_item_update` (to other subscribers) | `item_id, seq, sender, epoch, payload, ts` |
| `live_item_presence` | `item_id, sender, connection, payload` |
| `live_item_refused` | `item_id, client_msg_id?, reason` |

- `sender` is an opaque per-user hash. The server sets it from the authenticated
  connection and never takes it from the client.
- Refusal reasons:
  - `not_found`
  - `access_revoked`
  - `read_only`
  - `rate_limited`
  - `too_large`
  - `key_epoch_stale`
- **Access** follows the same ownership and membership checks as embed reads and
  user revisions:
  - The owner of a Personal item has `edit`.
  - A Project or Team member gets the role their membership allows. View-only
    roles get `view`.
  - A share link stays view-only: `view`, with no live subscription for anonymous
    visitors in this version.
- **Removal mid-session:** when a membership is removed, every live subscription
  of that user to that Team's or Project's items gets `live_item_refused
  {reason: access_revoked}` and is dropped. Later packets are refused.
- **Storage** (Directus, new schemas):
  - `live_item_updates`: `hashed_item_id, seq, sender_hash, epoch, payload, created_at`;
  - `live_item_snapshots`: `hashed_item_id, covers_seq, epoch, payload, created_at, confirmed`.
  - Redis holds the per-item `seq` counter (INCR), the hot tail and pub/sub
    fan-out across workers.
  - Compaction drops updates with `seq <= covers_seq` only after a snapshot is
    `confirmed`, which a second client does by loading it successfully.
- **Limits:**
  - 256 KB per packet;
  - 64 MB per item log;
  - 50 updates per second per connection; presence is limited to 20 per second.

## 3. Key rotation on Team member removal (lane SERVER + CORE)

- On a Team member removal, the remaining admin client rotates the Team key: a
  new `team_key_epoch`, with Project keys re-wrapped and the encrypted Team
  profile resealed in the same transaction. A concurrent profile change causes
  a retry with the newer ciphertext.
- When an item next opens, the core seals a new snapshot under a new item-key
  epoch, wrapped only for current members.
- A packet with an older epoch after rotation gets `key_epoch_stale`. The client
  fetches the new wrapper and re-seals its outbox.

### Persisted revisions after removal

- Membership removal, wrapper revocation and the pending-rotation flag commit
  together. Rotation and revision writes lock the same Team row before reading
  membership. A pending rotation refuses a new revision.
- Derive a separate revision key from the Team epoch key and the item identity.
  Authenticate the item, revision number, epoch and field when sealing the
  head, preview and history. A retained embed, chat or Project key must not
  open these fields. Keep the original embed key for reading historical rows
  written before this format, and use the encrypted predecessor chain to read
  rows written under older rotation epochs.
- The version transaction checks the ciphertext's epoch against the locked Team
  row and refuses a stale or unversioned write after rotation. Apply the same
  check to restore, hosted writeback and legacy mutation routes that can update
  the same item. Keep an already committed operation's receipt replay behavior.
- Project and chat reads, preview, timeline and restore must handle mixed rows
  before the new writer is enabled. During and after rotation, assistant file
  tools dispatch to the authorized device. Cloud commands receive the device's
  bounded, consent-checked Project snapshot and return an `apply_changes` job
  for that device to seal and commit. The persistent sandbox and the backend
  never receive a Team epoch key.
- Verify that a remaining member can close and reopen the item after a
  post-removal revision, read its older history and restore it as a fresh
  revision. Verify independently that the former member's retained keys fail
  to open both the post-removal live packet and stored revision.

## 4. Assistant edits (lane ASSIST)

- `stream_consumer.py` no longer writes `current_version + 1` for live-capable
  items.
- The server sends the requester's devices `embed_assistant_change` with
  `{embed_id, turn_id, base_version, new_text_form, mate_name, scope}`. This
  payload is encrypted the way embed content is encrypted today for the client.
- When the diff starts streaming, the server sends
  `embed_assistant_editing {embed_id, scope}`. The requester's core turns it into
  assistant presence.
- The requester's core applies the change set (section 1). If no device of the
  requester is online, the change waits in the existing 24 h vault cache and is
  applied when one comes online.
- Hosted Project code in an E2B sandbox:
  1. The assistant edits the sandbox copy.
  2. On write-back, the core runs a three-way merge: base = the sandbox checkout
     version, ours = live, theirs = the sandbox.
  3. If the same lines changed on both sides, the result is a proposal (a
     suggestion card), never an overwrite.
  4. Tests rerun after the merge.

## 5. Web (lane WEB)

- **Document editor:** TipTap with `@tiptap/extension-collaboration` and
  `@tiptap/extension-collaboration-caret` (cursors). The `contenteditable`
  `DocsEditor` is removed.
- **Code editor:** CodeMirror 6 with `y-codemirror.next`. The textarea
  `CodeEditor` is removed.
- **Sheet grid and slides editor:** send typed ops to the core and render its
  view model.
- **Header:** shows Saved, Saving and Waiting for connection, and the avatars of
  the people present with their colours.
- **No Save button.** The Edit button enters and leaves edit mode.
- **Flag:** `live_collaboration`. It is on in CI; on dev and prod it is switched
  on only after Marco's go.
