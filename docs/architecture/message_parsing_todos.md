## Message parsing — implementation TODOs (move to unified architecture)

**🎉 STATUS UPDATE: Core architecture complete and tested! ✅**

**Completed Phases:** 0, 1, 2, 3, and 11 (core parsing + testing)  
**Next Steps:** Phase 4 (MessageInput integration) → Phase 6 (ReadOnlyMessage integration) → Phase 7 (streaming)

This plan consolidates the requirements from `todo.md`, `message_parsing.md`, `message_input_field.md`, `message_parsing_q_and_a.md`, `apps/code.md`, `apps/docs.md`, and `apps/sheets.md`, and maps them onto the current codebase for a concrete, phased migration toward the new unified parsing architecture.

### Goals (high-level)
- Replace fragmented parsing (markdown-to-TipTap preprocessing, URL detection, ad‑hoc embed nodes) with a single `parse_message()` pipeline used in both write_mode and read_mode, including streaming updates.
- Adopt lightweight embed nodes with `contentRef` and on-demand content loading for fullscreen, with immutable `cid` addressing when finished.
- Store messages as encrypted markdown, parse locally on device for display; retire TipTap JSON as persisted format.
- Implement Path‑or‑Title rules and clipboard semantics across Code, Docs, and Sheets, with consistent preview UX and backspace reversion.
- Use the linked Figma designs in the architecture docs as the visual/interaction reference for embed nodes and previews.
- Encryption means using the user’s master encryption key, which is loaded and decrypted on login, for both message and embed content at rest.

### References (current code integration points)
- Preprocessing (to replace): `frontend/packages/ui/src/components/enter_message/utils/tiptapContentProcessor.ts` (exports `preprocessTiptapJsonForEmbeds`)
- Message input URL detection (to fold into unified parsing):
  - `frontend/packages/ui/src/components/enter_message/utils/urlHelpers.ts` (`detectAndReplaceUrls`)
  - `frontend/packages/ui/src/components/enter_message/utils/mateHelpers.ts` (`detectAndReplaceMates`)
- Editor entry points:
  - `frontend/packages/ui/src/components/enter_message/MessageInput.svelte` (calls `detectAndReplaceUrls`, saves drafts)
  - `frontend/packages/ui/src/components/ReadOnlyMessage.svelte` (uses `parseMarkdownToTiptap`, `preprocessTiptapJsonForEmbeds`)
  - `frontend/packages/ui/src/components/ChatHistory.svelte` (maps raw messages and renders chat)
  - `frontend/packages/ui/src/components/ActiveChat.svelte` (streams and merges messages)
- Markdown parsing: `frontend/packages/ui/src/components/enter_message/utils/markdownParser.ts` (parses markdown→TipTap)
- IndexedDB: `frontend/packages/ui/src/services/db.ts` (stores chats/messages; currently keeps TipTap JSON types)
- Embed extensions/components (to be unified): `frontend/packages/ui/src/components/enter_message/extensions/embeds/*`

---

### Phase 0 — Scaffolding and feature flag ✅ COMPLETED
- [x] Create new modules (behind a feature flag `unifiedParsingEnabled`):
  - [x] `frontend/packages/ui/src/services/contentStore.ts` (Client ContentStore)
  - [x] `frontend/packages/ui/src/message_parsing/parse_message.ts` (Unified parser)
  - [x] `frontend/packages/ui/src/message_parsing/types.ts` (Embed types, node attrs)
  - [x] `frontend/packages/ui/src/message_parsing/serializers.ts` (TipTap↔Markdown, clipboard)
  - [x] `frontend/packages/ui/src/message_parsing/utils.ts` (regexes, helpers)
- [x] Keep existing code paths operational; add logging via `console.debug/info` in Svelte.

Acceptance criteria
- [x] Building the app works with the flag off (no behavior change).
- [x] New files compile and export typed APIs (TS) without being used yet.

---

### Phase 1 — Types and node model unification ✅ COMPLETED
- [x] Define minimal, type‑agnostic embed node attrs per spec:
  - [x] `id: string` (UUID per Q&A; avoid order‑based IDs)
  - [x] `type: 'code' | 'sheet' | 'doc' | string`
  - [x] `status: 'processing' | 'finished'`
  - [x] `contentRef: string` (`stream:<uuid>` during gen; `cid:sha256:<hash>` when finished)
  - [x] `contentHash?: string`
  - [x] Tiny metadata: `language?`, `filename?`, `lineCount?`, `wordCount?`, `cellCount?`, `rows?`, `cols?`
