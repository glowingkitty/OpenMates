# Message parsing architecture

## Current implementation

The UI performs all message parsing on the client side through a coordinated pipeline:

1. **User input** – `MessageInput.svelte` converts the raw markdown draft entered by the user into a minimal TipTap JSON document.
2. **Incoming messages** – `ActiveChat.svelte` receives messages from the server (both user‑sent and assistant‑generated) via `chatSyncService`. It forwards the raw `Message` objects to `ChatHistory.svelte`.
3. **Mapping & preprocessing** – `ChatHistory` maps each `Message` to an internal representation and runs `preprocessTiptapJsonForEmbeds` (found in `frontend/packages/ui/src/components/enter_message/utils/tiptapContentProcessor.ts`).  
   - The processor traverses the TipTap document, uses regular expressions to detect markdown code blocks and standalone URLs, and replaces those text fragments with embed nodes (`codeEmbed`, `webEmbed`).  
   - It also normalises the document structure so that later rendering components can rely on a consistent shape.
4. **Rendering** – `ChatMessage.svelte` receives the processed TipTap JSON and renders it in read‑only mode, displaying code blocks, link previews, and other embeds.  
5. **Streaming AI replies** – For assistant messages streamed via `aiMessageChunk`, each chunk updates the same TipTap document (status = `streaming`) and the UI re‑renders the partial content in place until the final chunk marks the message as `synced`.

This pipeline ensures that both drafts and received messages undergo the same parsing logic, providing consistent embed handling and preview generation across the application.

### Current known bugs

