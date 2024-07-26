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

# TODO improve documentation
# TODO add example in docs with message and all fields in use
class MessageContent(BaseModel):
    type: Literal["text", "image"]
    text: Optional[str] = None
    source: Optional[Dict[str, str]] = None

    @model_validator(mode='after')
    def validate_content(self):
        if self.type == "text" and self.text is None:
            raise ValueError("Text content must be provided for type 'text'")
        if self.type == "image" and self.source is None:
            raise ValueError("Source must be provided for type 'image'")
        if self.type == "image" and self.source:
            if "type" not in self.source or self.source["type"] != "base64":
                raise ValueError("Image source type must be 'base64'")
            if "media_type" not in self.source or self.source["media_type"] not in ["image/jpeg", "image/png"]:
                raise ValueError("Image media_type must be 'image/jpeg' or 'image/png'")
            if "data" not in self.source:
                raise ValueError("Image data must be provided")
        return self

class MessageItem(BaseModel):
    role: Literal["user", "assistant"]
    content: Union[str, List[MessageContent]]

    @model_validator(mode='after')
    def validate_content(self):
        if isinstance(self.content, str):
            self.content = [MessageContent(type="text", text=self.content)]
        return self

class ClaudeAskInput(BaseModel):
    """This is the model for the incoming parameters for POST /{team_slug}/skills/claude/ask"""
    system_prompt: str = Field("You are a helpful assistant. Keep your answers concise.", title="System prompt", description="The system prompt to use for Claude")
    message: Optional[str] = Field(None, title="Message", description="How can Claude assist you?")
    message_history: Optional[List[MessageItem]] = Field(None, title="Message History", description="A list of previous messages in the conversation")
    ai_model: Literal["claude-3.5-sonnet", "claude-3-haiku"] = Field("claude-3.5-sonnet", title="AI Model", description="The model to use for Claude")
    temperature: float = Field(0.5, title="Temperature", description="The randomness of the response", json_schema_extra={"min": 0.0, "max": 1.0})
    stream: bool = Field(False, title="Stream", description="If true, the response will be streamed, otherwise it will be returned as a JSON response.")

    # prevent extra fields from being passed to API
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
    "system_prompt":"You are a helpful assistant. Keep your answers short.",
    "message": "What is the capital city of Germany?",
    "ai_model":"claude-3-haiku",
    "temperature": 0.5,
    "stream": False
}


class ClaudeAskOutput(BaseModel):
    """This is the model for the output of POST /{team_slug}/skills/claude/ask"""
    response: str = Field(..., description="The response from Claude to the question.")
    token_usage: Dict[str, Any] = Field(..., description="The token usage for the request")

claude_ask_output_example = {
    "response": "The capital city of Germany is Berlin.",
    "token_usage": {
        "input_tokens": 26,
        "output_tokens": 11
    }
}