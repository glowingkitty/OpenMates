# Function Calling Architecture

Function calling enables the LLM to trigger app skills and focus modes during conversations. This document explains how function calling integrates with the OpenMates apps architecture.

## Overview

When a user sends a message, the LLM analyzes the request and can decide to call specific functions (skills) or activate focus modes. This happens automatically based on conversation context and available tools.

**Key Concepts:**

- **Tools**: Function definitions that the LLM can call
- **Function Calls**: When the LLM decides to execute a skill or activate a focus mode
- **Tool Definitions**: Schemas that describe available skills and their parameters
- **Integration**: How function calling fits into the message processing pipeline

## Integration with Message Processing

Function calling is integrated into the main processing stage. See [Message Processing Architecture](../message_processing.md#main-processing) for the complete flow.

**Flow:**

1. User sends a message
2. Pre-processing analyzes the request and preselects relevant tools
3. Main processing begins with the selected LLM model
4. LLM receives preselected tools (skills and focus modes)
5. LLM decides whether to call functions based on user request
6. Function calls are executed (skills run, focus modes activate)
7. Results are incorporated into the assistant's response

## Tool Definitions

Tools are defined based on apps available to the current mate. Each app's `app.yml` file defines its skills, which are automatically converted into tool definitions.

**Implementation:** Tool definitions are dynamically generated from app metadata. See [`backend/apps/ai/processing/main_processor.py`](../../backend/apps/ai/processing/main_processor.py) for tool generation logic. Only skills with `stage: "production"` are exposed as tools.

### Tool Naming

Tools use the format `{app_id}-{skill_id}` for clear identification and routing:

- **Function Name**: `{app_id}-{skill_id}` (e.g., `web-search`, `videos-get_transcript`, `images-generate`)
- **App ID**: Lowercase app identifier (e.g., `web`, `videos`, `images`)
- **Skill ID**: Lowercase skill identifier (e.g., `search`, `get_transcript`, `generate`)

This format ensures unambiguous routing to the correct app and skill while maintaining compatibility with LLM tool calling standards (hyphens are required by some providers like Cerebras).

**Tool Structure:**

```json
{
  "type": "function",
  "function": {
    "name": "web-search",
    "description": "Search the web for information using Brave Search API",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "The search query"
        }
      },
      "required": ["query"]
    }
  }
}
```

### Skill Tools

Each production-stage skill becomes a tool. Tool schemas are generated from Pydantic models defined in each skill class. See [`backend/apps/base_skill.py`](../../backend/apps/base_skill.py) for the base skill implementation.

### Focus Mode Tools

Focus modes are exposed as tools, allowing the LLM to activate them when appropriate. When called, a focus mode activates for the current chat session, modifying the system prompt for subsequent messages.

## Tool Preselection

**Status**: Implemented when apps are implemented

To support scaling to many apps with many skills, tool preselection filters tools during pre-processing to only include those relevant to the current request.

**How It Works:**

1. **Pre-Processing Input**: A simplified overview is provided to the preprocessing LLM (see [`backend/apps/ai/processing/preprocessor.py`](../../backend/apps/ai/processing/preprocessor.py)):

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

2. **Pre-Processing Output**: The preprocessing LLM analyzes the user request and outputs (see [`backend/apps/ai/base_instructions.yml`](../../backend/apps/ai/base_instructions.yml) for the tool definition):
   - `relevant_app_skills`: List of skill identifiers in format `app_id-skill_id` (e.g., `["web-search", "videos-get_transcript"]`)
   - `relevant_app_focus_modes`: List of focus mode identifiers in format `app_id-focus_mode_id` (e.g., `["web-research"]`)
   - `relevant_app_settings_and_memories`: List of settings/memories in format `app_id-item_key` (e.g., `["travel-upcoming_trips"]`)

3. **Validation**: For each preselected tool (see [`backend/apps/ai/processing/main_processor.py`](../../backend/apps/ai/processing/main_processor.py)):
   - Verify it exists and is available
   - Check user preferences (if user has deactivated it)
   - Load full tool definition only for validated tools

4. **Main Processing**: Only preselected tools are included in the main processing request

**Benefits:**

- **Scalability**: System can handle hundreds of skills without performance issues
- **Efficiency**: Reduces token usage dramatically
- **Accuracy**: LLM receives focused tool set, improving decision quality
- **Privacy**: Only relevant app settings/memories are requested from client

For implementation details, see [Message Processing Architecture](../message_processing.md#tool-preselection).

## How the LLM Decides

The LLM uses several factors to decide which tools to call:

1. **User Intent**: What is the user trying to accomplish?
2. **Available Tools**: What skills and focus modes are available?
3. **Context**: What has been discussed in the conversation?
4. **Tool Descriptions**: Clear descriptions help the LLM understand when to use each tool

**System Instructions:**

The main processing system prompt includes instructions about when to use app skills, how to decide between different skills, when to activate focus modes, and how to combine multiple skills for complex requests.

These instructions are defined in [`backend/apps/ai/base_instructions.yml`](../../backend/apps/ai/base_instructions.yml).

## Function Call Execution

### Skill Execution

1. **Parse Function Call**: Extract app ID and skill ID from function name (e.g., `web-search` → `app_id: "web"`, `skill_id: "search"`)
2. **Route to App**: Identify which app handles the skill using the app ID
3. **Execute Skill**: Call the skill's execute method
4. **Handle Response**: Process results and incorporate into response

**Multiple Requests:**

Skills can handle multiple requests in a single call (up to 9 parallel requests). Each request creates a separate Celery task for parallel processing. See [App Skills Architecture](./app_skills.md#multiple-requests-per-skill-call) for details.

### Focus Mode Activation

1. **Parse Function Call**: Extract app ID and focus mode ID from function name (e.g., `web.research` → `app_id: "web"`, `focus_mode_id: "research"`)
2. **Update Chat State**: Activate focus mode for the chat
3. **Modify System Prompt**: Include focus mode instructions in subsequent messages
4. **Confirm Activation**: Assistant confirms focus mode is active

## Error Handling

When function calls fail, the system detects errors, provides error details to the LLM, allows retry with different parameters, and can fall back to responding without the function call if needed. Errors are communicated clearly to users with explanations and alternative approaches.

## Configuration

Function calling behavior is configured in:

- **Base Instructions**: [`backend/apps/ai/base_instructions.yml`](../../backend/apps/ai/base_instructions.yml) - Instructions for when to use tools
- **App Metadata**: Each app's `app.yml` file - Skill and focus mode definitions
- **Main Processor**: [`backend/apps/ai/processing/main_processor.py`](../../backend/apps/ai/processing/main_processor.py) - Tool generation and execution
- **Pre-Processor**: [`backend/apps/ai/processing/preprocessor.py`](../../backend/apps/ai/processing/preprocessor.py) - Tool preselection logic

## Related Documentation

- [Message Processing Architecture](../message_processing.md) - Complete message processing pipeline
- [App Skills Architecture](./app_skills.md) - Detailed skill implementation
- [Focus Modes](./focus_modes.md) - User-facing focus mode documentation
- [REST API Architecture](../rest_api.md) - Programmatic API access
- [Apps Architecture](./README.md) - Overview of apps, skills, and focus modes
