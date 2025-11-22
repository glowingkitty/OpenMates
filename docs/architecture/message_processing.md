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
  - **Embeds**: Embeds are cached separately at `embed:{embed_id}` (vault-encrypted, 24h TTL, global cache - one entry per embed). Chat index `chat:{chat_id}:embed_ids` tracks which embeds belong to each chat for eviction. When building AI context, embed references in messages are resolved to actual embed content from cache. See [Embeds Architecture](./embeds.md) for details.
  
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
   - Messages are sent as stored: containing embed references (JSON blocks with `embed_id`), not resolved embed content
   - **Embeds sent together**: Client parses messages to detect embed references, loads actual embed content from EmbedStore/IndexedDB (decrypted), and sends embeds as cleartext along with messages in the payload
6. **Server re-caches**: Server uses client-provided history (line 261-310), re-encrypts with current vault key, and caches for future use
   - **Message Caching**: Messages are cached exactly as received from client - with embed references intact (JSON blocks with `embed_id`). Server does NOT replace embed placeholders before caching.
   - **Embed Processing**: Server receives embeds along with messages (cleartext). For each embed:
     - Checks if embed already exists in cache/Directus (by `embed_id` and `version_number`)
     - If embed exists and version matches: Skip saving (no changes, already cached)
     - If new or version changed:
       - **Client-encrypted version**: Client encrypts embed with embed-specific key (`encryption_key_embed`), server persists to Directus (zero-knowledge permanent storage - server cannot decrypt)
       - **Vault-encrypted version**: Server encrypts embed with vault key (`encryption_key_user_server`), saves to `embed:{embed_id}` cache (vault-encrypted, 24h TTL) - for AI processing only, not persisted to Directus
   - **On-Demand Resolution**: Embed placeholder replacement happens only when building AI context for inference - cached messages remain unchanged with embed references
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

