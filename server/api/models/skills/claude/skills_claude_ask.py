################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from typing import Literal, List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field, ConfigDict, model_validator


# POST /{team_slug}/skills/claude/ask (ask a question to Claude)

class ToolUse(BaseModel):
    id: str = Field(..., description="Unique identifier for the tool use")
    name: str = Field(..., description="Name of the tool being used")
    input: Dict[str, Any] = Field(..., description="Input parameters for the tool")

class ToolResult(BaseModel):
    tool_use_id: str = Field(..., description="ID of the corresponding tool use")
    content: str = Field(..., description="Result content from the tool")

class MessageContent(BaseModel):
    type: Literal["text", "image", "tool_use", "tool_result"] = Field(..., description="Type of the message content")
    text: Optional[str] = Field(None, description="Text content of the message")
    source: Optional[Dict[str, str]] = Field(None, description="Source information for image content")
    id: Optional[str] = Field(None, description="ID for tool use content")
    name: Optional[str] = Field(None, description="Name for tool use content")
    input: Optional[Dict[str, Any]] = Field(None, description="Input for tool use content")
    tool_use_id: Optional[str] = Field(None, description="ID of the corresponding tool use for tool result content")
    content: Optional[str] = Field(None, description="Content for tool result")

    @model_validator(mode='after')
    def validate_content(self):
        if self.type == "text" and self.text is None:
            raise ValueError("Text content must be provided for type 'text'")
        if self.type == "image" and self.source is None:
            raise ValueError("Source must be provided for type 'image'")
        if self.type == "tool_use" and (self.id is None or self.name is None or self.input is None):
            raise ValueError("id, name, and input must be provided for type 'tool_use'")
        if self.type == "tool_result" and (self.tool_use_id is None or self.content is None):
            raise ValueError("tool_use_id and content must be provided for type 'tool_result'")
        return self

class MessageItem(BaseModel):
    role: Literal["user", "assistant"] = Field(..., description="Role of the message sender")
    content: Union[str, List[MessageContent]] = Field(..., description="Content of the message")

    @model_validator(mode='after')
    def validate_content(self):
        if isinstance(self.content, str):
            self.content = [MessageContent(type="text", text=self.content)]
        return self

class ToolInputSchema(BaseModel):
    type: Literal["object"] = Field("object", description="Type of the input schema")
    properties: Dict[str, Any] = Field(..., description="Properties of the input schema")
    required: Optional[List[str]] = Field(None, description="List of required properties")

class Tool(BaseModel):
    name: str = Field(..., description="Name of the tool")
    description: Optional[str] = Field(None, description="Description of the tool")
    input_schema: ToolInputSchema = Field(..., description="Input schema for the tool")

class ClaudeAskInput(BaseModel):
    """This is the model for the incoming parameters for POST /{team_slug}/skills/claude/ask"""
    system: str = Field(
        "You are a helpful assistant. Keep your answers concise.",
        title="System prompt",
        description="The system prompt to use for Claude"
    )
    message: Optional[str] = Field(
        None,
        title="Message",
        description="How can Claude assist you?"
    )
    message_history: Optional[List[MessageItem]] = Field(
        None,
        title="Message History",
        description="A list of previous messages in the conversation"
    )
    ai_model: Literal["claude-3.5-sonnet", "claude-3-haiku"] = Field(
        "claude-3.5-sonnet",
        title="AI Model",
        description="The model to use for Claude"
    )
    temperature: float = Field(
        0.5,
        title="Temperature",
        description="The randomness of the response",
        json_schema_extra={"min": 0.0, "max": 1.0}
    )
    stream: bool = Field(
        False,
        title="Stream",
        description="If true, the response will be streamed, otherwise it will be returned as a JSON response."
    )
    max_tokens: Optional[int] = Field(
        None,
        title="Max Tokens",
        description="The maximum number of tokens to generate in the response"
    )
    stop_sequence: Optional[List[str]] = Field(
        None,
        title="Stop Sequence",
        description="A list of sequences where the API will stop generating further tokens"
    )
    tools: Optional[List[Tool]] = Field(
        None,
        title="Tools",
        description="Definitions of tools that the model may use"
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode='after')
    def check_message_or_history(self):
        if self.message != None and self.message_history != None:
            raise ValueError("Only one of 'message' or 'message_history' should be provided.")
        if self.message == None and self.message_history == None:
            raise ValueError("Either 'message' or 'message_history' must be provided.")
        return self

    @model_validator(mode='after')
    def validate_message_history(self):
        if self.message_history:
            if len(self.message_history) == 0:
                raise ValueError("Message history must not be empty")
            last_message = self.message_history[-1]
            if last_message.role == "assistant" and not last_message.content:
                raise ValueError("The last assistant message in the history must not be empty")
        return self


