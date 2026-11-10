# Phase 0 spike: which CRDT for live documents, sheets and slides

Plan `live-collaboration-crdt`, spec `feature.live-collaboration@1` (draft).
Date 2026-11-10. Prototype: `prototype/` (standalone crate plus a Yjs script; not part
of `openmates-sdk` or any frontend package).

## Recommendation

| Topic | Choice |
|---|---|
| CRDT format | **Yjs v1 update format** |
| Rust engine (core) | **`yrs` 0.28.1** (MIT, y-crdt project; updated 2026-11-04, about 2.4 M recent downloads) |
| JS engine (main thread, view replica) | **`yjs` 13.6.33** (MIT) |
| Web binding | **Architecture (b)**: a JS Yjs replica per open item on the main thread for the editors; the Rust core in the Worker owns encryption, transport, the ciphertext log, snapshots, persistence, hydration and serialisation, assistant diffs, versions and presence encryption, and holds its own replica (also used by CLI and later Apple) |
| Doc editor toolkit | **TipTap 3** (already used: `@tiptap/*` 3.30.5 incl. `extension-table`), with `@tiptap/extension-collaboration` + `@tiptap/extension-collaboration-caret` (3.33.0, MIT; peers `yjs ^13`, `@tiptap/y-tiptap ^3.0.7`) |
| Sheets / slides | Own Svelte editors writing to the same Y.Doc schema; slide text elements reuse TipTap on a nested `Y.XmlFragment` |

This confirms the working assumption (Yjs + yrs). Loro is the better data model on
paper, but it fails the web architecture: its only JS runtime is wasm, so binding a
main-thread editor would need either main-thread wasm (forbidden: one Worker, one wasm
instance) or our own editor binding across the Worker boundary. Its wasm is also about
6 times larger.

## Evidence

Versions and licences come from crates.io and the npm registry on 2026-11-10.
Sizes were measured here.

| | yrs / yjs | Loro | Automerge |
|---|---|---|---|
| Rust crate | `yrs` 0.28.1, MIT | `loro` 1.17.1, MIT | `automerge` 0.12.0, MIT |
| JS runtime | `yjs` 13.6.33, pure JS | `loro-crdt` 1.17.1, wasm only | `@automerge/automerge` 3.5.0, wasm only |
| wasm32 probe, opt-z + LTO, engine only¹ | **333 KB raw / 130 KB gzip** | 2.19 MB raw / 768 KB gzip | not measured |
| Published npm wasm | `ywasm` 0.28.1: 1.00 MB / 343 KB gzip | `loro-crdt` web: 3.60 MB / 1.19 MB gzip | 47 MB unpacked package (several targets) |
| JS bundle on main thread | `yjs/dist/yjs.mjs` 300 KB / 63 KB gzip, unminified (minified not measured) | n/a: wasm | n/a: wasm |
| ProseMirror binding | `@tiptap/y-tiptap` 3.2.0 / `y-prosemirror` 1.3.7 (mature, used by TipTap Collaboration) | `loro-prosemirror` 0.4.4 (pre-1.0) | `@automerge/prosemirror` 0.2.0 (pre-1.0) |
| Native move in a list | no: delete + insert (see slides) | `LoroMovableList::mov`, `LoroTree::mov` | no |
| Undo | `UndoManager`: tracked origins, scope, capture timeout, `reset()` for step boundaries | `UndoManager` with `group_start/group_end` | patch-based, manual |
| History / versions | `Snapshot` needs `skip_gc`, so in practice our own encrypted snapshots | `checkout`, `fork_at`, shallow snapshots | full history kept |
| Presence | `yrs::sync::Awareness`, wire-compatible with y-protocols | ephemeral store in `loro-internal` (re-export not verified) | none built in |

¹ `prototype/wasm-size`: a cdylib using rich text with marks, map, array, undo and
update encode/apply, no wasm-bindgen. The empty baseline is 13 KB / 5.5 KB gzip, so
yrs adds about **+125 KB gzip** and Loro about **+760 KB gzip** to the core's wasm.
The current core wasm size was not measured here, so the relative increase is unknown.

Automerge was dropped early. It has the largest wasm and an immature ProseMirror
binding, and it brings no advantage over Loro for our shapes.

## 1. Data model fit

The schemas below are implemented in `prototype/src/model.rs`.

- **Document**: root `Y.XmlFragment "default"`, the shape TipTap Collaboration binds to.
  Each block (heading, paragraph, list, list item, blockquote, table, tableRow,
  tableCell, page break, image) is a `Y.XmlElement` named after the ProseMirror node,
  with node attrs as XML attributes. Text is `Y.XmlText`, and marks (bold, italic,
  underline, textStyle colour) are formatting attributes. docx_model blocks and runs
  map 1:1 onto this. Tables are nested elements, which TipTap's table extension
  already uses.