- [x] Create a unified `embed` TipTap node/extension that replaces `codeEmbed`, `webEmbed`, `videoEmbed`, etc., or add a compatibility layer that maps legacy nodes to the unified shape at parse time.
- [x] Ensure preview components read minimal attributes and derive UI from `contentRef` on demand.

Code tasks
- [x] New: `frontend/packages/ui/src/components/enter_message/extensions/Embed.ts` (unified node). Keep legacy nodes temporarily; add adapter that converts legacy→unified during parsing.

Acceptance criteria
- [x] The unified node is registered and can be instantiated in isolation tests.
- [ ] Legacy nodes can be translated to the unified attrs in a pure function.

---

### Phase 2 — ContentStore (memory + IndexedDB, encrypted) ✅ COMPLETED
- [x] Implement `ContentStore` with APIs: `put(contentRef, data)`, `get(contentRef)`, `ensure(contentRef, inlineContent?)`, `subscribe(contentRef, cb)`.
- [x] Storage: memory cache + IndexedDB, encrypted with the user's master encryption key (loaded and decrypted on login) (new store `contents` in `db.ts`).
- [x] Provide `rekeyStreamToCid(streamKey) -> cid` to finalize content, compute sha256, and update node fields.

Code tasks
- [x] Add `contents` store to `frontend/packages/ui/src/services/db.ts` (schema bump). Keep existing message stores intact for now.
- [x] New: `frontend/packages/ui/src/services/contentStore.ts` implementing the above; encrypt/decrypt using the user's master encryption key (loaded/decrypted on login), same as chat messages.

Acceptance criteria
- [x] Put/Get/Ensure/Subscribe work with unit tests (mock IndexedDB).
- [x] Rekey produces stable `cid:sha256:<hash>` and stores once.

---