claude_ask_input_example = {
    "system": "You are a helpful assistant. Keep your answers short.",
    "message": "Whats the capital of Germany?",
    "ai_model": "claude-3-haiku"
}

claude_ask_input_example_2 = {
    "system": "You are a helpful assistant. Keep your answers short.",
    "message": "What's the current stock price of Apple?",
    "ai_model": "claude-3-haiku",
    "temperature": 0.5,
    "max_tokens": 150,
    "tools": [
        {
            "name": "get_stock_price",
            "description": "Get the current stock price for a given ticker symbol.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "The stock ticker symbol, e.g. AAPL for Apple Inc."
                    }
                },
                "required": ["ticker"]
            }
        },
        {
            "name": "get_weather",
            "description": "Get the current weather for a given location.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and state or country, e.g. 'New York, NY' or 'London, UK'"
                    }
                },
                "required": ["location"]
            }
        }
    ]
}

claude_ask_input_example_3 = {
    "system": "You are a helpful assistant. Keep your answers short. Use tools only when clearly asked. Else, answer with your knowledge.",
    "message_history": [
        {
            "role": "user",
            "content": "What's the current stock price of Apple?"
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_01WjKuTw9s9UMVyyET2UE4GB",
                    "name": "get_stock_price",
                    "input": {
                        "ticker": "AAPL"
                    }
                }
            ]
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_01WjKuTw9s9UMVyyET2UE4GB",
                    "content": "$150.25"
                }
            ]
        }
    ],
    "ai_model": "claude-3-haiku",
    "temperature": 0.5,
    "tools": [
        {
            "name": "get_stock_price",
            "description": "Get the current stock price for a given ticker symbol.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "The stock ticker symbol, e.g. AAPL for Apple Inc."
                    }
                },
                "required": ["ticker"]
            }
        },
        {
            "name": "get_weather",
            "description": "Get the current weather for a given location.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and state or country, e.g. 'New York, NY' or 'London, UK'"
                    }
                },
                "required": ["location"]
            }
        }
    ]
}

claude_ask_input_example_4 = {
    "system": "You are a helpful assistant. Analyze images and answer questions about them.",
    "message_history": [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": "/9j/4AAQSkZJRg..."
                    }
                },
                {
                    "type": "text",
                    "text": "What's in this image?"
                }
            ]
        }
    ]
}


class ContentItem(BaseModel):
    type: Literal["text", "tool_use", "tool_result"] = Field(..., description="Type of the content item")
    text: Optional[str] = Field(None, description="Text content")
    tool_use: Optional[Dict[str, Any]] = Field(None, description="Tool use information")
    tool_result: Optional[Dict[str, Any]] = Field(None, description="Tool result information")

class Usage(BaseModel):
    input_tokens: int = Field(..., description="Number of input tokens")
    output_tokens: int = Field(..., description="Number of output tokens")

class ClaudeAskOutput(BaseModel):
    """This is the model for the output of POST /{team_slug}/skills/claude/ask"""
    content: List[ContentItem] = Field(..., description="The response content from Claude to the question.")
    usage: Usage = Field(..., description="Token usage information")

claude_ask_output_example = {
    "content": [
        {
            "type": "text",
            "text": "The capital city of Germany is Berlin."
        }
    ],
    "usage": {
        "input_tokens": 26,
        "output_tokens": 11
    }
}

claude_ask_output_example_2 = {
    "content": [
        {
            "type": "tool_use",
            "tool_use": {
                "id": "toolu_0125cE39s6tPfDUcKwpPmn9i",
                "name": "get_stock_price",
                "input": {
                    "ticker": "AAPL"
                }
            }
        }
    ],
    "usage": {
        "input_tokens": 459,
        "output_tokens": 58
    }
}

claude_ask_output_example_3 = {
    "content": [
        {
            "type": "text",
            "text": "The current stock price for Apple (ticker symbol AAPL) is $150.25."
        }
    ],
    "usage": {
        "input_tokens": 548,
        "output_tokens": 24
    }
}

claude_ask_output_example_4 = {
    "content": [
        {
            "type": "text",
            "text": "The image shows a small yellow boat on the open ocean, from the top view."
        }
    ],
    "usage": {
        "input_tokens": 230,
        "output_tokens": 17
    }
}