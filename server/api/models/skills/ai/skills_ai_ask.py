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

# class ContentStreamData(BaseModel):
#     text: str = Field(..., description="Text content of the stream event")

# class ToolUseData(BaseModel):
#     name: str = Field(..., description="Name of the tool being used")
#     input: Dict[str, Any] = Field(..., description="Input parameters for the tool")

# class StreamEvent(BaseModel):
#     event: Literal["content", "tool_use", "stream_end"] = Field(..., description="Type of streaming event")
#     data: Optional[Union[ContentStreamData, ToolUseData]] = Field(None, description="Event data")

# class ContentStreamEvent(StreamEvent):
#     event: Literal["content"] = "content"
#     data: ContentStreamData

# class ToolUseStreamEvent(StreamEvent):
#     event: Literal["tool_use"] = "tool_use"
#     data: ToolUseData

# class StreamEndEvent(StreamEvent):
#     event: Literal["stream_end"] = "stream_end"
#     data: None = None

class ToolUse(BaseModel):
    id: str = Field(..., title="ID", description="Unique identifier for the tool use")
    name: str = Field(..., title="Name", description="Name of the tool being used")
    input: Dict[str, Any] = Field(..., title="Input", description="Input parameters for the tool")

class ToolResult(BaseModel):
    tool_use_id: str = Field(..., title="Tool Use ID", description="ID of the corresponding tool use")
    content: str = Field(..., title="Content", description="Result content from the tool")

class MessageContent(BaseModel):
    type: Literal["text", "image", "tool_use", "tool_result"] = Field(..., title="Type", description="Type of the message content")
    text: Optional[str] = Field(None, title="Text", description="Text content of the message")
    source: Optional[Dict[str, str]] = Field(None, title="Source", description="Source information for image content")
    id: Optional[str] = Field(None, title="ID", description="ID for tool use content")
    name: Optional[str] = Field(None, title="Name", description="Name for tool use content")
    input: Optional[Dict[str, Any]] = Field(None, title="Input", description="Input for tool use content")
    tool_use_id: Optional[str] = Field(None, title="Tool Use ID", description="ID of the corresponding tool use for tool result content")
    content: Optional[str] = Field(None, title="Content", description="Content for tool result")

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
    role: Literal["user", "assistant"] = Field(..., title="Role", description="Role of the message sender")
    content: Union[str, List[MessageContent]] = Field(..., title="Content", description="Content of the message")

    @model_validator(mode='after')
    def validate_content(self):
        if isinstance(self.content, str):
            self.content = [MessageContent(type="text", text=self.content)]
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content if isinstance(self.content, str) else [
                content.model_dump(exclude_none=True) for content in self.content
            ]
        }

class ToolInputSchema(BaseModel):
    type: Literal["object"] = Field("object", title="Type", description="Type of the input schema")
    properties: Dict[str, Any] = Field(..., title="Properties", description="Properties of the input schema")
    required: Optional[List[str]] = Field(None, title="Required", description="List of required properties")

class Tool(BaseModel):
    name: str = Field(..., title="Name", description="Name of the tool")
    description: Optional[str] = Field(None, title="Description", description="Description of the tool")
    input_schema: ToolInputSchema = Field(..., title="Input Schema", description="Input schema for the tool")

class ContentItem(BaseModel):
    type: Literal["text", "tool_use", "tool_result"] = Field(..., title="Type", description="Type of the content item")
    text: Optional[str] = Field(None, title="Text", description="Text content")
    tool_use: Optional[ToolUse] = Field(None, title="Tool Use", description="Tool use information")
    tool_result: Optional[ToolResult] = Field(None, title="Tool Result", description="Tool result information")

    @model_validator(mode='after')
    def remove_none_fields(cls, values):
        return {k: v for k, v in values.model_dump().items() if v is not None}

class AiProvider(BaseModel):
    name: Literal["claude", "chatgpt"] = Field(..., title="Provider Name", description="Name of the AI provider")
    model: Literal["claude-3.5-sonnet","claude-3-haiku","gpt-4o","gpt-4o-mini"] = Field(..., title="Model", description="Specific model of the AI provider")

    @model_validator(mode='after')
    def validate_model(self):
        valid_models = {
            "claude": ["claude-3.5-sonnet", "claude-3-haiku"],
            "chatgpt": ["gpt-4o", "gpt-4o-mini"]
        }
        if self.name not in valid_models:
            raise ValueError(f"Invalid provider: {self.name}")
        if self.model not in valid_models[self.name]:
            raise ValueError(f"Invalid model '{self.model}' for provider '{self.name}'. Valid models are: {', '.join(valid_models[self.name])}")
        return self

