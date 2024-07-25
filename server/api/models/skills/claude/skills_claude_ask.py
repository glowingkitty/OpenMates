
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

from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


# POST /{team_slug}/skills/claude/ask (ask a question to Claude)

class ClaudeAskInput(BaseModel):
    """This is the model for the incoming parameters for POST /{team_slug}/skills/claude/ask"""
    system_prompt: str = Field("You are a helpful assistant. Keep your answers concise.", title="System prompt", description="The system prompt to use for Claude")
    message: str = Field(..., title="Message", description="How can Claude assist you?") # TODO in future replace with message history
    ai_model: Literal["claude-3.5-sonnet", "claude-3-haiku"] = Field("claude-3.5-sonnet", title="AI Model", description="The model to use for Claude")
    temperature: float = Field(0.5, title="Temperature", description="The randomness of the response", json_schema_extra={"min": 0.0, "max": 1.0})

    # prevent extra fields from being passed to API
    model_config = ConfigDict(extra="forbid")


claude_ask_input_example = {
    "system_prompt": "You are a helpful assistant. Keep your answers concise.",
    "message": "What is the capital of France?",
    "ai_model": "claude-3.5-sonnet",
    "temperature": 0.5
}


class ClaudeAskOutput(BaseModel):
    """This is the model for the output of POST /{team_slug}/skills/claude/ask"""
    response: str = Field(..., description="The response from Claude to the question.")

claude_ask_output_example = {
    "response": "The capital of France is Paris."
}