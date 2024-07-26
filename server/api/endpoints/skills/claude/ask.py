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

from anthropic import Anthropic
from dotenv import load_dotenv
from server.api.models.skills.claude.skills_claude_ask import ClaudeAskOutput
from typing import Literal, Union, List, Dict, Any
from pydantic import Field, validator
from fastapi.responses import StreamingResponse


async def ask(
        token: str,
        message: str = None,
        message_history: List[Dict[str, Any]] = None,
        system_prompt: str = "You are a helpful assistant. Keep your answers concise.",
        ai_model: Literal["claude-3.5-sonnet", "claude-3-haiku"] = "claude-3.5-sonnet",
        temperature: float = 0.5,
        stream: bool = False
    ) -> Union[ClaudeAskOutput, StreamingResponse]:
    """
    Ask a question to Claude
    """

    # TODO check for user api key or billing / enough credits

    if ai_model not in ["claude-3.5-sonnet", "claude-3-haiku"]:
        raise ValueError("Invalid AI model. Please select 'claude-3.5-sonnet' or 'claude-3-haiku'.")

    if message is None and message_history is None:
        raise ValueError("Either 'message' or 'message_history' must be provided.")

    if message is not None and message_history is not None:
        raise ValueError("Only one of 'message' or 'message_history' should be provided.")

    add_to_log("Asking Claude ...", module_name="OpenMates | Skills | Claude | Ask", color="yellow")

    # Select a more specific model
    if ai_model == "claude-3.5-sonnet":
        ai_model = "claude-3-5-sonnet-20240620"
    elif ai_model == "claude-3-haiku":
        ai_model = "claude-3-haiku-20240307"

    # Define common configuration
    message_config = {
        "model": ai_model,
        "max_tokens": 1000,
        "system": system_prompt,
        "messages": message_history if message_history else [{"role": "user", "content": message}],
        "temperature": temperature
    }

    # TODO implement other missing parameters, including tools, from https://docs.anthropic.com/en/api/messages

    # Send request to Claude to get a response
    load_dotenv()
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    if stream:
        async def event_stream():
            with client.messages.stream(**message_config) as stream:
                for text in stream.text_stream:
                    yield f"data: {text}\n\n"
                yield "event: stream_end\ndata: Stream ended\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    else:
        response = client.messages.create(**message_config)
        return {
            "response": response.content[0].text,
            "token_usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            }
        }