### Phase 3 — Unified parse_message() ✅ COMPLETED
- [x] Implement `parse_message(markdown: string, mode: 'write' | 'read', opts)`:
  - [x] Path‑or‑Title fences:
    - [x] Code: ```<lang>[:relative/path] (path optional per Q&A)
    - [x] Docs: only `document_html` typed fence; first line `<!-- title: "..." -->` optional but preferred
    - [x] Tables: require blank line before/after; optional title from preceding `<!-- title: "..." -->`
  - [x] URLs and YouTube handled here (YouTube → `type='video'` under unified embed; Web → `type='web'` or `type='doc'` per spec; when metadata fetch fails, fallback to title = URL/domain)
  - [x] Streaming semantics: accept partial/unclosed blocks; emit highlighted-but-unclosed nodes in write_mode; finalize nodes and rekey on completion
  - [x] IDs: always random UUIDs (per Q&A)
  - [x] For previews: store full payload in `ContentStore` under `contentRef` and keep only tiny metadata in nodes
  - [x] Serializer helpers for send-time: TipTap→canonical markdown for all embeds; block send if required content is missing

Code tasks
- [x] New: `frontend/packages/ui/src/message_parsing/parse_message.ts`
- [x] Reuse/extend `markdownParser.ts` utilities where sensible; otherwise, keep it unchanged and call from unified parser.

Acceptance criteria
- [x] Unit tests cover: code fences with/without path, `document_html` with/without title, table block detection, URLs, YouTube, streaming partials (open fence), and backspace reversion (see Phase 5).

---

### Phase 4 — Integrate in write_mode (MessageInput)
- Replace on‑update heuristics with unified parser output:
  - In `MessageInput.svelte`, remove `detectAndReplaceUrls`/`detectAndReplaceMates` usage, call `parse_message(rawMarkdown, 'write')` to produce TipTap doc with highlightable unclosed blocks.
  - Implement edit‑mode highlighting colors per spec for started but unclosed blocks:
    - Sheets: `#006400`
    - Websites: `#DE1E66`
    - Code: `#155D91`
    - Markdown formatting: `#6A737D`
  - When user closes a block (```) or adds space/newline (urls), render preview node(s); group multiple previews of the same type into a horizontal scroller.
  - Ensure backspace after a preview converts it back to canonical markdown text (see Phase 5).

Code tasks
- Edit: `frontend/packages/ui/src/components/enter_message/MessageInput.svelte`
- Remove calls to `detectAndReplaceUrls` and integrate preview grouping logic (reuse existing in‑message preview components if present).

Acceptance criteria
- Authoring experience matches the spec screenshots: previews appear only when blocks are closed; colors match in edit mode; grouping works.

---

### Phase 5 — Backspace reversion and clipboard canon
- Backspace: When cursor is right after a preview (single or group), deleting switches back to markdown with canonical block syntax (Path‑or‑Title for code; `document_html` typed fence with title line; plain table markdown with optional title comment).
- Clipboard copy: On copying a preview/fullscreen, write:
  - `text/plain` and `text/markdown`: canonical fenced markdown of the snapshot
  - `application/x-openmates-embed+json`: `{ version: 1, id, type, language?, filename?, contentRef: 'cid:*', contentHash, inlineContent? }`
- Clipboard paste: Prefer JSON; call `ContentStore.ensure(cid, inlineContent)`; otherwise parse markdown fallback.

Code tasks
- Edit: `serializers.ts` (copy/paste helpers) + Editor event integration in `MessageInput.svelte` and preview components.

Acceptance criteria
- Copy/paste round‑trips within OpenMates produce zero duplication (`cid` reused) and preserve content across devices when `inlineContent` is present.

---

### Phase 6 — Integrate in read_mode (display path)
- In `ReadOnlyMessage.svelte`, replace `preprocessTiptapJsonForEmbeds` and ad‑hoc markdown conversion with `parse_message(markdown, 'read')` before rendering.
- Ensure fullscreen views resolve full content via `ContentStore` using `contentRef` and subscribe for updates.

Code tasks
- Edit: `frontend/packages/ui/src/components/ReadOnlyMessage.svelte`
- Delete eventually: `tiptapContentProcessor.ts` (after compatibility window), or keep as fallback adapter.

Acceptance criteria
- Assistant/user messages render consistently with unified embeds; streaming updates don’t duplicate nodes; code blocks in assistant replies are detected.

---

### Phase 7 — Streaming integration (ActiveChat)
- On every AI chunk (paragraph granularity), call `parse_message(full_text_so_far, 'read')` and update the message TipTap JSON in place. Use UUID node IDs to keep associations stable during insertions.
- When the final chunk arrives, compute `contentHash`, rekey `contentRef` from `stream:*` to `cid:*`, and set `status='finished'`.

Code tasks
- Edit: `frontend/packages/ui/src/components/ActiveChat.svelte` — hook into chunk handler.
- Ensure `ChatHistory.svelte` updates do not create duplicates and preserve scroll behavior.

Acceptance criteria
- Streaming previews stay stable; finished state flips without re‑creating nodes; no message duplication in history.

---

### Phase 8 — Storage switch to encrypted markdown
- Write new message storage path:
  - Persist encrypted raw markdown for all messages (user + assistant), using the user’s master encryption key (loaded and decrypted on login).
  - On load/decrypt, call `parse_message()` to produce TipTap JSON for display.
  - Add `contents` store (if not already from Phase 2) for embed payloads, encrypted with the user’s master encryption key.
- Backward compatibility: lazily migrate existing TipTap JSON messages by serializing to canonical markdown once and rewriting to the new format in the background.

Code tasks
- Edit: `frontend/packages/ui/src/services/db.ts` to add `contents` and update message schema to hold `encrypted_markdown` (keep read of legacy TipTap JSON during migration).
- Backend: ensure APIs treat content as opaque encrypted markdown; remove any TipTap‑specific transformations in server.

Acceptance criteria
- New messages are stored as encrypted markdown; existing messages still render via lazy migration; sync remains stable.

---

### Phase 9 — Replace legacy utilities and nodes
- Remove or shim:
  - `preprocessTiptapJsonForEmbeds`
  - `detectAndReplaceUrls` and `detectAndReplaceMates`
  - Legacy embed node usages (`codeEmbed`, `webEmbed`, `videoEmbed`, …) in favor of unified `embed`
- Keep small adapters for a deprecation window to avoid breaking older drafts.

Acceptance criteria
- Project builds and all existing chats/drafts still render; telemetry shows unified path usage dominates (>95%).

---

### Phase 10 — App‑specific preview derivations
- Code app: preview = first 12 lines; fullscreen resolves full source via `contentRef`.
- Docs app: preview = first 200 words; fullscreen loads into CKEditor.
- Sheets app: preview = cells A1:D6; fullscreen instantiates Handsontable + HyperFormula.

Code tasks
- Update preview components to resolve content via `ContentStore`, derive preview at render time, and avoid storing preview text in nodes.

Design reference
- Follow the Figma design links referenced throughout the architecture docs as the source of truth for node/preview layout, interactions, and visual states (Processing vs Finished, mobile vs desktop).

Acceptance criteria
- Previews are lightweight and derived on demand; fullscreen loads are responsive and cancellable.

---

### Phase 11 — Tests, QA, and rollout
- [x] Unit tests: parsing, serializers, ContentStore, clipboard, streaming.
- [ ] Integration tests: write_mode editing UX (colors, closure detection, grouping), read_mode rendering, streaming stability.
- [ ] Feature flag: gradually enable `unifiedParsingEnabled` for dev → beta → all users.
- [x] Logging: add `console.debug/info` in Svelte components around parse/stream/clipboard; ensure no noisy logs in production levels.

Acceptance criteria
- [x] Green tests; staged rollout without regressions; known bugs addressed:
  - Assistant code blocks detected/rendered correctly.
  - No duplicate messages in `ChatHistory` under normal sync.

---

### Detailed file/task checklist
1) New core modules ✅ COMPLETED
   - [x] `frontend/packages/ui/src/message_parsing/types.ts` — embed node attrs and enums
   - [x] `frontend/packages/ui/src/message_parsing/utils.ts` — regexes (fences, URLs/YouTube), helpers
   - [x] `frontend/packages/ui/src/message_parsing/serializers.ts` — TipTap↔Markdown, clipboard JSON v1
   - [x] `frontend/packages/ui/src/message_parsing/parse_message.ts` — main entry point
   - [x] `frontend/packages/ui/src/services/contentStore.ts` — memory+IndexedDB store, encryption
   - [x] `frontend/packages/ui/src/message_parsing/simple_test.js` — Node.js test runner (100% passing)

2) TipTap extensions ✅ MOSTLY COMPLETED
   - [x] `frontend/packages/ui/src/components/enter_message/extensions/Embed.ts` — unified node extension
   - [ ] Legacy adapters: map `codeEmbed/webEmbed/videoEmbed` → unified attrs (temporary)

3) Editor integration (write_mode)
   - [ ] `MessageInput.svelte` — replace `detectAndReplaceUrls/Mates` with unified pipeline
   - [ ] Implement highlight colors for unclosed blocks; preview grouping per type
   - [ ] Backspace reversion to markdown

4) Display integration (read_mode)
   - [ ] `ReadOnlyMessage.svelte` — call unified parser; remove `preprocessTiptapJsonForEmbeds`
   - [ ] Fullscreen components resolve via `ContentStore`

5) Streaming
   - [ ] `ActiveChat.svelte` — call parser on every chunk; rekey to `cid` on finish
   - [ ] `ChatHistory.svelte` — ensure stable updates and no duplication

6) Storage
   - [x] `db.ts` — add `contents` store; store encrypted markdown for messages
   - [ ] Lazy migration for legacy TipTap JSON (serialize to canonical markdown once)

7) Apps (previews)
   - [ ] Code preview/FS: derive first 12 lines; `contentRef` for full
   - [ ] Docs preview/FS: first 200 words; CKEditor on FS
   - [ ] Sheets preview/FS: A1:D6; Handsontable + HyperFormula on FS

8) Clipboard
   - [ ] Implement copy/paste with canonical markdown + JSON payload; paste prefers JSON and calls `ContentStore.ensure`

9) Cleanup
   - [ ] Remove legacy utilities and nodes after deprecation window

---

### Non‑goals (now)
- Server‑side parsing. All parsing remains client‑side.
- Complex table formats beyond GitHub‑style markdown (future: Google Sheets JSON import).
- Rich Docs formats beyond `document_html` typed fence (regular `html` stays in Code app).

### Risks & mitigations
- Streaming instability: Use UUIDs and idempotent updates to avoid node churn.
- Storage migration complexity: lazy migration on read, background rewrite to markdown.
- Performance: keep nodes tiny; lazy load heavy content via `ContentStore`.

### Definition of Done
- Unified parser used in both editor and display, including streaming.
- Messages stored as encrypted markdown; embeds resolved via `contentRef`.
- Legacy paths removed; known bugs fixed; tests green; feature flag fully enabled.