**PII Protection**: Before sending messages to LLMs, sensitive personal information (PII) should be pseudonymized to protect user privacy. See [Sensitive Data Redaction Architecture](./sensitive_data_redaction.md) for implementation details and options (Presidio, data-anonymizer).

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
    - **Benchmark Resources**: See [AI Model Selection Architecture](./ai_model_selection.md#benchmark-resources-for-model-comparison) for resources used in model comparison
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
   - Skills: List of skill identifiers (e.g., `web-search`, `images-generate`, `videos-get_transcript`)
   - Focus Modes: List of focus mode identifiers (e.g., `web-research`, `code-plan_project`)
   - App Settings & Memories: List of available settings/memories (without content) that the user has saved

2. **Pre-Processing Analysis**: The preprocessing LLM analyzes the user request and outputs:
   - `relevant_app_skills`: List of skill identifiers that might be relevant
   - `relevant_app_focus_modes`: List of focus mode identifiers that might be relevant
   - `relevant_app_settings_and_memories`: List of settings/memories categories and entries that might be relevant
   - `relevant_new_app_settings_and_memories`: List of settings/memories categories which we might want to generate after processing the user request (for post-processing feedback)

3. **Validation & Loading**: For each preselected skill/focus mode:
   - Verify it exists and is available
   - **Check if app is installed**: Exclude skills from uninstalled apps (all apps installed by default, user can uninstall in App Store)
   - Check if user has deactivated it (if user preferences are implemented)
   - **Auto-exclude skills that require connected accounts** when no account is connected yet
   - Load full tool definition for main processing

4. **Settings & Memories Content**: For preselected settings/memories:
   - Check chat history for existing app settings/memories request messages
   - If pending request exists, extract accepted responses from the message's YAML structure
   - If no request exists or request is incomplete, create a new system message in chat history with the request (encrypted with chat key)
   - Send WebSocket notification to client
   - Continue processing immediately (no waiting/timeout)
   - Include accepted responses from chat history in main processing context
   - Include newly-created entries from previous messages in the same chat
   
   **Note**: Requests persist in chat history indefinitely, allowing users to respond hours or days later. The conversation continues without the data until the user provides it.

5. **Dynamic Skills for Settings/Memories Management**:
   - For apps with relevant settings/memories, include dynamically generated skills
   - Skills enable full CRUD operations on settings/memories entries:
     - `{app_id}.settings_memories_add_{category_name}` - Create new entries
     - `{app_id}.settings_memories_update_{category_name}` - Update existing entries
     - `{app_id}.settings_memories_delete_{category_name}` - Delete existing entries
   - These skills are available for use in main processing when user confirms they want to save, update, or delete data

**Account-Connected Skills Handling:**

Some skills require the user to have a connected account (e.g., Gmail integration, Twitter/X API access, external service credentials). The system automatically excludes these skills from processing when no account is connected yet:

1. **Detection**: During validation, the system checks if a skill requires an account connection via its `requires_account` metadata
2. **Account Status Check**: Verifies if the user has an active connection to the required service
3. **Auto-Exclusion**: If no connection exists, the skill is removed from the preselected tools before main processing
4. **Graceful Handling**: The LLM never attempts to call unavailable skills, avoiding errors and confusing responses

This ensures users aren't offered functionality that cannot work without proper setup, and prevents the LLM from wasting tokens trying to use unavailable tools.

**Benefits:**
- **Scalability**: System can handle hundreds of skills without performance degradation
- **Efficiency**: Reduces token usage by only including relevant tools
- **Accuracy**: LLM receives a focused set of tools, improving decision-making
- **Privacy**: Only relevant settings/memories are requested from client
- **User Experience**: Prevents errors from unavailable account-dependent skills
- **Reliability**: Only executable skills are provided to the LLM

**Example Input to Pre-Processing:**

```text
Skills:
web-search
images-generate
videos-get_transcript
code-write_file
travel-search_connections

Focus Modes:
web-research
code-plan_project
videos-summarize
```

**Example Output from Pre-Processing:**

```json
{
  "relevant_app_skills": ["web-search", "videos-get_transcript"],
  "relevant_app_focus_modes": ["web-research"],
  "relevant_app_settings_and_memories": ["web-preferred_search_provider"],
  "relevant_new_app_settings_and_memories": ["travel-upcoming_trips", "movies-watched"]
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
- **Skill results format**: When skill results are passed to the LLM via function calling, they are encoded in **TOON (Token-Oriented Object Notation) format** instead of JSON. This reduces token usage by 30-60% compared to JSON, making it more efficient for LLM inference and chat history storage. REST API responses still return JSON format for frontend compatibility.

- **Embeds Architecture**: Skill results are stored as separate embed entities and referenced in messages. When building AI context from cached chat history, embed references are resolved to actual embed content (TOON format) from the embed cache (`embed:{embed_id}`). See [Embeds Architecture](./embeds.md) for details.

For detailed documentation on how function calling works, see [Function Calling Architecture](./apps/function_calling.md).

### Embed Creation During Skill Execution

**Status**: ⚠️ **TO BE IMPLEMENTED** - This is the new architecture for handling skill results.

**Flow**: Immediately after skill execution completes (before LLM inference continues):

1. **Skill Results Received**:
   - Skill executes and returns results in JSON format
   - Results are received in [`main_processor.py`](../../backend/apps/ai/processing/main_processor.py) after tool call execution

2. **Embed Creation** (Server-Side):
   - **For composite results** (web search, places, events):
     - Convert each result to TOON format (30-60% space savings vs JSON)
     - Create child embed entries (one per result): `website`, `place`, or `event` embeds
       - Each child embed: `content` field contains TOON-encoded result data
     - Create parent embed entry: `app_skill_use` embed
       - Parent embed `content`: TOON-encoded metadata (query, provider, skill name, etc.)
       - Parent embed `embed_ids`: Array of child embed IDs
   - **For single results** (code generation, image generation):
     - Convert result to TOON format
     - Create single `app_skill_use` embed entry
     - Embed `content`: TOON-encoded result data
     - `embed_ids`: null (no child embeds)

3. **Server-Side Caching**:
   - Encrypt embeds with vault key (`encryption_key_user_server`) - server can decrypt for AI
   - Cache at `embed:{embed_id}` (24h TTL, global cache - one entry per embed)
   - Add to `chat:{chat_id}:embed_ids` index for eviction tracking
   - Content stored as TOON string (no conversion needed until inference)

4. **Stream Embed Reference Chunk**:
   - Create embed reference JSON: `{"type": "app_skill_use", "embed_id": "..."}`
   - Stream as markdown code block chunk to frontend immediately via [`stream_consumer.py`](../../backend/apps/ai/tasks/stream_consumer.py)
   - Frontend receives chunk, parses embed reference, loads embed from cache
   - Frontend renders embed preview immediately (user sees results while LLM continues processing!)

5. **LLM Inference Continues**:
   - LLM receives filtered skill results (for inference efficiency - excludes non-essential fields)
   - LLM processes results and generates response
   - LLM can place additional embed references anywhere in response (flexible placement)
   - Embed references are streamed as JSON code blocks in markdown

**Benefits**:
- ✅ **Immediate Results**: Users see skill results instantly (before LLM finishes processing)
- ✅ **Space Efficient**: TOON format saves 30-60% storage vs JSON
- ✅ **Flexible Placement**: LLM can place embed references contextually within response
- ✅ **No Repeated Conversion**: Store as TOON, decode only when needed (rendering/inference)
- ✅ **Fast Inference**: Server cache stores TOON, decodes only when building AI context

**Implementation Files**:
- Embed creation: [`backend/core/api/app/services/embed_service.py`](../../backend/core/api/app/services/embed_service.py) (to be created)
- Embed caching: [`backend/core/api/app/services/cache_chat_mixin.py`](../../backend/core/api/app/services/cache_chat_mixin.py) (update)
- Streaming: [`backend/apps/ai/tasks/stream_consumer.py`](../../backend/apps/ai/tasks/stream_consumer.py) (update)
- Skill execution: [`backend/apps/ai/processing/main_processor.py`](../../backend/apps/ai/processing/main_processor.py) (update)

### Embed Processing During Inference

**Embed Resolution Flow**:

1. **Messages Contain Embed References**: Messages stored in cache contain lightweight JSON reference blocks (e.g., `{"type": "app_skill_use", "embed_id": "..."}`) instead of full embed content

2. **Client Provides Full History (Cache Miss)**:
   - When server requests full chat history due to cache miss, client loads messages from IndexedDB
   - Client sends messages as stored: containing embed references (JSON blocks with `embed_id`), not resolved embed content
   - Messages are sent with embed references intact (as they are stored in IndexedDB)

3. **Server Receives and Processes Messages and Embeds**:
   - Server receives messages with embed references (not resolved) and embeds as cleartext (sent together by client)
   - **Message Caching**: Messages are cached exactly as received - with embed references intact (JSON blocks with `embed_id`). Server does NOT replace embed placeholders before caching.
   - **Embed Processing**: For each embed received from client:
     - Server checks if embed already exists in cache/Directus (by `embed_id` and `version_number`)
     - If embed exists and version matches: Skip saving (no changes, already cached)
     - If new or version changed:
       - **Client-encrypted version**: Client encrypts embed with embed-specific key (`encryption_key_embed`), server persists to Directus (zero-knowledge permanent storage - server cannot decrypt)
       - **Vault-encrypted version**: Server encrypts embed with vault key (`encryption_key_user_server`), saves to `embed:{embed_id}` cache (vault-encrypted, 24h TTL, global cache) - for AI processing only, not persisted
   - **Cached messages remain unchanged** - embed resolution happens on-demand during inference only

4. **Embed Resolution on Every Inference**:
   - **Every time messages are used for AI inference** (including follow-up requests), the server:
     - Parses message markdown to detect embed reference JSON blocks (e.g., `{"type": "app_skill_use", "embed_id": "..."}`)
     - Loads embeds from cache (`embed:{embed_id}`) for each `embed_id` found
     - Decrypts embeds using vault key (server can decrypt for AI processing)
     - **Decodes TOON content** from embed `content` field (stored as TOON string, decoded for inference)
     - Replaces embed reference JSON blocks in messages with actual embed content (decoded from TOON)
     - Includes resolved messages with embed content in AI context sent to LLM
   - This ensures LLM always receives full embed content, not just references, for proper context understanding
   - **TOON Decoding**: Content is decoded from TOON only when building AI context (not on every cache read)

5. **Fallback if Embed Missing from Cache**:
   - If embed not found in cache, server requests embed from client
   - Client loads embed from Directus, decrypts, sends to server as cleartext
   - Server caches embed for future use

**Key Points**:
- ✅ Client sends messages with embed references (as stored) - server does NOT receive resolved embed content from client
- ✅ Server resolves embed references: parses messages, loads embeds from cache, replaces placeholders with actual embed content
- ✅ Server processes embeds: encrypts with vault key, stores separately in `embed:{embed_id}` cache
- ✅ Embed placeholder replacement happens **every time** messages are used for inference (follow-up requests) - server-side resolution
- ✅ Server resolves embed references from cache before sending to LLM, ensuring LLM always receives full embed content

**Output**: Clear text response streamed to client (client will encrypt before storage)

**Configuration**: [`backend/apps/ai/base_instructions.yml`](../../backend/apps/ai/base_instructions.yml) - Contains base ethics, app use, and follow-up instructions

## Post-Processing

**Status**: ⚠️ **NOT YET IMPLEMENTED** - This is planned functionality that is still on the todo list.

**Planned Implementation**: Future dedicated post-processing module (to be created)

**Overview**: Post-processing analyzes the last user message and assistant response to generate contextual suggestions, settings/memories suggestions, and metadata.

**LLM Configuration**:
- **Model**: Mistral Small 3.2 (text only) or Gemini 2.5 Flash Lite (text + images)
- **Output Format**: JSON via function calling
- **System Prompt**: Includes ethics instructions and requests structured JSON output

**Generated Outputs**:
- **[Follow-up Suggestions & New Chat Suggestions](./followup_request_suggestions.md)**: 6 contextual suggestions for each type
- **[Settings/Memories Suggestions](#settingsmemories-suggestions)**: Suggested data to save to settings/memories
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

## Settings/Memories Suggestions

**Status**: ⚠️ **NOT YET IMPLEMENTED** - Part of main processing system prompt optimization

**Overview**: The main processing system prompt is optimized to detect when relevant settings/memories should be saved, updated, or deleted based on the conversation context. The assistant includes natural language suggestions in its response, which are then picked up by post-processing to generate follow-up request suggestions.

### Flow

1. **Pre-Processing**: Provides relevant app settings/memories entries to main processing (see [Tool Preselection](#tool-preselection))
   - Includes existing entries that might be relevant to the conversation
   - Includes available settings/memories categories and their schemas
   - Includes dynamically generated skills for managing settings/memories

2. **Main Processing**: System prompt is optimized to:
   - Analyze conversation context against relevant settings/memories
   - Detect if new entries should be saved (e.g., user mentions watching a movie, visiting a restaurant)
   - Detect if existing entries should be updated (e.g., user changes a rating, updates preferences)
   - Detect if entries should be deleted (e.g., user wants to remove something from a list)
   - Include natural language suggestions in the response when appropriate
   - Example: "Would you like me to save 'Inception' to your watched movies list?"
   - Example: "Should I update your rating for 'The Matrix' to 9.5?"
   - Example: "Would you like me to remove 'Old Restaurant' from your favorites?"

3. **Post-Processing**: Generates follow-up request suggestions
   - Analyzes the main processing response for settings/memories suggestions
   - Extracts natural language suggestions about saving/updating/deleting entries
   - Converts them into actionable follow-up request suggestions
   - These appear as quick action buttons in the UI

4. **User Interaction**: User clicks on follow-up suggestion
   - User confirms by clicking the suggestion (e.g., "Save Inception to watched movies")
   - This triggers a new message with the confirmation
   - Main processing receives the confirmation and calls the appropriate skill:
     - `{app_id}.settings_memories_add_{category}` for new entries
     - `{app_id}.settings_memories_update_{category}` for updates (with entry_id and changed fields)
     - `{app_id}.settings_memories_delete_{category}` for deletions (with entry_id)
   - Skill execution follows the zero-knowledge encryption flow (see [app_settings_and_memories.md](./apps/app_settings_and_memories.md#execution-flow))

### System Prompt Optimization

The main processing system prompt includes instructions to:

- Monitor conversation for data that matches available settings/memories categories
- Suggest saving data when it would be valuable for future personalization
- Suggest updating entries when user provides corrections or new information
- Suggest deleting entries when user indicates they want something removed
- Use natural, conversational language for suggestions (not technical skill names)
- Only suggest when it adds clear value to the user experience

### Integration with Follow-up Suggestions

- Post-processing automatically extracts settings/memories suggestions from the main response
- These are converted into follow-up request suggestions that appear as quick action buttons
- Users can click to confirm, which triggers skill execution
- Follow-up suggestions also reference newly-created/updated entries for personalization

## Topic specific post-processing

- for example: for software development related requests, also check generated code for security flaws, if comments and reasoning for decisions is included, if it violates requirements, if docs need to be updated, if files are so long that they should be better split up, if the files, duplicate code, compiler errors, etc. -> generate "next step suggestions" in addition to follow up questions


## Storage constraints and parsing implications

When local storage is constrained (e.g., IndexedDB quota), parsing and rendering should remain responsive by relying on lightweight nodes and on-demand content loading.

- Lightweight parsing output
    - `parse_message()` emits minimal embed nodes (id, type, status, contentRef, contentHash?, small metadata). It never stores full preview text in the node.
    - Previews are derived at render time from the EmbedStore; if missing, show a placeholder and load on-demand when user enters fullscreen.

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