- **Sheet**: `Y.Array rows` and `Y.Array cols` of stable ids, plus `Y.Map cells` keyed by
  `"{rowId}:{colId}"` with the raw input (`"42"`, `"=SUM(B1:B3)"`). The last writer
  wins per cell. A concurrent row insert does not re-target another member's edit
  (proven). The markdown table is serialised by walking the id order.
- **Deck**: `Y.Array slide_order` of slide ids plus `Y.Map slides`. Each slide id maps to
  `{layout, notes, elements: Y.Map}`, and each element id maps to a `Y.Map` of
  last-writer-wins properties (`type`, `x`, `y`, `w`, `h`, `z`, `fill`, font and so
  on) and a `body`. In production `body` is a nested `Y.XmlFragment` so TipTap can
  edit it; the prototype uses `Y.Text`. The slides markup is one element per line,
  sorted by z then id.
- **Slide reorder without native move**: a move is delete + insert of the *id*, and
  content stays in the map. So a move never copies or loses content. Two concurrent
  moves of the same slide leave the id twice, and a delete racing a move leaves a
  dangling id. `effective_order()` resolves both the same way on every replica
  (first occurrence wins, ids without content are skipped), and the next local
  reorder cleans up. Element z-order is a numeric property, not a list position.
  This is the one place where Loro would be simpler.

## 2. Rust core fit

- **Wasm size**: about +125 KB gzip (see above). This is acceptable against the
  advisory performance gate. Loro's +760 KB is not.
- **API maturity**: yrs is pre-1.0 (0.x), so expect minor API churn between releases.
  Pin it exactly (`=0.28.1`) and upgrade deliberately. Its v1 encoding is a frozen
  wire format shared with yjs 13. Two gotchas found in the spike:
  - The default `OffsetKind` is **Bytes**; it must be **Utf16** to agree with
    Yjs/ProseMirror positions (proven with an emoji in `tests/interop.rs`).
  - On `wasm32-unknown-unknown`, `undo::Options` has no `Default` (no system clock).
    The core passes a clock closure (`Date.now()` through the host).
- **UniFFI**: CRDT types never cross the binding. Shells see view models,
  commands and opaque update bytes, so UniFFI needs nothing special. Apple native
  editors later bind the same way the web shell does, or render core view models.
- **Undo**:
  - Per user: an `UndoManager` scoped to the item's roots tracks only local
    origins, so other members' changes are never undone (proven).
  - The assistant change set is applied in one transaction with origin
    `assistant` on the requester's replica, so it is exactly one undo step. Undo
    keeps edits members made in the meantime, and the undo itself is an ordinary
    update broadcast to everyone (proven).
  - On the web, the visible undo stack is the JS `UndoManager` that y-tiptap
    creates, because undo must act on what the user sees immediately. The same
    origin rule applies there: the shell applies a core-delivered assistant update
    with an origin the JS `UndoManager` tracks. The core's `UndoManager` serves the
    CLI and Apple.
- **Update encoding and encryption**:
  - One local transaction (debounced 50–100 ms in production, merged with
    `merge_updates_v1`) becomes one v1 update and one AES-256-GCM packet
    (`prototype/src/envelope.rs`).
  - The AAD binds a format tag, the packet kind and the item id, so the server
    cannot replay a packet into another item or relabel an update as a snapshot
    (proven).
  - Packets are self-describing. Out-of-order or duplicate delivery is buffered
    or ignored by yrs (proven), so the server needs only per-item ordering for
    efficiency, not for correctness.
  - Overhead is 28 bytes per packet (nonce + tag). In production the key is the
    item's existing embed key from the current key hierarchy.
- **Compaction**:
  - A member's client periodically seals `encode_state_as_update_v1` as a
    Snapshot packet that records the log sequence it covers. The server then
    drops covered log entries.
  - A joiner loads snapshot + tail. Replaying already-covered entries is
    harmless (proven).
  - Measured: 301 single-keystroke packets = 12.9 KB of ciphertext against a
    727-byte snapshot. yrs garbage-collects deleted content by default, so
    snapshots stay small.
- **Versions**: do not use yrs `Snapshot` (it needs `skip_gc`, which grows forever).
  A named version is an encrypted full state plus its serialised text, which keeps
  today's `embed_diffs` timeline and previews working. Contributors are the
  authenticated senders of the packets between two versions. Restore = serialise
  the target version, then apply it as one change set (path 4) on top of the
  current state. It becomes a new version for everyone and never rewinds the log.

## 3. Web editor binding: (a) Rust-only document versus (b) JS view replica

