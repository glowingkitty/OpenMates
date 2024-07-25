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
from pydantic import BaseModel, Field, ConfigDict, validator


# POST /{team_slug}/skills/claude/ask (ask a question to Claude)

class MessageContent(BaseModel):
    type: Literal["text", "image"]
    text: Optional[str] = None
    source: Optional[Dict[str, str]] = None

class MessageItem(BaseModel):
    role: Literal["user", "assistant"]
    content: Union[str, List[MessageContent]]

class ClaudeAskInput(BaseModel):
    """This is the model for the incoming parameters for POST /{team_slug}/skills/claude/ask"""
    system_prompt: str = Field("You are a helpful assistant. Keep your answers concise.", title="System prompt", description="The system prompt to use for Claude")
    message: Optional[str] = Field(None, title="Message", description="How can Claude assist you?")
    message_history: Optional[List[MessageItem]] = Field(None, title="Message History", description="A list of previous messages in the conversation")
    ai_model: Literal["claude-3.5-sonnet", "claude-3-haiku"] = Field("claude-3.5-sonnet", title="AI Model", description="The model to use for Claude")
    temperature: float = Field(0.5, title="Temperature", description="The randomness of the response", json_schema_extra={"min": 0.0, "max": 1.0})
    stream: bool = Field(False, title="Stream", description="Whether to stream the response")

    # prevent extra fields from being passed to API
    model_config = ConfigDict(extra="forbid")

    @validator('message', 'message_history')
    def check_message_or_history(cls, v, values, **kwargs):
        if 'message' in values and 'message_history' in values:
            if values['message'] is not None and values['message_history'] is not None:
                raise ValueError("Only one of 'message' or 'message_history' should be provided.")
        if v is None and ('message' not in values or values['message'] is None) and ('message_history' not in values or values['message_history'] is None):
            raise ValueError("Either 'message' or 'message_history' must be provided.")
        return v

claude_ask_input_example = {
    "system_prompt": "You are a helpful assistant. Keep your answers concise.",
    "message": "What is the capital of France?",
    "ai_model": "claude-3.5-sonnet",
    "temperature": 0.5,
    "stream": False
}


class ClaudeAskOutput(BaseModel):
    """This is the model for the output of POST /{team_slug}/skills/claude/ask"""
    response: str = Field(..., description="The response from Claude to the question.")

claude_ask_output_example = {
    "response": "The capital of France is Paris."
}