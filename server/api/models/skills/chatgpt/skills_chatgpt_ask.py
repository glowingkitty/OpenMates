
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


# POST /{team_slug}/skills/chatgpt/ask (ask a question to ChatGPT)

class ChatGPTAskInput(BaseModel):
    """This is the model for the incoming parameters for POST /{team_slug}/skills/chatgpt/ask"""
    system_prompt: str = Field("You are a helpful assistant. Keep your answers concise.", title="System prompt", description="The system prompt to use for ChatGPT")
    message: str = Field(..., title="Message", description="How can ChatGPT assist you?") # TODO in future replace with message history
    ai_model: Literal["openai__gpt-4o", "openai__gpt-3.5-turbo"] = Field("openai__gpt-4o", title="AI Model", description="The model to use for ChatGPT")
    temperature: float = Field(0.5, title="Temperature", description="The randomness of the response", min=0.0, max=2.0)

    # prevent extra fields from being passed to API
    model_config = ConfigDict(extra="forbid")


chatgpt_ask_input_example = {
    "system_prompt": "You are a helpful assistant. Keep your answers concise.",
    "message": "What is the capital of France?",
    "ai_model": "openai__gpt-4o",
    "temperature": 0.5
}


class ChatGPTAskOutput(BaseModel):
    """This is the model for the output of POST /{team_slug}/skills/chatgpt/ask"""
    response: str = Field(..., description="The response from ChatGPT to the question.")

chatgpt_ask_output_example = {
    "response": "The capital of France is Paris."
}