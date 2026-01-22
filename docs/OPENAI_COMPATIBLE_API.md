# OpenAI-Compatible API Implementation

This document describes the OpenAI-compatible functionality implemented for the OpenMates AI ask skill.

## Overview

The `/skills/ask` endpoint now supports **both** internal and OpenAI formats in a single unified endpoint. It automatically detects the request format and processes accordingly, enabling easy integration with existing OpenAI client libraries while maintaining backward compatibility.

## Endpoint

- **URL**: `POST /skills/ask`
- **Supports**: Both internal format (WebSocket/web app) and OpenAI format (REST API/CLI)
- **Auto-detection**: Automatically determines request format and processes accordingly

## Features

### OpenAI Compatibility
- Standard OpenAI ChatGPT API request/response format
- Support for streaming and non-streaming responses
- Compatible with OpenAI client libraries

### OpenMates Extensions
The API includes additional OpenMates-specific parameters:

- `apps_enabled`: Enable/disable app skills (tools)
- `allowed_apps`: List of specific apps to allow
- `mate_id`: Select specific AI Mate
- `provider`: Preferred provider (e.g., 'openai', 'cerebras', 'anthropic')
- `focus_mode`: Focus mode for specialized responses
- `is_incognito`: Incognito mode (no storage/billing)

### Stateless Design
- No server-side chat storage
- Client provides full conversation history
- Each request is independent
- Privacy-first approach

## Request Format

```json
{
  "messages": [
    {
      "role": "user|assistant|system",
      "content": "string",
      "name": "optional_name"
    }
  ],
  "model": "openmates-ai",
  "stream": false,
  "temperature": 0.7,
  "max_tokens": 1000,
  "top_p": 1.0,
  "frequency_penalty": 0.0,
  "presence_penalty": 0.0,
  "stop": ["stop", "sequences"],

  // OpenMates-specific extensions
  "apps_enabled": true,
  "allowed_apps": ["web", "maps", "news"],
  "mate_id": "research-mate",
  "provider": "cerebras",
  "focus_mode": "research",
  "is_incognito": false
}
```

## Response Format

### Non-streaming Response
```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1677652288,
  "model": "openmates-ai",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello! How can I help you today?"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 15,
    "total_tokens": 25
  }
}
```

### Streaming Response
Server-sent events format:
```
data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1677652288,"model":"openmates-ai","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1677652288,"model":"openmates-ai","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1677652288,"model":"openmates-ai","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

## Implementation Details

### Architecture
1. **Route Registration**: BaseApp automatically registers `/skills/ask/openai` for ask skills
2. **Request Transformation**: OpenAI format → Internal AskSkillRequest format
3. **Processing**: Uses existing Celery-based async processing
4. **Response Transformation**: Internal response → OpenAI format

### Internal Flow
1. Parse and validate OpenAI request
2. Generate required IDs (chat_id, message_id, user_id)
3. Transform messages to internal format
4. Create AskSkillRequest with user preferences
5. Execute via existing Celery task system
6. Stream or return formatted OpenAI response

### Stateless Operation
- Chat ID: `openai-{uuid}` or `incognito`
- User ID: Static `openai-api-user`
- Message ID: `msg-{uuid}`
- No persistence required

## Usage Examples

### OpenAI Format (REST API/CLI)
```bash
# Basic chat with OpenAI format
curl -X POST http://localhost:8001/skills/ask \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ],
    "stream": false
  }'
```

### With OpenMates Features
```bash
# OpenAI format with app skills enabled
curl -X POST http://localhost:8001/skills/ask \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Search for recent AI news and find good restaurants nearby"}
    ],
    "apps_enabled": true,
    "allowed_apps": ["web", "news", "maps"],
    "provider": "cerebras",
    "stream": true
  }'
```

### Internal Format (WebSocket/Web App)
```bash
# Internal format - still works as before
curl -X POST http://localhost:8001/skills/ask \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "web-chat-123",
    "message_id": "msg-456",
    "user_id": "user-789",
    "user_id_hash": "hash-012",
    "message_history": [
      {
        "role": "user",
        "content": "Hello, how are you?",
        "created_at": 1640995200,
        "sender_name": "User",
        "category": null
      }
    ]
  }'
```

## Benefits

1. **Unified Endpoint**: Single `/skills/ask` endpoint handles both formats
2. **Auto-Detection**: Automatically detects and processes request format
3. **Backward Compatible**: Existing WebSocket/web app integration unchanged
4. **Developer Friendly**: Drop-in replacement for OpenAI API
5. **CLI/Package Ready**: Perfect for pip/npm packages
6. **Privacy First**: OpenAI format uses stateless design with no server-side storage
7. **Feature Rich**: Full app skills and embedding support in OpenAI format
8. **Scalable**: Stateless OpenAI format, easy to scale horizontally

## Technical Implementation

### Streaming Architecture
- **Real Streaming**: Uses existing Redis pub/sub infrastructure
- **Per-paragraph Streaming**: Inherits OpenMates' sophisticated streaming capabilities
- **OpenAI SSE Format**: Converts Redis chunks to Server-Sent Events format
- **Task Monitoring**: Monitors Celery task completion via Redis channels

### Response Handling
- **Streaming**: Real-time chunks via `text/plain` SSE format
- **Non-streaming**: Waits for task completion and returns full response
- **Error Handling**: Graceful error responses in OpenAI format

## Limitations

- Authentication not implemented yet (TODO: API keys)
- Rate limiting uses existing internal mechanisms

## Future Enhancements

1. API key authentication system
2. Enhanced rate limiting for API usage
3. Usage analytics and billing integration
4. Extended OpenAI compatibility (function calling, etc.)
5. Performance optimizations