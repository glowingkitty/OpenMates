# Message processing architecture

> Server caches last 3 chats in memory (encrypted with server-side vault key) for follow-up context, while maintaining zero-knowledge architecture for permanent storage.

## Zero-Knowledge Architecture Overview

**Core Principle**: Server never has client-side decryption keys and can only process messages when client provides decrypted content on-demand.

**Flow**:
1. Client encrypts all messages with chat-specific keys (client-side E2EE via [`cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts))
2. Server stores only encrypted messages permanently (cannot decrypt - zero-knowledge storage in Directus)
3. When processing needed, client decrypts and sends clear text to server via [`chatSyncServiceSenders.ts`](../../frontend/packages/ui/src/services/chatSyncServiceSenders.ts)
4. **Server caches last 3 chats in memory** (encrypted with server-side vault key per user via [`EncryptionService`](../../backend/core/api/app/utils/encryption.py)) for follow-up context
5. Server processes clear text using cached history when available (see [`message_received_handler.py`](../../backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py))
6. Server streams response to client (via [`stream_consumer.py`](../../backend/apps/ai/tasks/stream_consumer.py))
7. **Server saves assistant response to cache** (encrypted with server-side vault key via [`CacheService`](../../backend/core/api/app/services/cache.py))
8. Client receives response, encrypts with chat-specific key, and stores on server (zero-knowledge permanent storage)

**Key Architecture Points**:
- **Permanent Storage**: Zero-knowledge (server cannot decrypt) - stored in Directus database
  - Uses client-side `encryption_key_chat` per chat (see [`security.md#chats`](./security.md#chats))
  - Messages encrypted/decrypted client-side only

- **Dual-Cache Architecture**: Two separate message caches with different encryption and purposes:
  
  **1. AI Inference Cache** (`user:{user_id}:chat:{chat_id}:messages:ai`):
  - **Purpose**: Fast AI processing context (last 3 recently used chats)
  - **Encryption**: Vault-encrypted with `encryption_key_user_server` (server can decrypt for AI)
  - **TTL**: 24 hours
  - **Used by**: `message_received_handler.py` when building AI context
  - **Populated**: When new messages arrive from client
  - **Methods**: `add_ai_message_to_history()`, `get_ai_messages_history()`
  
  **2. Sync Cache** (`user:{user_id}:chat:{chat_id}:messages:sync`):
  - **Purpose**: Fast client sync during login (last 100 chats)
  - **Encryption**: Client-encrypted with `encryption_key_chat` (same as Directus)
  - **TTL**: 1 hour (cleared after Phase 3 completion)
  - **Used by**: Phase 1/2/3 sync handlers when sending chats to client
  - **Populated**: During cache warming (from Directus)
  - **Methods**: `set_sync_messages_history()`, `get_sync_messages_history()`
  - **Cleanup**: Automatically cleared after successful Phase 3 sync

- **Why Dual-Cache?**:
  - AI cache uses vault encryption (server can decrypt for processing)
  - Sync cache uses client encryption (zero-knowledge maintained)
  - Mixing would cause decryption failures on client side
  - Implemented in [`cache_chat_mixin.py`](../../backend/core/api/app/services/cache_chat_mixin.py)

- **Cache Expiry**: AI cache: 24h, Sync cache: 1h (ephemeral, cleared post-sync)
- **Privacy**: Both caches are per-user, isolated, and encrypted with appropriate keys

**Architecture Alignment with [`security.md`](./security.md)**:
- ✅ **Client-side E2EE for permanent storage** - matches zero-knowledge principle
- ✅ **Server stores encrypted blobs it cannot decrypt** - for permanent storage
- ✅ **Server-side vault encryption for temporary cache** - uses `encryption_key_user_server` for "low sensitivity data"
- ✅ **Performance optimization** - cache enables fast AI responses without client re-sending history
- ✅ **Privacy-preserving** - cache is temporary, user-isolated, and encrypted

**Cache Fallback Mechanism** (On-Demand Architecture):
1. Client sends new user message with only the message content (no full history by default) via [`sendNewMessageImpl()`](../../frontend/packages/ui/src/services/chatSyncServiceSenders.ts:150)
2. Server receives message in [`handle_message_received()`](../../backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py:21) and checks if chat history is in cache (last 3 chats per user) via [`cache_service.get_chat_messages_history()`](../../backend/core/api/app/services/cache_chat_mixin.py:505)
3. **If in cache and decryption succeeds**: Server decrypts cached history with [`decrypt_with_user_key()`](../../backend/core/api/app/utils/encryption.py:371) using `user_vault_key_id` (line 282-285) and uses it for AI processing
4. **If cache miss or decryption fails** (stale vault keys): Server detects failures (line 334-348) and sends [`request_chat_history`](../../backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py:337) event to client
5. **Client responds**: [`handleRequestChatHistoryImpl()`](../../frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts:543) loads all messages from IndexedDB and resends with `message_history` field
6. **Server re-caches**: Server uses client-provided history (line 261-310), re-encrypts with current vault key, and caches for future use
7. After AI response, server saves assistant message to cache for next follow-up via [`_save_to_cache_and_publish()`](../../backend/apps/ai/tasks/stream_consumer.py)

**Current Implementation** (as of this fix):
- ✅ Server caches user messages when received (via [`message_received_handler.py`](../../backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py))
- ✅ Server caches assistant responses after processing (via [`stream_consumer.py`](../../backend/apps/ai/tasks/stream_consumer.py))
- ✅ Server uses cached history (both user and assistant messages) for follow-ups
- ✅ Cache includes last 3 most recently edited chats per user (configured via `TOP_N_MESSAGES_COUNT`)
- ✅ Falls back to Directus if cache miss occurs (see lines 222-264 in [`message_received_handler.py`](../../backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py))

## Pre-Processing

**Status**: Partially implemented.

**Input**: Decrypted chat history provided by client (server cannot decrypt stored data)

**Implementation**: [`backend/apps/ai/processing/preprocessor.py`](../../backend/apps/ai/processing/preprocessor.py)

- Split chat history into blocks of 70.000 tokens max
- send separate request for every 70.000 tokens, to be processed simultaneously
- then extract max harmful value, last language code, etc.
- LLM request to mistral small 3.2
- system prompt:
    - requests a json output via function calling
        - language_code: language code of the last user request (default: EN)
- extract request category and therefore mate (software, marketing, etc.)
- define best fitting LLM for request based on complexity/usecase
    - **Model Selection**: Analyzes request to determine optimal LLM (reasoning, coding, vision, etc.)
    - **Selection Reasoning**: Outputs explanation for why specific model was chosen
    - **Factors Considered**: Task complexity, content type (text/code/images), required capabilities, cost-efficiency
    - **Output Fields**:
        - `selected_model`: Model identifier (e.g., "claude-3-5-sonnet", "gpt-4o", "gemini-2.0-flash")
        - `selection_reason`: Human-readable explanation of model choice
- detect harmful / illegal requests
- **preselect relevant app skills and focus modes** (see [Tool Preselection](#tool-preselection) below)
- detect which app settings & memories need to be requested by user to hand over to main processing (and requests those data via websocket connection)
- "tags" field, which outputs a list of max 10 tags for the request, based on which the frontend will send the top 3 "similar_past_chats_with_summaries" (and allow user to deactivate that function in settings)
- "prompt_injection_chance" -> extract chance for prompt injection, to then include in system prompt explicit warning to not follow request but continue the conversation in a better direction
- **"title"** -> generated title for the chat (**first message only** - skipped if chat already has a title)
- **"icon_names"** -> which icon names to consider from the Lucide icon library (**first message only** - skipped if chat already has a title)
- **"category"** -> chat category for visual organization and filtering (always generated, but only used for icon/category storage on first message)

**One-Time Metadata Generation**: The preprocessing stage checks if a chat already has a title (`current_chat_title` field in request). If a title exists, it skips generating `title` and `icon_names` fields. This ensures that chat metadata (title, icon, category) is set only once during the first message and remains consistent for all follow-up messages.

**Configuration**: [`backend/apps/ai/base_instructions.yml`](../../backend/apps/ai/base_instructions.yml) - Contains the preprocessing tool definition and base instructions

### Tool Preselection

**Status**: Implemented when apps are implemented

**Purpose**: As the number of apps and skills grows, including all available tools in every main processing request becomes inefficient and can overload the LLM. Tool preselection filters tools to only those relevant to the current request.

**How It Works:**

1. **Input to Pre-Processing**: A simplified overview of all available app skills and focus modes is provided:
   - Skills: List of skill identifiers (e.g., `web.search`, `images.generate`, `videos.get_transcript`)
   - Focus Modes: List of focus mode identifiers (e.g., `web.research`, `code.plan_project`)
   - App Settings & Memories: List of available settings/memories (without content) that the user has saved

2. **Pre-Processing Analysis**: The preprocessing LLM analyzes the user request and outputs:
   - `relevant_app_skills`: List of skill identifiers that might be relevant
   - `relevant_app_focus_modes`: List of focus mode identifiers that might be relevant
   - `relevant_app_settings_and_memories`: List of settings/memories that might be relevant

3. **Validation & Loading**: For each preselected skill/focus mode:
   - Verify it exists and is available
   - Check if user has deactivated it (if user preferences are implemented)
   - Load full tool definition for main processing

4. **Settings & Memories Content**: For preselected settings/memories:
   - Request actual content from client via WebSocket
   - Include in main processing context

**Benefits:**
- **Scalability**: System can handle hundreds of skills without performance degradation
- **Efficiency**: Reduces token usage by only including relevant tools
- **Accuracy**: LLM receives a focused set of tools, improving decision-making
- **Privacy**: Only relevant settings/memories are requested from client

**Example Input to Pre-Processing:**

```text
Skills:
web.search
images.generate
videos.get_transcript
code.write_file
travel.search_connections

Focus Modes:
web.research
code.plan_project
videos.summarize
```

**Example Output from Pre-Processing:**

```json
{
  "relevant_app_skills": ["web.search", "videos.get_transcript"],
  "relevant_app_focus_modes": ["web.research"],
  "relevant_app_settings_and_memories": ["web.preferred_search_provider"]
}
```

For detailed documentation on tool preselection and scalability, see [Function Calling Architecture](./apps/function_calling.md#scalability-and-tool-preselection).

## Main-processing

**Input**: Decrypted chat history and user data provided by client

**Implementation**: [`backend/apps/ai/processing/main_processor.py`](../../backend/apps/ai/processing/main_processor.py)

- LLM request to model selected by pre-processing
- system prompt:
    - is built up based on multiple instruction parts:
        1. Focus instruction (if focus mode active for chat)
        2. Base ethics instruction
        3. Mate specific instruction
        4. Apps instruction (about how to decide for which app skills/focus modes?)
- input:

	- chat history (decrypted by client)
	- similar_past_chats (based on pre-processing)
	- user data
		- interests (related to request or random, for privacy reasons. Never include all interests to prevent user detection.)
		- preferred learning style (visual, auditory, repeating content, etc.)
- assistant creates response & function calls when requested (for starting focus modes and app skills)

For detailed documentation on how function calling works, see [Function Calling Architecture](./apps/function_calling.md).

**Output**: Clear text response streamed to client (client will encrypt before storage)

**Configuration**: [`backend/apps/ai/base_instructions.yml`](../../backend/apps/ai/base_instructions.yml) - Contains base ethics, app use, and follow-up instructions

## Post-Processing

**Status**: ⚠️ **NOT YET IMPLEMENTED** - This is planned functionality that is still on the todo list.

**Planned Implementation**: Future dedicated post-processing module (to be created)

**Overview**: Post-processing analyzes the last user message and assistant response to generate contextual suggestions and metadata.

**LLM Configuration**:
- **Model**: Mistral Small 3.2 (text only) or Gemini 2.5 Flash Lite (text + images)
- **Output Format**: JSON via function calling
- **System Prompt**: Includes ethics instructions and requests structured JSON output

**Generated Outputs**:
- **[Follow-up Suggestions & New Chat Suggestions](./followup_request_suggestions.md)**: 6 contextual suggestions for each type
- **[Chat Summary](#chat-summary)**: 2-3 sentence summary for context
- **[Chat Tags](#chat-tags)**: Max 10 tags for categorization
- **harmful_response**: Score 0-10 to detect harmful responses and consider reprocessing
- **new_learnings**: (idea phase) Better collect new learnings

**Additional Features** (to be implemented):
- Auto-parse URLs in response and validate links (replace 404s with Brave search?)
- Consider user interests without creating tracking profile
- Consider user's learning type (visual, auditory, reading, etc.)

> **Note from dev meetup (2025-10-08)**: How to implement harm detection with pre-processing and post-processing without overreacting - what parameters to include? Consider balancing false positives vs. false negatives, defining clear thresholds, and establishing criteria for when to flag vs. block vs. redirect responses.
> **Note from dev meetup (2025-10-08)**: Implement 'compress conversation history' functionality, to reduce the size of the conversation history for the LLM? But if so, we need to show user the compresses conversation by default and show a 'Show full conversation' button to show the full conversation from before, with the clear dislaimer that the conversation history is not used anymore when the user asks a new question. Althought we can consider implementing a functionality that allows the chatbot to search in the full chat history of that chat and include matches again into the conversation - a "Remember" functionality?

**Output**: Post-processing results sent to client (client will encrypt before storage)

## Topic specific post-processing

- for example: for software development related requests, also check generated code for security flaws, if comments and reasoning for decisions is included, if it violates requirements, if docs need to be updated, if files are so long that they should be better split up, if the files, duplicate code, compiler errors, etc. -> generate "next step suggestions" in addition to follow up questions


## Storage constraints and parsing implications

When local storage is constrained (e.g., IndexedDB quota), parsing and rendering should remain responsive by relying on lightweight nodes and on-demand content loading.

- Lightweight parsing output
    - `parse_message()` emits minimal embed nodes (id, type, status, contentRef, contentHash?, small metadata). It never stores full preview text in the node.
    - Previews are derived at render time from the ContentStore; if missing, show a placeholder and load on-demand when user enters fullscreen.

- Behavior under budget pressure
    - If the sync layer stored only metadata (no message bodies), `parse_message()` can still render previews from existing `contentRef` (if present) and show truncated text around them.
    - For fullscreen, the UI attempts rehydration via `contentRef`. If missing locally due to eviction, it requests content on-demand (or reconstructs from canonical markdown if available).

- Streaming backpressure
    - During streaming, avoid persisting intermediate states when space is tight. Keep in-memory and finalize once the message ends; then persist only the minimal node + `cid` mapping.
    - If final persistence exceeds budget, persist only references (`cid`) and drop inline/full content from cache.

- Copy/paste resilience
    - Clipboard JSON (`application/x-openmates-embed+json`) can include `inlineContent` to enable reconstruction even when the target device lacks the `cid` payload.


### Follow-up Suggestions & New Chat Suggestions

For detailed specifications on follow-up request suggestions and new chat suggestions (generation, storage, UI behavior, and implementation), see **[`followup_request_suggestions.md`](./followup_request_suggestions.md)**.


### Chat summary

#### Chat summary | Idea

The chat summary is a short summary of the chat, which is typically not shown to the user directly but used for new requests to the assistant so it has a context of the previous chats.

#### Chat summary | Implementation

**Status**: ⚠️ **NOT YET IMPLEMENTED** - This is planned functionality that is still on the todo list.

**Planned Backend**: To be implemented in a future post-processing module

**Planned Frontend**: To be stored and managed in [`frontend/packages/ui/src/services/db.ts`](../../frontend/packages/ui/src/services/db.ts)

- generated during post-processing
- input:
    - previous chat summary (if it exists)
    - last user request
    - last assistant response
- output:
    - new chat summary (2-3 sentences)
- include general app settings & memories which are included, but not the actual details (strip them out before generating the summary)

**Example output:**

```json
{
    // ...
    "chat_summary": "User asked about Whisper for iOS compatibility and how to implement it and assistant explained its compatibility and how to implement it."
    // ...
}
```


### Chat tags

#### Chat tags | Idea

The chat tags are a list of tags for the chat, which are used to categorize the chat and to help the user to find the chat again.

#### Chat tags | Implementation

**Status**: ⚠️ **NOT YET IMPLEMENTED** - This is planned functionality that is still on the todo list.

**Planned Backend**: To be implemented in a future post-processing module

**Planned Frontend**: To be stored and managed in [`frontend/packages/ui/src/services/db.ts`](../../frontend/packages/ui/src/services/db.ts)

- generated during post-processing
- input:
    - previous chat tags (if it exists)
    - last user request
    - last assistant response
- output:
    - new chat tags (max 10 tags)
- include general app settings & memories which are included, but not the actual details (strip them out before generating the tags)

**Example output:**

```json
{
    // ...
    "chat_tags": ["Whisper", "iOS", "Compatibility", "Implementation"]
    // ...
}
```

### User message shortening

[![User message shortening](../../docs/images/user_message_shortening.jpg)](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3544-39158&t=vQbeWjQG2QtbTDoL-4)

#### User message shortening | Idea

When the user message is too long, it should be shortened to a maximum length, so the user isn't scrolling forever.

#### User message shortening | Implementation

**Frontend**: Implemented in [`frontend/packages/ui/src/components/chats/Chat.svelte`](../../frontend/packages/ui/src/components/chats/Chat.svelte) and [`frontend/packages/ui/src/message_parsing/parse_message.ts`](../../frontend/packages/ui/src/message_parsing/parse_message.ts)

- only user messages are shortened
- shorten text rendered in DOM to first X words or X lines (use js, not webkit-line-clamp, also count in preview blocks as multiple lines of text, so messages with lots of preview blocks aren't getting bloated)
- load & decrypt & parse full message from indexedDB when clicking on 'Click to show full message' cta at the bottom of the user message

Figma design: [User message shortened](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3544-39320&t=vQbeWjQG2QtbTDoL-4)

> Question: how to better detect if user is asking for advice on how to self harm, how to harm others or how to do something illegal - over a longer conversation, and still remain reliable. (see openai case where chatgpt gave suicide instructions to teenager). Add "conversat_safety_score" that accumulates over time?

# Example enhancement to your pre-processing
harmful_content_detection:
  categories:
    - direct_self_harm
    - indirect_self_harm  
    - gradual_escalation_patterns
    - emotional_distress_indicators
  response_actions:
    - refuse_and_redirect
    - provide_crisis_resources  
    - flag_for_human_review
    - terminate_conversation

> Idea: add mate specific pre-processing? for example for software dev topics -> does request likely require folder / project overview? (if so, we would include that in vscode extension)

## Implementation Files

### Backend Processing Pipeline
- **[`backend/apps/ai/processing/README.md`](../../backend/apps/ai/processing/README.md)**: Overview of AI processing modules
- **[`backend/apps/ai/processing/preprocessor.py`](../../backend/apps/ai/processing/preprocessor.py)**: Pre-processing stage implementation
- **[`backend/apps/ai/processing/main_processor.py`](../../backend/apps/ai/processing/main_processor.py)**: Main processing stage implementation
- **[`backend/apps/ai/base_instructions.yml`](../../backend/apps/ai/base_instructions.yml)**: Core instructions and system prompts
- **[`backend/apps/ai/tasks/ask_skill_task.py`](../../backend/apps/ai/tasks/ask_skill_task.py)**: Celery task orchestration

### Frontend Message Handling
- **[`frontend/packages/ui/src/services/chatSyncServiceSenders.ts`](../../frontend/packages/ui/src/services/chatSyncServiceSenders.ts)**: Message sending and dual-phase architecture
- **[`frontend/packages/ui/src/services/chatSyncServiceHandlersChatUpdates.ts`](../../frontend/packages/ui/src/services/chatSyncServiceHandlersChatUpdates.ts)**: Chat update handlers
- **[`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts)**: Client-side encryption/decryption
- **[`frontend/packages/ui/src/services/db.ts`](../../frontend/packages/ui/src/services/db.ts)**: Local database and message encryption
- **[`frontend/packages/ui/src/message_parsing/parse_message.ts`](../../frontend/packages/ui/src/message_parsing/parse_message.ts)**: Message parsing and rendering

### WebSocket Handlers
- **[`backend/core/api/app/routes/websockets.py`](../../backend/core/api/app/routes/websockets.py)**: Main WebSocket endpoint
- **[`backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py`](../../backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py)**: Message reception handler
- **[`backend/core/api/app/routes/handlers/websocket_handlers/encrypted_chat_metadata_handler.py`](../../backend/core/api/app/routes/handlers/websocket_handlers/encrypted_chat_metadata_handler.py)**: Encrypted metadata handler
- **[`backend/core/api/app/routes/handlers/websocket_handlers/ai_response_completed_handler.py`](../../backend/core/api/app/routes/handlers/websocket_handlers/ai_response_completed_handler.py)**: AI response completion handler