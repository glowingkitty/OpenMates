# Live collaboration v2: audit, scope and architecture proposal

Plan `live-collaboration-crdt`, Specification `feature.live-collaboration@1` (draft).
Date 2026-11-14. Builds on the Phase 0 spike (`spike.md`, 2026-11-10) and the
user decisions recorded in `plan.yml`. Status: proposal, waiting for the owner's
decisions (section 6). Nothing here is implemented yet.

What is new compared with the spike:

- code files in hosted Projects;
- live assistant edits;
- the same account on several devices;
- Team key rotation;
- view, comment and edit roles;
- editing through share links by signed-in outsiders and anonymous guests;
- an evaluation of PowerSync.

## 1. Audit: what exists today (dev, commit d95e2b13b3)

Shared facts for all four types:

- **Saving.** A save writes the whole content as the next embed version
  (`POST /v1/embeds/{id}/user-revisions`, Rust `client/embed_user_revision.rs`).
  The head is re-encrypted with the embed key.
  - A save from a stale base is refused with `embed_version_conflict`. Nothing
    is ever merged.
  - Hosted Project files keep an encrypted patch per revision and a full
    snapshot every 32 revisions (`work/projects/hosted/job.rs`).
- **Live updates.** No WebSocket messages exist for live edits, presence or
  CRDT packets.
  - After a user save the server sends `embed_revision_committed` to the same
    user only, and only the diagram fullscreen listens for it.
  - Team members get no live push.
- **Assistant edits to chat embeds.** The server decrypts the vault cache copy
  and applies a unified diff to the plaintext (`backend/apps/ai/tasks/stream_consumer.py`).
  It then writes `current_version + 1` without checking for a user save made in
  the meantime. An open fullscreen refreshes when the whole diff block has been
  applied, not while it streams.
- **Assistant edits to Project files.** These go through `project_update_file`
  with an expected base hash, run on the client and are client-encrypted.
- **Keys.** Each item has its own embed key, wrapped for the master key, the
  chat key and the Project key.
  - A Team Project key is wrapped with the Team key and records
    `team_key_epoch`.
  - Team keys are never rotated (`docs/architecture/teams.md`; the Teams
    Specification excludes rotation).
- **Share links.** The embed key travels in the URL fragment, inside a blob
  sealed with a key derived from the embed id, optionally with a password.
  - The duration is stored inside the blob, so expiry is checked by the
    client, not the server.
  - Links are view-only.
- **Versions and commits.** Every save is a version in `embed_diffs`. Restoring
  creates a new version.
  - A native Project commit only points at `{file, embed_version}`, so commits
    keep working if versions come from a CRDT.
  - There is no hosted Git object model.
  - Per-chat Git worktrees exist only on a connected machine.

| Type | Web | Apple | CLI |
|---|---|---|---|
| Documents | Custom `contenteditable` editor (`DocsEditor.svelte`, `execCommand`, not TipTap); Edit/Save toggle. Saves HTML and drops `docx_model`. On a conflict, Reload loses the user's edits. Tests: `docs-editor.spec.ts`, `projects-create-edit-files.spec.ts`, `embed-diff-editing.spec.ts`. | Viewer only (`DocumentCanvas`); no editor, no editing tests. | `embeds show`, `embeds versions list/show/restore`; no content edit. |
| Sheets | Custom Svelte grid inside the fullscreen; each committed cell saves the whole markdown table as a new version. Not in the core model. On a conflict, a toast shows and the sheet reverts. Tests: `sheet-edit-real.spec.ts`, `sheet-fullscreen.spec.ts`, Projects E2E. | Viewer only (`SheetRenderer`, XLSX export). | View and versions only. |
| Slides | `SlidesEditor.svelte` sends typed operations to the core's in-memory `yrs` replica (`client/shared_items/deck*.rs`) with core undo; the save writes the serialised markup as a whole version. Rust-core builds only. Tests: `slides-editor.spec.ts` (10 tests), `slides-manual-edit.spec.ts`, core `deck_convergence_tests.rs`. | View and present only (`parse_deck_markup`, not `DeckDocument`). | Nothing. |
| Code | Plain textarea with a gutter (`CodeEditor.svelte`, not CodeMirror), Project files only; saves the full text. On a conflict, a reload button. Tests: `code-editor.spec.ts`, `cli-native-project-hosted-files.spec.ts`. | Viewer with highlighting; no editor. | **Full edit:** `projects hosted list/read/create/update/rename/delete`, patch with expected base, commits. |