class AiAskInput(BaseModel):
    """This is the model for the incoming parameters for POST /{team_slug}/skills/ai/ask"""
    system: str = Field(
        "You are a helpful assistant. Keep your answers concise.",
        title="System prompt",
        description="The system prompt to use for the AI"
    )
    message: Optional[str] = Field(
        None,
        title="Message",
        description="How can the AI assist you?"
    )
    message_history: Optional[List[MessageItem]] = Field(
        None,
        title="Message History",
        description="A list of previous messages in the conversation"
    )
    provider: AiProvider = Field(
        ...,
        title="AI Provider",
        description="The AI provider and model to use"
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
    cache: bool = Field(
        False,
        title="Cache",
        description="If true, prompt caching will be used. Available currently for 'Claude' only."
    )
    max_tokens: Optional[int] = Field(
        2000,
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
    def check_cache_available(self):
        if self.cache and self.provider.name != "claude":
            raise ValueError("Cache is only available for 'Claude'.")
        return self

    @model_validator(mode='after')
    def check_message_or_history(self):
        if self.message is not None and self.message_history is not None:
            raise ValueError("Only one of 'message' or 'message_history' should be provided.")
        if self.message is None and self.message_history is None:
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


class AiAskOutput(BaseModel):
    """This is the model for the output of POST /{team_slug}/skills/ai/ask"""
    content: Union[str, List[ContentItem]] = Field(..., title="Content", description="The response content from the AI to the question.")
    cost_credits: Optional[int] = Field(None, title="Cost in credits", description="Total cost of the request in credits")


class AiAskOutputStream(BaseModel):
    content: Optional[ContentItem] = Field(..., title="Content", description="The response content from the AI to the question.")
    cost_credits: Optional[int] = Field(None, title="Cost in credits", description="Total cost of the request in credits")
    stream_end: Optional[bool] = Field(None, title="Stream end", description="If true, the stream has ended")

ai_ask_input_example = {
    "system": "You are a helpful assistant. Keep your answers short.",
    "message": "What's the capital of Germany?",
    "provider": {
        "name": "claude",
        "model": "claude-3-haiku"
    },
    "temperature": 0.5
}

ai_ask_input_example_2 = {
    "system": "You are a helpful assistant. Keep your answers short.",
    "message": "What's the current stock price of Apple?",
    "provider": {
        "name": "claude",
        "model": "claude-3-haiku"
    },
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

ai_ask_input_example_3 = {
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
    "provider": {
        "name": "claude",
        "model": "claude-3-haiku"
    },
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

ai_ask_input_example_4 = {
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
    ],
    "provider": {
        "name": "claude",
        "model": "claude-3-haiku"
    }
}

ai_ask_input_example_5 = {
    "system": "You are a helpful assistant. Keep your answers concise.",
    "message":"Explain to me how dragonfly works for caching in python and give me a code example.",
    "stream":True,
    "provider": {
        "name":"claude",
        "model":"claude-3-haiku"
    }
}

ai_ask_output_example = {
    "content": [
        {
            "type": "text",
            "text": "The capital city of Germany is Berlin."
        }
    ],
    "cost_credits": 1
}

ai_ask_output_example_2 = {
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
    "cost_credits": 2
}

ai_ask_output_example_3 = {
    "content": [
        {
            "type": "text",
            "text": "The current stock price for Apple (ticker symbol AAPL) is $150.25."
        }
    ],
    "cost_credits": 3
}

ai_ask_output_example_4 = {
    "content": [
        {
            "type": "text",
            "text": "The image shows a small yellow boat on the open ocean, from the top view."
        }
    ],
    "cost_credits": 3
}

ai_ask_output_example_5 = [
    {"event":"content","data":{"text":"Dragonfly is a caching library for Python that provides a simple and efficient way to cache the results of expensive function calls. It allows you to cache the results of a function based on its input parameters, and it can automatically invalidate the cache when the function's dependencies change.\n\n"}},
    {"event":"content","data":{"text":"Here\n's a simple example of how to use Dragonfly for caching in Python:\n\n"}},
    {"event":"content","data":{"text":"```python\n\nfrom dragonfly import cache\n\n@cache\ndef fibonacci(n):\n    if n <= 1:\n        return n\n    else:\n        return(fibonacci(n-1) + fibonacci(n-2))\n\nprint(fibonacci(10))  # Output: 55\nprint(fibonacci(10))  # Output: 55 (cached)\n```\n\n"}},
    {"event":"content","data":{"text":"In this\n example, we define a `fibonacci` function that calculates the nth Fibonacci number. We use the `@cache` decorator from the Dragonfly library to cache the results of this function.\n\n"}},
    {"event":"content","data":{"text":"When\n we first call the `fibonacci` function with an argument of `10`, the function is executed and the result is cached. When we call the function again with the same argument, the cached result is returned instead of recalculating the value.\n\n"}},
    {"event":"content","data":{"text":"Dragonfly also\n supports more advanced caching features, such as:\n\n"}},
    {"event":"content","data":{"text":"- Exp\niration: You can set a time-to-live (TTL) for cached values, after which they will be automatically invalidated.\n"}},
    {"event":"content","data":{"text":"- Dependencies\n: You can specify dependencies for a cached function, so that the cache is invalidated when the dependencies change.\n- Memoization: Dragonfly can automatically memoize the results of a function based on its input parameters.\n"}},
    {"event":"content","data":{"text":"- Distribute\nd caching: Dragonfly can be used to cache results across multiple processes or machines using a distributed cache backend, such as Redis or Memcached.\n\n"}},
    {"event":"content","data":{"text":"Here's\n an example of using Dragonfly with dependencies:\n\n"}},
    {"event":"content","data":{"text":"```python\n\nfrom dragonfly import cache\n\n@cache(dependencies=['data.txt'])\ndef load_data():\n    with open('data.txt', 'r') as f:\n        return f.read()\n\nprint(load_data())  # Output: the contents of data.txt\n# Modify data.txt\nprint(load_data())  # Output: the updated contents of data.txt (cache invalidated)\n```\n\n"}},
    {"event":"content","data":{"text":"In this\n example, we use the `dependencies` parameter of the `@cache` decorator to specify that the `load_data` function depends on the `data.txt` file. If the contents of `data.txt` change, the cached result will be invalidated and the function will be called again to load the updated data."}},
    {"event":"stream_end","data":None}
]