- while pasting a code block renders it correctly, code blocks in assistant response are not detected/rendered correctly
- sync or rendering is buggy: sometimes we see messages duplicated in chathistory (assumption: server or client doesn't recognize that we already have the messages and therefore adds them), also when messages are send from one device, other logged in device at the time receives only responses and not user messages


## Planned new architecture

### Limit max default visible message length from user

- shorten long user messages in the read only chat history and show a “Show full” button at the bottom end of the message (use line-clamp css to define max number of lines, in combination with function to detect if messages is shortened based on height/scroll height)


### What we parse

#### Long pasted messages

- auto detect long text blocks and paste in messageinput field as markdown code block (as regular markdown text, see [apps/code.md#embedded-previews](apps/code.md#embedded-previews)) or docs (see [apps/docs.md#embedded-previews](apps/docs.md#embedded-previews))

#### Code blocks

- code blocks starting with ``` and ending with ``` -> to Code embedded previews, with auto detected code language, see [apps/code.md#embedded-previews](apps/code.md#embedded-previews)

#### Tables

- tables (with empty line before and empty line after table structure) -> to Sheet embedded previews, see [apps/sheets.md#embedded-previews](apps/sheets.md#embedded-previews)
  - Plain markdown tables are auto-detected without needing a typed fence
  - To attach a title, place an HTML comment with a quoted title immediately above the table: `<!-- title: "Your Title" -->`

#### File paths and titles (Path or Title standard)

We adopt a minimalist rule for all generated or pasted blocks: either provide a file path for code/files, or a title for documents/notes/tables — nothing else.

- Code or files-to-save must include a path in the code fence:

  ````
  ```<language>:<relative/path/to/file.ext>
  <content>
  ```
  ````

- Documents (rich text) without a file path must include a title as the first line inside a typed fence:

  ````
  ```<type>_<format>
  <!-- title: "Descriptive Name" -->
  <content>
  ```
  ````

  - Allowed `<type>_<format>`: `document_html` (Docs app). Regular `html` remains Code app.
  - Only `title` metadata is allowed, on the first line inside the block
  - Never mix both path and title in the same block (if both are present, the path is used)
  - Tables: plain markdown tables are parsed; titles are taken from a preceding HTML comment `<!-- title: "..." -->` (if present. Else 'Table' is used as title)

#### Pasted content

- use html that is copied to clipboard to detect content / source
	- code copied from vscode -> Code app preview
	- text copied from Google docs -> Docs app preview

#### Tool calls (Skills used, Focus modes activated / deactivated, app settings & memories requested)

- always a json code block with details
- skill use (request_id, app name, skill name, input, output) is added as yml code block in assistant response
- how to handle processing times from ms to seconds or even minutes:
   - once function call is generated, we add json code block to assistant response inline and render it accordingly (with "Processing..." status)
	- we wait for app skill celery tasks to finish and then return output back to LLM for interpreting. If processing not finished after 5 seconds, we return “The processing takes a bit longer. I let you know once it’s finished.
	- for app skills that are known to take longer (generate images or videos, search for doctor appointments, etc.) we directly return “I let you know once I finished.” And send follow up message with results as json code block once results are finished.

##### Skill example

```json
{
   "app":"Web", "skill":"Search", "requests":[
   {"id":"93a8da", "query":"egg price increase in US since 2023", "output":[(dict for each web page with id, title, url, description, snippets)]},
   {"id":"7ch231", "query":"who is profiting from egg price increase in US", "output":[(dict for each web page with id, title, url, description, snippets)]}
   ]
}
```

##### Focus mode example

```json
{"app":"Jobs", "focus":"Career advice", "change":"activated"}
```

##### App settings & memories request

```json
{"requested":[{"app":"Code", "settings_and_memories":["Favorite languages & frameworks", "Current projects"]}]}
```

### Unified parsing function

- one "parse_message()" function for both parsing message_inputfield in active chat, as well as sent messages from user and assistant
- gets executed every time we receive a new chunk of an assistant response or if we load a message from the indexeddb after decrypting it
- also needs to consider that every embedded preview can open a full screen view and must be able to give the full screen view the content (we open a new full screen view overlay while leaving the existing rendered embedded preview unchanged, to not cause transitioning animation issues in the DOM)

#### Lightweight embeds with contentRef and on-demand content loading

To keep TipTap documents small and rendering fast, embeds store only lightweight metadata plus a stable pointer to the heavy content. Full content is stored client-side (memory + encrypted using master encryption key in IndexedDB (see [security.md](security.md))) and loaded & decrypted on demand for fullscreen views.

- TipTap node attributes (lightweight, no persisted preview text):
    - `id` (stable identity like `messageId:embedIndex`)
    - `type` (`code`, `sheet`, `doc`, …)
    - `status` (`processing` | `finished`)
    - `contentRef` (stable key to resolve full content from the client store)
    - `contentHash?` (sha256 of full content once finished; used for cache/immutability)
    - minimal, stable metadata (e.g., `language`, `filename`, `lineCount` / `cellCount` / `wordCount`, `rows`, `cols`)
    - Preview UI is derived from the current content resolved via `contentRef` and never persisted in the node (an in-memory cache keyed by `contentHash` may be used).
- Client ContentStore:
    - Provides `put/get/ensure/subscribe` to manage content in memory and IndexedDB (stored encrypted using master encryption key, see [security.md](security.md))
    - Keys can be content-addressable (e.g., `cid:sha256:...`) or temporary stream keys (`stream:<messageId>:<embedIndex>`) during generation
    - Fullscreen components resolve `contentRef` via the store and subscribe for streaming updates
- Streaming semantics:
    - During streaming, embeds point to `stream:*` keys; once finished, content is re-keyed to a stable `cid` and the node updates `status=finished` and `contentRef=cid`
- Rehydration:
    - On reload, if `cid` is missing locally, fullscreen provides a deterministic loader (reconstruct from message markdown/table, or fetch by `messageId, embedIndex` if available)

##### Preview content policy (per type)

- Code: preview renders only the first 12 lines (derived at render-time). Full source is stored under `contentRef` and loaded in fullscreen.
- Sheet: preview renders only cells A1 to D6 (derived). Full sheet is stored under `contentRef` and initialized in fullscreen (Handsontable + HyperFormula).
- Docs (generic text): preview shows the first 200 words (derived). Full text is stored under `contentRef` and loaded in fullscreen.
- Future types: follow the same pattern — keep only small, stable metadata in the node and offload full payloads to the store via `contentRef`. Use an in-memory cache keyed by `contentHash` to avoid recomputing previews.

```ts
// Minimal, type-agnostic node attributes (example)
export type EmbedStatus = 'processing' | 'finished';
export type EmbedType = 'code' | 'sheet' | 'doc' | string; // extensible

export interface EmbedNodeAttrs {
    id: string;              // messageId:embedIndex
    type: EmbedType;         // e.g., 'code' | 'sheet' | 'doc'
    status: EmbedStatus;     // 'processing' | 'finished'
    contentRef: string;      // e.g., 'cid:sha256:…' or 'stream:<messageId>:<embedIndex>'
    contentHash?: string;    // sha256 of full content once finished (immutable snapshot id)
    // Optional, tiny preview metadata (do not persist preview text)
    filename?: string;
    language?: string;
    lineCount?: number;      // code
    wordCount?: number;      // docs
    cellCount?: number;      // sheets
    rows?: number;           // sheets
    cols?: number;           // sheets
}
```

##### Path-or-Title parsing details

- Code fences with path:
  - Fence pattern: ^```([a-zA-Z0-9_+\-]+):([^`\n]+)$ captures `language` and `relativePath` (remove path if the path starts with a URL scheme like `://`).
  - Node mapping: `type='code'`, `language`, `filename=relativePath`, `lineCount` computed. Preview is derived on render.

- Typed fences with title:
  - Fence pattern: ^```([a-zA-Z0-9]+_[a-zA-Z0-9]+)$ captures `type_format` (currently: `document_html`).
  - First line must match an HTML comment title with quotes (required): `<!-- title: "Your Title" -->`
  - Parsing rules: read the quoted title, trim whitespace, and reject any other metadata keys.
  - Node mapping:
    - `document_html` → `type='doc'`, `wordCount` computed. Preview is derived on render.
  - Special-case note: `document_html` is reserved to represent rich documents parsed by the Docs app. Regular `html` code fences are treated as Code embeds and rendered by the Code app, not Docs.

- Content addressing:
  - During generation/streaming, assign `contentRef='stream:<messageId>:<embedIndex>'`.
  - When finished, store full content, compute `contentHash=sha256(fullContent)`, and re-key to `contentRef='cid:sha256:<hash>'` for deduplication across copy/paste.

Validation rules:

- For blocks that try to include both a `:path` in the fence and a `<!-- title: ... -->` inside: the path is used and the title is ignored
- For code without a path fence, use 'Code' as title and attempt auto detection of code language

#### Input

- decrypted_markdown_text (of message draft, sent user request, sent assistant response)
- mode (write_mode or read_mode)

#### Output (write_mode)

In write_mode we take markdown input and output a rendered tiptap version that is easy to edit in the message input field. We fully render embedded previews (for the various apps, like Code, Web, Maps, etc.), but when the user presses backspace, we turn the rendered embedded preview back into code that can be edited and which is only highlighted by a different grey tone then the rest of the text, to visualize that the embedded preview is recognized as such.

- tiptap code / rendered code
- markdown tags which can't be easily removed are not rendered but highlighted in different color: headings
- rendered previews which are auto parsed and can be edited via backspace: previews which can profit from added context or smaller footprint in message -> code block, document, sheet, web url, image url, YouTube url
- auto checks if any such preview is started via regex for code blocks, urls, tables. But while preview block is not closed, the text will only be color wise highlighted (to show the user the system recognizes the text as a preview, while keep enabling the user to edit the preview). Rendering will only happen once the preview is closed via closing ``` or space or empty line (depending on preview type)
- auto detect multiple previews of same type behind each other without space and if detected create a slider which can scroll previews from left to right

#### Output (read_mode)

In read_mode we take the markdown and fully render all embedded previews (for the various apps, like Code, Web, Maps, etc.) in the message, as well as render inline code, inline links, formula, headings, etc. 

- tiptap code / rendered code

### Clipboard semantics (copy/paste without duplication)

Goal: Copying an embed captures a snapshot of the exact content at copy-time (immutable), places canonical markdown for external apps on the system clipboard, and preserves a zero-duplication path inside OpenMates via a `cid`.

Copy (from preview context menu or fullscreen):

- Snapshot the current content:
  - Resolve full content from `contentRef`, compute `contentHash=sha256(fullContent)` and set `contentRef='cid:sha256:<hash>'` in the payload (immutable).
- Write multiple clipboard flavors:
  - text/plain: canonical fenced markdown block (Path-or-Title) of that snapshot
  - text/markdown: same canonical fenced block
  - application/x-openmates-embed+json: JSON payload with lightweight metadata and inline content for portability:

    {
      "version": 1,
      "id": "<messageId>:<embedIndex>",
      "type": "code|doc|sheet",
      "language": "<optional>",
      "filename": "<optional relative path>",
      "contentRef": "cid:sha256:<hash>",
      "contentHash": "<sha256>",
      "inlineContent": "..." | { "grid": string[][] }
    }

Paste (inside OpenMates MessageInput):

- If application/x-openmates-embed+json is present:
  - Parse payload and call ContentStore.ensure(contentRef=cid, inlineContent) so content is present locally.
  - Insert a lightweight embed node pointing to that `contentRef` with `contentHash` and minimal metadata. Do not inject raw markdown into the editor.
- Otherwise, fall back to regular markdown parsing of text/plain or text/markdown using Path-or-Title rules, which may create a new `contentRef`.

Send-time serialization (TipTap → Markdown):

- On send, walk the TipTap document and serialize embed nodes to canonical markdown by resolving full content from the ContentStore. If content is missing, prompt the user to retry loading or block send.

Cross-device rehydration:

- If a pasted `contentRef` is a `cid:*` unknown locally, `ensure()` can accept `inlineContent` embedded in the clipboard payload to reconstruct it, or the paste falls back to the markdown path which regenerates the content.
- For private, unsynced content, deduplication only works on the same device/session unless inline content is provided.

### Long-term: Markdown-based storage with local processing

In the future architecture, we plan to transition from storing TipTap JSON to storing raw markdown text for all messages. This approach offers several advantages:

1. **Simplified storage format** - Messages stored as plain markdown text rather than complex JSON structures
2. **Local encryption/decryption** - Markdown text encrypted/decrypted locally for each message
3. **Client-side parsing** - All parsing and rendering of markdown elements (code blocks, URLs, etc.) performed locally
4. **Improved privacy** - Zero-knowledge encryption of message content with no server-side processing of unencrypted content
5. **Reduced backend complexity** - Backend only handles encrypted markdown without needing to understand message structure

#### Implementation details

The new flow will work as follows:

1. **User input** - User enters markdown text in the editor
2. **Local encryption** - Markdown text is encrypted locally before transmission
3. **Storage** - Encrypted markdown stored in the database
4. **Retrieval** - Encrypted messages retrieved and decrypted locally
5. **Local parsing** - Client converts markdown to TipTap JSON on device when:
   - User sends a message
   - Assistant responses are received
   - Existing encrypted chats are decrypted and loaded
6. **Rendering** - TipTap JSON rendered with appropriate UI components

This approach eliminates the current need for server-side conversion between TipTap JSON and markdown for LLM processing, as all messages will already be in markdown format. The LLM will receive the raw markdown text, and all rich rendering will be handled exclusively by the client.

#### Benefits for LLM processing

- **Consistency** - LLMs receive the exact same markdown format that users see
- **Preservation of structure** - Code blocks, URLs, and other special elements properly preserved in their markdown form
- **Simplified processing pipeline** - No need for conversion between formats for LLM consumption

#### Client-side processing flow

1. **Storage format**: Raw markdown text (encrypted)
2. **Display format**: TipTap JSON (generated on-device)
3. **Conversion timing**:
   - When sending user messages: Markdown → TipTap JSON for display
   - When receiving AI responses: Markdown → TipTap JSON for display
   - When loading chat history: Decrypt markdown → Convert to TipTap JSON for display
4. **LLM processing**: Raw markdown text (no conversion needed)