Projects work from chat 9382ed57 (commit 7512c73eb1):

- What works: creating and editing the four types in Project folders, with an
  Edit/Save toggle.
- Limits:
  - dev-only behind the `platform:projects` flag;
  - needs the Rust-core build flag;
  - Personal Projects only, because Team Projects have no core save scope;
  - one user at a time, whole-file saves, conflicts refused.

### Gaps

1. No multi-user, multi-device or live editing for any type, on any surface.
2. Assistant chat-embed diffs skip the version check, so an assistant edit can
   overwrite a user save made at the same time. `embed-diff-editing.md` still
   says "last-write-wins".
3. No editor merges an incoming change. Conflicts end in a reload, which loses
   the user's edits in the document and code editors.
4. The document editor drops `docx_model` on save, and the spike's TipTap
   binding does not exist.
5. Sheets and documents are not in the core shared model; only decks are.
6. No Team key rotation; share-link expiry is checked only by the client.
7. Apple has no editors; the CLI edits only code Project files.

## 2. What "real-time" means: four levels

| Level | Meaning | Needed | Why |
|---|---|---|---|
| R1 | Live assistant edits: the open document changes in place, block by block, while the assistant writes. | **Now** | This is what users feel most, and it is also the fix for gap 2. |
| R2 | User and assistant edit at the same time without conflicts. | **Now** | Required as soon as R1 exists: the user keeps typing while the assistant edits. |
| R3 | The same account on several devices, such as a laptop and a phone. | **Now** | This needs no new rules: once R2 has transport, a second device is just another replica. |
| R4 | Several people co-edit: Team and Project members, presence, roles, key rotation. | **Next** | This was the owner's decision on 9 and 10 Nov, including across Teams. Membership, roles and key rotation are the extra work. |
| R5 | People outside the Team edit through a share link, signed in or as guests. | **Later** | This carries the highest abuse and security risk. It comes after R4 is stable. |

All five levels run on the same machinery: an encrypted change log, a live relay
and a shared model in the core. The levels differ only in who may join and which
key they get.

## 3. Options

### Option A: encrypted Yjs relay owned by the Rust core (recommended)

This is the spike's design, extended.

- The Yjs v1 format with `yrs` in the core.
- Every open item has one authoritative replica in the core.
- Changes are sealed with AES-256-GCM using the item key, with an AAD that binds
  item id, packet kind and key epoch.
- The packets travel over the existing WebSocket. The server keeps an
  append-only ciphertext log and a live relay and never reads content.
- Clients make encrypted snapshots for compaction.
- Named versions are full encrypted states plus their text form, so the
  `embed_diffs` timeline, previews, search and exports keep working.

| Pros | Cons |
|---|---|
| Proven in the spike: convergence, assistant change sets, undo, presence, out-of-order delivery | Snapshots are made by clients, so the server cannot validate them (mitigated: keep the old snapshot until a second client loads the new one) |
| Fits "one core, three shells": Apple and the CLI get it through bindings | `yrs` is pre-1.0 and must be pinned (already `=0.28.1`) |
| Adds about 125 KB gzip to the wasm | Web typing needs a JS Yjs mirror (approved for rich text; this proposal asks to extend it to code) |
| Uses our key hierarchy, WebSocket and Directus with no new service | Key rotation and share links are our own work (sections 4.4 and 4.5) |
| Secsync uses the same snapshot-plus-update shape for encrypted Yjs | |

### Option B: PowerSync carrying ciphertext rows

PowerSync replicates rows from a Postgres database (through logical replication)
into a SQLite database on the client. Writes go back through our own API.

Under client-side encryption:

- PowerSync would only carry opaque rows of Yjs updates, which is the same log
  as in Option A, behind an extra service.
- It does not merge text, so we would still need Yjs.
- It has no presence or ephemeral channel.
- Its sync rules can partition only by columns the server can read, which is
  just the Team and item ids.

| Pros | Cons |
|---|---|
| A mature offline-first engine for relational data | A second sync stack beside the Rust core's phased sync, which breaks the rule that the core owns sync and cache |
| Built-in local SQLite with at-rest encryption on some SDKs | A new self-hosted service; the Open Edition is FSL-licensed and becomes Apache 2.0 after two years |
| | Adds replication lag from the database log, and presence needs a separate channel anyway |
| | Brings nothing to merging, keys or permissions |

**Verdict: not needed.** PowerSync solves row sync, which our phased sync and
encrypted cache already do. Our problem is merging encrypted text, which
PowerSync does not do.

### Option C: Automerge with Keyhive/Beelay

