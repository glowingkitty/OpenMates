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

- one “parse_messag()” function for both parsing message_inputfield in active chat, as well as sent messages from user and assistant

### Input

- markdown text (of message draft, sent user request, sent assistant response)

### Output (message_inputfield)

- tiptap code / rendered code
- markdown tags which can’t be easily removed are not rendered but highlighted in different color: headings
- rendered previews which are auto parsed and can be edited via backspace: previews which can profit from added context or smaller footprint in message -> code block, document, sheet, web url, image url, YouTube url
- auto checks if any such preview is started via regex for code blocks, urls, tables. But while preview block is not closed, the text will only be color wise highlighted (to show the user the system recognizes the text as a preview, while keep enabling the user to edit the preview). Rendering will only happen once the preview is closed via closing ``` or space or empty line (depending on preview type)
- auto detect multiple previews of same type behind each other without space and if detected create a slider which can scroll previews from left to right

### Output (sent user request, sent assistant response)

- tiptap code / rendered code
