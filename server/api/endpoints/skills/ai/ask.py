################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from server.api.models.skills.ai.skills_ai_ask import AiAskOutput, AiAskInput
from typing import Union, List, Dict, Any
from fastapi.responses import StreamingResponse

# load providers
from server.api.endpoints.skills.ai.providers.claude.ask import ask as ask_claude
from server.api.endpoints.skills.ai.providers.chatgpt.ask import ask as ask_chatgpt


async def ask(
        token: str,
        system: str = "You are a helpful assistant. Keep your answers concise.",
        message: str = None,
        message_history: List[Dict[str, Any]] = None,
        provider: dict = {"name":"claude", "model":"claude-3.5-sonnet"},
        temperature: float = 0.5,
        stream: bool = False,
        cache: bool = False,
        max_tokens: int = 1000,
        stop_sequence: str = None,
        tools: List[dict] = None,
    ) -> Union[AiAskOutput, StreamingResponse]:
    """
    Ask a question to AI
    """

    ai_ask_input = AiAskInput(
        system=system,
        message=message,
        message_history=message_history,
        provider=provider,
        temperature=temperature,
        stream=stream,
        cache=cache,
        max_tokens=max_tokens,
        stop_sequence=stop_sequence,
        tools=tools
    )

    add_to_log("Asking AI ...", module_name="OpenMates | Skills | AI | Ask", color="yellow")

    if ai_ask_input.provider.name == "claude":
        return await ask_claude(token=token, **ai_ask_input.model_dump())
    elif ai_ask_input.provider.name == "chatgpt":
        return await ask_chatgpt(token=token, **ai_ask_input.model_dump())