Automerge is a Rust/wasm CRDT. Keyhive and Beelay are Ink & Switch's
capability-based access control, group key agreement and encrypted sync for it.

| Pros | Cons |
|---|---|
| Key rotation, revocation and capabilities are part of the design | Keyhive and Beelay are pre-alpha and experimental; a newer protocol (Subduction) is still moving |
| Full history is built in | The largest wasm and an immature ProseMirror binding (spike) |
| | It would replace our key hierarchy (master, Team and Project keys) |

**Verdict: watch, do not adopt.** It is worth a fresh look once Keyhive reaches
1.0.

Also ruled out: **server-side operational transform** (the way Google Docs
works), because the server would have to read the content.

**Recommendation: Option A.**

## 4. Architecture of Option A in detail

### 4.1 One engine, one schema per type

There is one shared engine in the core, and each type adds only its schema adapter.

- **Shared engine:** transport, sealing, log, snapshots, presence, undo,
  versions, assistant change sets, offline outbox and permissions.
- **Schema adapters**, each with a parser and serialiser for the text form the
  assistant edits:
  - Document: `Y.XmlFragment` (TipTap/ProseMirror shape) ↔ `docx_model`.
  - Sheet: row and column id arrays plus a cell map, formulas stored by id ↔
    markdown table in A1 notation.
  - Deck: slide order plus a slide map with element maps; this already exists in
    `shared_items/deck*.rs` ↔ slides markup.
  - Code: one `Y.Text` ↔ file text. Line-based assistant diffs map to UTF-16
    ranges.

A separate engine per type would duplicate crypto, transport and history four
times and break the one-core rule.

### 4.2 Web editors

- The sheet and slides editors send typed operations to the core and render its
  view model. The slides editor already works this way.
- The document editor moves to TipTap, which is already a dependency, with
  `@tiptap/extension-collaboration`. Code moves to CodeMirror 6 with
  `y-codemirror.next`.
- Both use a third-party Yjs mirror on the main thread that only passes update
  bytes to the core.
  - For rich text this exception is approved.
  - For code it is a new request (question Q2).
- The `contenteditable` and textarea editors are deleted.

### 4.3 Transport, storage and compaction

- **WebSocket messages:**
  - `item_subscribe(item_id)`: the server checks access and returns the latest
    snapshot plus the log tail;
  - `item_update`: sealed bytes; the server assigns a sequence number, stores
    the update and fans it out;
  - `item_presence`: relayed only, never stored;
  - `item_snapshot(covers_seq)`;
  - typed refusals: `access_revoked`, `read_only`, `link_expired`,
    `rate_limited`, `key_epoch_stale`.
- **Precedent:** `project_task_sync_subscribe`.
- **Hot tail:** a Redis stream with fan-out across API workers, flushed in
  batches to an append-only Directus collection.
- **Compaction:** a client seals a snapshot after about 500 updates or 64 KB of
  log, or when the item closes.
  - The server drops covered log entries only after a second load succeeds.
  - Updates are debounced by 50–100 ms and merged per transaction.
- **Versions (checkpoints):** made on an assistant edit, a restore, a Project
  commit, a guest's first change, after 5 minutes idle, and at least every
  30 minutes of active editing. Each checkpoint is one `embed_diffs` row, so the
  timeline stays readable.
- **Project commits:** a commit forces a checkpoint for every changed file and
  points at those versions. Commits need no format change.
- **Saving:** the Edit button stays to enter and leave editing, but saving
  becomes automatic. An explicit Save does not fit live editing (question Q3).

### 4.4 Keys, roles and rotation

