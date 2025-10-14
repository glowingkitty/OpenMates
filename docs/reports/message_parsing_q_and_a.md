## Unified Markdown Parsing — Top 10 Questions

1) Node model: Use one generic `embed` node with `EmbedNodeAttrs`, or retrofit existing nodes (`codeEmbed`, `webEmbed`, `videoEmbed`, etc.) to carry minimal attrs (`id`, `type`, `status`, `contentRef`, `contentHash?`, tiny metadata)?
> Answer: Use a unified `embed` node, since the nodes share huge parts of their attributes and design.

2) Content addressing: After generation finishes, always re-key `contentRef` to `cid:sha256:<hash>` and set `contentHash=<hash>`; never persist `stream:*` in stored messages — confirm.
> Explanation (simpler): While the AI is still generating an embed, we point the node to a temporary key like `contentRef="stream:<messageId>:<embedIndex>"`. When the embed is finished, we compute the SHA‑256 of the full content and store it under a permanent key like `contentRef="cid:sha256:<hash>"` and set `contentHash` to that same `<hash>`. We then update the node to use the permanent `cid:*` and set `status = "finished"`. We never save the temporary `stream:*` to the database — it only exists in memory during generation.
> Example:
> - During generation: `contentRef = "stream:abc123:0"`, `status = "processing"`
> - After finish: compute hash → `contentRef = "cid:sha256:8f14e45fce..."`, `contentHash = "8f14e45fce..."`, `status = "finished"`
> Answer: yes, sounds reasonable.

3) Streaming updates: Call `parse_message()` on every AI chunk with full text-so-far, and render highlighted-but-unclosed blocks until they close; finalize nodes + re-key on the last chunk — confirm.
> Answer: we should use parse_message() every time we receive the updated message from the server - meaning, every time we receive a new paragraph chunk.

4) Embed IDs: Define stable `id` for streaming embeds. Is `messageId:embedIndex` required, and if earlier text inserts new embeds, should we recompute indices and update IDs for all later embeds?
> Explanation (simpler): Each embed has an `id` so we can update it reliably during streaming. One simple scheme is `id = <messageId>:<embedIndex>`, where the first embed is index 0, second is 1, etc. The problem: if the AI later inserts a new embed earlier in the message, all later indices shift (what was index 2 becomes index 3). The question is whether we should (a) recompute and update IDs for all later embeds when order changes, or (b) choose an ID that never changes (e.g., a random UUID or a temporary streaming ID that we keep stable and later map to final). We need to pick one behavior so updates remain consistent.
> Answer: never use counter-based IDs, use a random UUID instead.

5) Path-or-Title rules (MVP):
   - Code: support fences ````<lang>[:<relative/path>]` (allow subfolders and dots; trim spaces)
   - Docs: only `document_html` with required first line `<!-- title: "..." -->`
   - Tables: require blank line before/after; title from preceding comment `<!-- title: "..." -->`
   Confirm exactly these acceptance rules for v1.
> Answer: Code blocks can be be fenced with ```<lang>[:<relative/path>]``` (but not defining the path or language is also allowed, even while not recommended). The title for docs and tables are also optional (but recommended).

6) URL and YouTube handling: Move URL detection fully into `parse_message()` and treat YouTube as Video (not Web). On failure to resolve meta, fallback behavior: keep as link or keep a pending preview?
> Answer: 'Website' and 'Web videos' (youtube) detection should indeed be handled in `parse_message()`. If website loading of metadata fails, render still as website node, but with url as title (and main domain color highlighted), and for youtube videos we use the video node, but with url as title. In both cases the url is shortened to a max length of course.

7) Backspace reversion (edit UX): When reverting an embed in the editor, should we restore the canonical markdown (including path-or-title line) for all types (code, table, document, web/video)?
> Answer: yes, we should restore the canonical markdown (including path-or-title line) for all types (code, table, document, web/video), so the user can see the original content and modify it.

8) Clipboard canon: On copy, write both canonical fenced markdown and `application/x-openmates-embed+json` with inline content; on paste, prefer JSON to ensure `ContentStore.ensure(cid, inline)` before inserting a lightweight node — confirm JSON schema and `version`.
> Explanation (simpler): When the user copies a preview, we put two things on the system clipboard:
> - `text/plain` and `text/markdown`: the canonical fenced markdown for use in any app.
> - `application/x-openmates-embed+json`: a small JSON payload with type, filename/language (if any), `contentRef` (e.g., `cid:*`), `contentHash`, and optional `inlineContent` so OpenMates can reconstruct locally without re-downloading.
> On paste inside OpenMates, we first look for that JSON. If present, we call `ContentStore.ensure(contentRef, inlineContent)` to make sure the full content exists locally, then we insert a lightweight embed node. If the JSON is missing, we fall back to parsing the markdown text.
> Example JSON:
> ```json
> {
>   "version": 1,
>   "id": "m123:0",
>   "type": "code",
>   "language": "python",
>   "filename": "stripe_payment_processor.py",
>   "contentRef": "cid:sha256:8f14e45fce...",
>   "contentHash": "8f14e45fce...",
>   "inlineContent": "def foo():\n  return 1\n"
> }
> ```
> Answer: sounds like a reasonable approach.

9) Storage/migration: Switch to encrypted markdown storage for new messages now, and lazily migrate existing TipTap JSON on load by serializing to canonical markdown and rewriting nodes to minimal attrs — acceptable?
> Answer: implement encrypted markdown storage of original assistant responses and user messages, and also consider the implementation of a migration script in the frontend to migrate existing chats to the new structure (see how compliated it would be to implement, before deciding if it's worth it). 

10) Integration points (initial refactor scope): Replace `preprocessTiptapJsonForEmbeds` and `detectAndReplaceUrls()` with the unified `parse_message()` in both write_mode and read_mode; keep current Svelte embed components but retrofit their attrs to the minimal spec — confirm.
> Answer: as I said, we should replace existing parsing functions with the unified `parse_message()` in both write_mode and read_mode.