**(a) Document only in the Worker.** ProseMirror transactions are synchronous, and
the Worker is async. We would have to write our own binding:
- local steps go out as messages;
- remote changes come back as ProseMirror steps;
- in-flight local steps must be rebased against remote ones on the main thread;
- positions and selections must be mapped, and IME composition handled;
- a separate collaboration caret is needed.

This amounts to rebuilding y-prosemirror plus an OT-style rebase layer in
TypeScript. It is high risk, it adds latency on every keystroke, and it puts *more*
merge-like logic in TypeScript, not less.

**(b) JS view replica (recommended).** The main thread holds one `Y.Doc` per open
item, bound with TipTap Collaboration (doc) or with our sheet and slide editors. The
shell code is only glue:
- forward each local update's bytes to the Worker;
- apply the update bytes the Worker sends;
- render the presence view model.

Everything else is in Rust:
- AES-GCM sealing and opening;
- WebSocket transport and the ciphertext log;
- offline queue and IndexedDB cache;
- snapshots and compaction;
- authorisation errors;
- hydrating from and serialising to docx_model, the markdown table and slides
  markup;
- assistant diffs, versions and restore;
- presence encryption and expiry.

**Honest weighing against "logic lives in Rust".** In (b), the CRDT merge does run in
TypeScript, but inside the third-party `yjs` library, as a second implementation of
the same frozen format. It is not hand-written OpenMates logic. Interop is proven
both ways in `tests/interop.rs`. Under the current rule wording ("never add merge
logic to TypeScript"), this is still an **exception the user should approve**.

The guardrails:
- no OpenMates TypeScript decides conflicts, policy, crypto, persistence or
  serialisation;
- the TS schema accessors for sheets and slides are a thin, contract-tested mirror
  of `model.rs`;
- structural commands with real logic (assistant diff, restore, apply template,
  formula rewrites on row and column insert) are core commands whose result
  reaches the JS replica as an update.

Memory cost: a second replica only for items that are open (documents are KB to low MB).

**Toolkit.** TipTap 3 is already a dependency (message input, workflows) and already
has tables. Collaboration is a first-party TipTap extension built on
`@tiptap/y-tiptap` (a y-prosemirror fork). Lexical has a Yjs binding but would mean
a second editor stack. Writing our own editor is out of scope. Align
`@tiptap/extension-collaboration*` with the repo's TipTap pin (3.30.5 exists for
both; latest is 3.33.0).

## 4. Assistant unified diff → minimal change set ("fork at base")

Implemented in `prototype/src/diff_apply.rs` and proven in
`tests/assistant_and_presence.rs`.

1. When the assistant reads an item, the core records the base: the version's
   encrypted full state (versions are stored anyway). The text the assistant sees
   is `serialise(base)`.
2. The assistant's unified diff is applied to that exact base text. The base is
   pinned, so tier-1 exact patching always matches it, and the fuzzy tiers become
   a fallback for model errors only.
3. The requester's core builds a private **fork** from the base state with a
   **fresh client id**. Reusing a live client id would mint duplicate item ids and
   corrupt replicas; this is documented on the function. The core then diffs base
   text against patched text:
   - block level first: Myers over blocks, merging adjacent delete/insert into
     hunks;
   - inside each paired block, character level (UTF-16 offsets);
   - extra lines become new blocks, missing lines become deleted blocks.
4. `encode_diff_v1(base_state_vector)` exports only the new ops. Their ids anchor
   to base items, so merging into the live document keeps what members typed in the
   meantime, even inside the same paragraphs.

   Proven: B typed "Team: " and " but fine" after the base was read, the assistant
   changed "March" to "April" and added a block, and both edits survived. A naive
   full replace on the same input loses B's edits (asserted). The change set was
   75 bytes.
5. The change set is sealed and broadcast. The requester applies it with origin
   `assistant`, so it is one undo step.

Production extensions:
- docx_model runs: a difference in marks only becomes `format()` calls;
- tables: recursive alignment;
- sheets: cell-wise diff of the markdown table, mapped to ids;
- slides: element-wise diff by `id`, so only changed properties are set.

Today the server applies the diff to plaintext it already has during the AI turn.
In the new design it sends the patched text (or the diff) to the requester's client,
which materialises the change set.

## 5. Presence

- `yrs::sync::Awareness` state (user name, colour, and a cursor as an encoded
  `StickyIndex` relative to content) is sealed as a `Presence` packet with the same
  key. The server relays it to connected members and never writes it.
- A sticky anchor survives concurrent edits. In the test, the cursor moved from 11
  to 17 after B inserted 6 characters before it.
- Leaving sends an explicit removal entry. `update()` omits removed clients, so the
  core uses `update_with_clients([self])`, which mirrors y-protocols
  `removeAwarenessStates`. The core also expires peers after about 30 s without a
  heartbeat.