- **Item key.** The item key (today's embed key) gets an `epoch`.
  - Wrappers per epoch: Project key (Team or Personal), master key (owner) and
    share link.
  - Packets name their epoch in the AAD.
- **Member removal.** When a member is removed from a Team or Project:
  1. The server stops relaying to them at once (authorisation). This is the real
     barrier.
  2. A remaining admin's client rotates the Team key (new `team_key_epoch`) and
     re-wraps Project keys.
  3. When an item next opens, the first writer's core starts a new item-key
     epoch, seals a fresh snapshot under it and wraps it only for current members.
  4. Old log entries stay under the old epoch until compaction removes them.
- **Plain limit:** rotation protects future content. What the removed member
  already saw on their device cannot be taken back.
- **Roles:**
  - `view`: receive only;
  - `comment`: view, plus encrypted comments (phase 7);
  - `edit`: send changes.
- **Enforcement:** the server enforces roles on every packet from the membership
  or link record. It cannot read content, so it decides only on who sent the
  packet.
- **Attribution:** the server stamps each stored packet with the authenticated
  sender (account id or guest session id). Contributors per version are derived
  from those stamps.

### 4.5 Share links (R5)

**Default.** A link is view-only. The owner can switch it to `can comment` or
`can edit`, set an expiry, and revoke it at once. An edit link defaults to
7 days.

**The secret.** Each link has its own random 32-byte secret, carried in the URL
fragment and never sent to the server. Two values are derived from it:

| Derived value | Who holds it | Purpose |
|---|---|---|
| `wrap = HKDF(secret, "wrap")` | Only the client; it unwraps a `share_link` wrapper of the current item key stored on the server | Reading and writing the content |
| `auth = HKDF(secret, "auth")` | The server stores only `SHA-256(auth)` | The visitor proves they hold the link |

So the server can authorise a link without ever being able to decrypt the item.

**What changes from today:**

- Expiry, role and revocation move into a server-side link record. Today they
  are only in the client-checked blob.
- Revoking deletes the wrapper, refuses the link's sessions and starts a new
  item-key epoch.

**Signed-in outsiders** edit under their account name and get no Team access.

**Anonymous guests:**

- They pick a name, shown with a "Guest" badge and a colour.
- Each visit is a guest session bound to the link, and the session id stamps
  the guest's packets.
- The owner can remove a guest or stop all guests.

**Abuse limits** (refused with a typed error; the content stays unchanged):

- per guest: updates per second, KB per minute;
- per link: at most 20 people at once (default);
- maximum item size;
- a bot check before a guest's first edit;
- the server cannot scan encrypted content, so cleanup is a restore to an
  earlier version.

**Owner approval:** recommended no approval queue at first. A checkpoint is
saved right before each guest's first change in a visit, so the owner can go
back in one step (question Q5).

### 4.6 Assistant edits as operations (R1 and R2)

1. When the assistant reads the item, the core pins the base version and sends
   its text form for the turn. The server sees plaintext only during an
   assistant request, as in today's "encrypted until invoked" rule for Team
   chats.
2. The assistant streams a unified diff. Each finished hunk is sent to the
   requester's core.
3. The requester's core applies each hunk against the pinned base on a private
   fork with a fresh client id. It then broadcasts the minimal change set, so the
   change appears in place while the assistant is still writing. Members' edits
   made meanwhile are kept (proven in the spike).
4. All hunks of one turn are one undo step for the requester and one checkpoint
   version.
5. If the requester's device goes offline mid-turn, the remaining patched text
   waits in the existing 24-hour vault cache. The next core of that user to come
   online applies it.
6. In the plan's first phase the server-side `current_version + 1` write is
   replaced by this path.

### 4.7 Offline and conflicts

- **Outbox.** Offline changes stay in the core's encrypted outbox and merge on
  reconnect through state vectors. The user sees "N offline changes merged".
- **Same-value conflicts.** The same cell or the same element property is
  resolved by last-writer-wins, the same on every replica. The member whose value
  lost sees it replaced.
- **Stale epoch.** If the key epoch changed while the device was offline, the
  core fetches the new wrapper and re-seals its outbox.
- **Lost access.** If the user lost access while offline, nothing is uploaded.
  Their changes stay on the device and they are offered a private copy. Nothing
  is silently discarded.

### 4.8 Out of scope

- Files in a Git repository on a connected machine (remote access). The file on
  disk stays the source of truth there; these files are edited on that machine
  and are not live-shared.
- Tracked changes and suggestion mode.
- Live collaboration on diagrams, mind maps and whiteboards.

## 5. Phases (summary; details and tests in `plan.yml`)

| Phase | Outcome | Levels |
|---|---|---|
| 1 | Core shared model for all four types; documents on TipTap, code on CodeMirror; still single-user saves | foundation |
| 2 | Encrypted log, relay, snapshots, autosave and checkpoints; the same account on two devices | R3 |
| 3 | Live assistant edits as change sets for all four types; the server-side diff write is removed | R1, R2 |
| 4 | Team and Project members co-edit: presence, roles, removal, attribution in history | R4 |
| 5 | Item-key epochs and Team key rotation on removal | R4 |
| 6 | Share links with roles and expiry; signed-in outsiders, then guests with limits | R5 |
| 7 | Encrypted comments for the `comment` role; Apple editors on the core model | later |

## 6. Open questions for the owner

See `plan.yml` `open_questions`. Each one needs one decision.
