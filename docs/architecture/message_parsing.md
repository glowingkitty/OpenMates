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

## Planned changes

### Short-term: Unified parsing function

- one "parse_message()" function for both parsing message_inputfield in active chat, as well as sent messages from user and assistant

#### Input

- markdown text (of message draft, sent user request, sent assistant response)

#### Output (message_inputfield)

- tiptap code / rendered code
- markdown tags which can't be easily removed are not rendered but highlighted in different color: headings
- rendered previews which are auto parsed and can be edited via backspace: previews which can profit from added context or smaller footprint in message -> code block, document, sheet, web url, image url, YouTube url
- auto checks if any such preview is started via regex for code blocks, urls, tables. But while preview block is not closed, the text will only be color wise highlighted (to show the user the system recognizes the text as a preview, while keep enabling the user to edit the preview). Rendering will only happen once the preview is closed via closing ``` or space or empty line (depending on preview type)
- auto detect multiple previews of same type behind each other without space and if detected create a slider which can scroll previews from left to right

#### Output (sent user request, sent assistant response)

- tiptap code / rendered code

### Long-term: Markdown-based storage with local processing

In the future architecture, we plan to transition from storing TipTap JSON to storing raw markdown text for all messages. This approach offers several advantages:

1. **Simplified storage format** - Messages stored as plain markdown text rather than complex JSON structures
2. **Local encryption/decryption** - Markdown text encrypted/decrypted locally for each message
3. **Client-side parsing** - All parsing and rendering of markdown elements (code blocks, URLs, etc.) performed locally
4. **Improved privacy** - End-to-end encryption of message content with no server-side processing of unencrypted content
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