- On the web, the shell feeds the decoded states into a y-protocols `Awareness`
  object for TipTap's caret extension. The formats are wire-compatible, but this was
  **not tested in the spike**.
- Sheets and slides publish `{cell}` or `{slide, element}` instead of a text anchor.

## Top risks

1. **Rule exception for the JS replica (architecture b).** It needs user approval
   and a guard so that no hand-written merge or policy code creeps into the shell.
   There is also drift risk between `model.rs` and the TS schema accessors.
   Mitigation: a contract test like `tests/interop.rs` in CI.
2. **Structural semantics outside the CRDT.**
   - Sheet formulas reference A1 positions, so a concurrent row or column insert
     can make a formula point at the wrong cell. Proposal: store formulas
     internally in id form (`=SUM({r1:c2}:{r3:c2})`) and render A1 only for display
     and serialisation.
   - Slide reorder has no native move. The dedupe rule works but must be applied
     everywhere the order is read.
3. **Assistant change depends on the requester's client and the base state.**
   - The change set is materialised by the requester's core. If that device goes
     offline mid-turn, another member's core must do it, and then the undo step
     belongs to nobody.
   - Docx_model mark and table diffs are more complex than the plain-text lines
     proven here.
   - yrs is pre-1.0; pin and upgrade deliberately.

Also noted: snapshots are made by clients and the server cannot validate them. Keep
the previous snapshot and log until a second client has loaded the new one without
error.

## What the prototype proves and does not

Proven (7 tests green through `heavy_slot`, `cargo test` in `prototype/`):
- two replicas edit a doc paragraph, the same sheet cell, a concurrent row insert,
  the same slide-element property plus a different property, and concurrent slide
  moves;
- they exchange individually AES-GCM-sealed updates out of order and twice, and
  converge to identical text and state vectors;
- one value wins for the same cell or property, and different properties are both
  kept;
- tampered, relabelled and cross-item packets are refused;
- snapshot + tail rebuilds the state;
- the assistant diff merges as a minimal change set that keeps concurrent edits,
  and a naive replace does not;
- the assistant change is exactly one undo step and keeps other members' edits;
- encrypted presence with a sticky cursor works, and so does leaving;
- yrs ↔ Yjs 13 interop both ways, including UTF-16 offsets and formatting
  attributes;
- wasm size for yrs and Loro.

Not proven:
- TipTap / y-tiptap bound to a Worker-fed replica in a browser;
- the y-protocols Awareness bridge;
- real docx_model, markdown and slides-markup serialisers (the prototype uses
  simplified stand-ins);
- mark and table diffs;
- performance on large documents and wasm init time;
- the current core wasm baseline;
- server log, snapshot and authorisation behaviour;
- multi-device offline at scale;
- Loro beyond size and API presence.

## Running the prototype

```bash
cd docs/plans/live-collaboration-crdt/prototype/js && npm install --ignore-scripts   # yjs only, isolated
cd ../../../../..
CARGO_TARGET_DIR=/tmp/om-crdt-spike-target python3 scripts/heavy_slot.py run -- \
  cargo test --manifest-path docs/plans/live-collaboration-crdt/prototype/Cargo.toml -- --nocapture
# wasm size probe: --features none|yrs|loro
CARGO_TARGET_DIR=/tmp/om-crdt-wasm RUSTFLAGS='--cfg getrandom_backend="wasm_js"' python3 scripts/heavy_slot.py run -- \
  cargo build --release --target wasm32-unknown-unknown \
  --manifest-path docs/plans/live-collaboration-crdt/prototype/wasm-size/Cargo.toml --features yrs
```

## Decisions needed from the user

1. Approve architecture (b): the third-party Yjs replica on the main thread as an
   exception to "no merge logic in TypeScript", with policy staying in Rust.
   Recommendation: yes.
2. Approve id-based formula storage for sheets. It changes how formulas are stored
   inside the shared model, while the markdown table the assistant edits stays A1.
   Recommendation: yes.

## Decision recorded 2026-11-10

Decision 1 was narrowed by the user because Apple support follows and editing
logic must not be written twice. The Rust core (yrs) holds the authoritative
replica of every open item. Sheets and slides editors send typed operations to
the core ("set cell", "move element") and render its view model; the TypeScript
schema accessors proposed in section 3 are not built. A JS Yjs mirror on the main
thread exists only for rich-text typing (document editor, slide text boxes) and
only exchanges update bytes with the core. Apple calls the core directly and
needs no mirror. Unproven: typing latency of the mirror-to-core loop in a browser.
Decision 2 (id-based formulas) is adopted as the default.
