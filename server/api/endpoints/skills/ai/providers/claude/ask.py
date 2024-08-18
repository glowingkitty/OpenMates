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
from server.api.models.skills.ai.skills_ai_ask import AiAskOutput, AiAskInput
from typing import Literal, Union, List, Dict, Any
from fastapi.responses import StreamingResponse
from anthropic.types import ContentBlock, TextBlock, ToolUseBlock

def serialize_content_block(block: ContentBlock) -> Dict[str, Any]:
    result = {"type": block.type}
    if isinstance(block, TextBlock):
        result["text"] = block.text
    elif isinstance(block, ToolUseBlock):
        result["tool_use"] = {
            "id": block.id,
            "name": block.name,
            "input": block.input
        }
    return result

async def ask(
        token: str,
        message: str = None,
        message_history: List[Dict[str, Any]] = None,
        tools: List[dict] = None,
        system: str = "You are a helpful assistant. Keep your answers concise.",
        ai_model: Literal["claude-3.5-sonnet", "claude-3-haiku"] = "claude-3.5-sonnet",
        temperature: float = 0.5,
        stream: bool = False,
        cache: bool = False,
        max_tokens: int = 1000,
        stop_sequence: str = None
    ) -> Union[AiAskOutput, StreamingResponse]:
    """
    Ask a question to Claude
    """

    ai_ask_input = AiAskInput(
        system=system,
        message=message,
        message_history=message_history,
        provider={
            "name": "claude",
            "model": ai_model
        },
        temperature=temperature,
        stream=stream,
        cache=cache,
        max_tokens=max_tokens,
        stop_sequence=stop_sequence,
        tools=tools
    )

    # TODO check for user api key or billing / enough credits

    add_to_log("Asking Claude ...", module_name="OpenMates | Skills | Claude | Ask", color="yellow")

    # Select a more specific model
    if ai_ask_input.provider.model == "claude-3.5-sonnet":
        ai_model = "claude-3-5-sonnet-20240620"
    elif ai_ask_input.provider.model == "claude-3-haiku":
        ai_model = "claude-3-haiku-20240307"

    # Define common configuration
    message_config = {
        "model": ai_model,
        "max_tokens": ai_ask_input.max_tokens,
        "system": ai_ask_input.system,
        "messages": ai_ask_input.message_history if ai_ask_input.message_history else [{"role": "user", "content": ai_ask_input.message}],
        "temperature": ai_ask_input.temperature
    }

    if ai_ask_input.tools:
        message_config["tools"] = ai_ask_input.tools
        message_config["tool_choice"] = {"type": "auto"}

    # Send request to Claude to get a response
    load_dotenv()
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    if ai_ask_input.stream:
        async def event_stream():
            with client.messages.stream(**message_config) as stream:
                for text in stream.text_stream:
                    yield f"data: {text}\n\n"
                yield "event: stream_end\ndata: Stream ended\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    else:
        response = client.messages.create(**message_config)

        # TODO calculate cost, based on token usage
        cost_credits = None
        return AiAskOutput(
            content=[serialize_content_block(block) for block in response.content],
            cost_credits=cost_credits
        )