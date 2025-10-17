# Follow-up Request Suggestions & New Chat Suggestions

> **Status**: ⚠️ **NOT YET IMPLEMENTED** - This is planned functionality that is still on the todo list.

## Overview

The post-processing stage generates two types of suggestions to enhance user engagement:

1. **Follow-up Request Suggestions**: 6 contextual suggestions shown under the last assistant message in an active chat (3 visible by default). Suggestion messages must encourage learning more about a topic, exploring different view points, and (once apps are implemented, later) exploring which app skills exist on OpenMates and can be used in this context. Max length: 5 words per suggestion.
2. **New Chat Request Suggestions**: Suggestions shown in the welcome message when no chat is open (3 random from stored pool). Suggestions encourage exploring new topics which are related to previous conversation tppics. Max length: 5 words per suggestion.

Both suggestion types support fuzzy search/filtering as the user types in the message input field, and clicking a suggestion copies it to the message input field.

## Architecture

### Post-Processing Pipeline

**Planned Implementation**: Future dedicated post-processing module (to be created)

- **LLM Model**: Mistral Small 3.2 for text-only, Gemini 2.5 Flash Lite for text + images
- **System Prompt Includes**:
  - Ethics prompt
  - Mate-specific prompt (software, marketing, etc.)
  - Focus mode prompt (if active)
  - Base instructions from [`backend/apps/ai/base_instructions.yml`](../../backend/apps/ai/base_instructions.yml)
- **Input Context**:
  - Last user request
  - Last assistant response
  - User interests (?)
  - User's preferred learning type (visual, auditory, reading, etc.)
- **Output**: JSON via function calling with suggestions and metadata

### Storage & Encryption

**Follow-up Request Suggestions**:
- Stored encrypted in the chat record under field `encrypted_follow_up_request_suggestions` (encrypted via chat specific key client side)
- Contains the last 18 generated suggestions (as a list)
- Stored in both IndexedDB (client-side) and Directus (server-side)
- Replaced when the next assistant response for the chat is completed

**New Chat Request Suggestions**:
- Stored under separate database model `new_chat_request_suggestions` (encrypted via master encryption key client side, not chat specific key)
- Includes `chat_id` field for tracking which chat generated each suggestion
- **NOT deleted** when the source chat is deleted (retained for continued topic exploration and usability)
- Stores the 50 most recent suggestions
- Stored in both IndexedDB (client-side) and Directus (server-side)

## Follow-up Request Suggestions

[![Follow up suggestions](../../docs/images/follow_up_suggestions.png)](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3469-39197&t=vQbeWjQG2QtbTDoL-4)

### Purpose

Engage users to ask follow-up questions, dig deeper, and learn topics better while discovering OpenMates App skills and features. Suggestions can include:
- Learning more about specific topics
- Instructions to use app skills (web search, image generation, etc.)
- Instructions to start specific focus modes
- For completed code editing tasks: "create & push commit" and similar

### Generation Rules

- **Count**: 6 suggestions generated per assistant response
- **Display**: First 3 shown by default
- **Filtering**: Auto-search/filter based on current message input
- **Hide Behavior**: If message input string is not contained in any suggestion, show no suggestions
- **Special Cases**:
  - For learning-oriented topics: Reserve one suggestion for learning-specific follow-ups ("Test me about this topic", "Prepare me for an upcoming test", "Repeat teaching me about this every week")
  - Always include app skills and focus modes in suggestions (and auto-complete when implemented)

### Example Output

```json
{
    "follow_up_request_suggestions": [
        "Explore Whisper Tiny for iOS compatibility",
        "Check iOS device compatibility for Whisper models",
        "Research Core ML conversion for Whisper models",
        "Compare Whisper accuracy with Apple's on-device speech recognition",
        "Can Whisper run offline on mobile devices efficiently?",
        "How to fine-tune Whisper for custom accents or languages?"
    ]
}
```

### Frontend Integration

**Planned Frontend**: To be handled in [`frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts`](../../frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts)

- Receive suggestions from post-processing via WebSocket
- Encrypt and store in IndexedDB under chat record
- Display first 3 in chat UI under last assistant message
- Implement fuzzy search/filter as user types
- Handle click to copy suggestion to message input field

## New Chat Request Suggestions

[![New chat suggestions](../../docs/images/messageinputfield/new_chat_suggestions.jpg)](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3554-60874&t=vQbeWjQG2QtbTDoL-4)

### Purpose

Help users start new chats and explore topics, OpenMates App skills, and features. Suggestions can include:
- Learning more about specific topics
- Instructions to use app skills (web search, image generation, etc.)
- Instructions to start specific focus modes
- General conversation starters

### Generation Rules

- **Count**: 6 suggestions generated per assistant response
- **Storage**: 50 most recent suggestions stored in pool
- **Display**: 3 randomly selected from the pool
- **Filtering**: Auto-search/filter based on current message input
- **Hide Behavior**: If message input string is not contained in any suggestion, show no suggestions
- **Special Cases**: Always include app skills and focus modes in suggestions (and auto-complete when implemented)

### Example Output

```json
{
    "new_chat_request_suggestions": [
        "Whisper for offline voice notes",
        "Best open-source speech-to-text?",
        "Auto-subtitle local videos",
        "Run AI models on phones?",
        "How is AI optimized for mobile chips?",
        "Learn languages with speech recognition"
    ]
}
```

> New suggestions are added to the top of the user's `new_chat_request_suggestions` list, and only the first 50 are kept.

### Frontend Integration

**Planned Frontend**: To be stored and managed in [`frontend/packages/ui/src/services/db.ts`](../../frontend/packages/ui/src/services/db.ts)

- Receive suggestions from post-processing via WebSocket
- Add to top of existing `new_chat_request_suggestions` list
- Keep only first 50 suggestions
- Display 3 random suggestions in welcome message
- Implement fuzzy search/filter as user types
- Handle click to copy suggestion to message input field

## Additional Post-Processing Outputs

For complete context, post-processing also generates:

- **[Chat Summary](./message_processing.md#chat-summary)**: 2-3 sentence summary for context
- **[Chat Tags](./message_processing.md#chat-tags)**: Max 10 tags for categorization
- **harmful_response**: Score 0-10 to detect harmful responses and consider reprocessing
- **new_learnings**: (idea phase) Better collect new learnings

## Related Documentation

- **Post-Processing Overview**: See [`message_processing.md#post-processing`](./message_processing.md#post-processing)
- **Chat Summary Details**: See [`message_processing.md#chat-summary`](./message_processing.md#chat-summary)
- **Chat Tags Details**: See [`message_processing.md#chat-tags`](./message_processing.md#chat-tags)
- **Base Instructions**: [`backend/apps/ai/base_instructions.yml`](../../backend/apps/ai/base_instructions.yml)
- **Frontend Handlers**: [`frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts`](../../frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts)
- **Database Layer**: [`frontend/packages/ui/src/services/db.ts`](../../frontend/packages/ui/src/services/db.ts)
