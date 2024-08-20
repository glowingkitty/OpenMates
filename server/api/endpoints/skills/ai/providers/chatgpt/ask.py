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

from openai import OpenAI
from dotenv import load_dotenv
from server.api.models.skills.ai.skills_ai_ask import AiAskOutput, AiAskInput
from typing import Literal, Union, List, Dict, Any
from fastapi.responses import StreamingResponse
import json

def serialize_content_block(block: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": block["type"],
        "text": block.get("text", ""),
        "tool_calls": block.get("tool_calls", [])
    }

async def ask(
        token: str,
        system: str = "You are a helpful assistant. Keep your answers concise.",
        message: str = None,
        message_history: List[Dict[str, Any]] = None,
        provider: dict = {"name":"chatgpt", "model":"gpt-4o"},
        temperature: float = 0.5,
        stream: bool = False,
        cache: bool = False,
        max_tokens: int = 1000,
        stop_sequence: str = None,
        tools: List[dict] = None
    ) -> Union[AiAskOutput, StreamingResponse]:
    """
    Ask a question to ChatGPT
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

    add_to_log("Asking ChatGPT ...", module_name="OpenMates | Skills | ChatGPT | Ask", color="yellow")


    # # TODO implement check for user key / balance
    # user = get_user(token=token)

    # # Get the estimated minimum cost of the skill
    # estimated_minimum_cost = get_skill_costs(
    #     software="chatgpt",
    #     skill="ask",
    #     token_count=count_tokens(system+message)+200 # assumming 200 tokens for the response
    # )

    # # Get the api credentials for ChatGPT
    # api_credentials = get_api_credentials(
    #     user=user,
    #     software="chatgpt",
    #     api_credentials="default",
    #     costs_eur=estimated_minimum_cost
    # )

    # # Send request to ChatGPT to get a response
    # client = OpenAI(api_key=api_credentials["api_key"])

    # Send request to ChatGPT to get a response
    load_dotenv()
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    messages = [{"role": "system", "content": ai_ask_input.system}]
    if ai_ask_input.message_history:
        messages.extend(ai_ask_input.message_history)
    else:
        messages.append({"role": "user", "content": ai_ask_input.message})

    # Define common configuration
    chat_config = {
        "model": ai_ask_input.provider.model,
        "messages": messages,
        "temperature": ai_ask_input.temperature,
        "max_tokens": ai_ask_input.max_tokens,
        "stream": ai_ask_input.stream
    }

    if ai_ask_input.tools:
        chat_config["tools"] = ai_ask_input.tools
        chat_config["tool_choice"] = "auto"

    if ai_ask_input.stream:
        async def event_stream():
            stream = client.chat.completions.create(**chat_config)
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield f"data: {chunk.choices[0].delta.content}\n\n"
                elif chunk.choices[0].delta.tool_calls:
                    yield f"data: {json.dumps(chunk.choices[0].delta.tool_calls[0].to_dict())}\n\n"
            yield "event: stream_end\ndata: Stream ended\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    else:
        response = client.chat.completions.create(**chat_config)

        # TODO: Calculate cost based on token usage
        cost_credits = None

        content = [serialize_content_block({"type": "text", "text": response.choices[0].message.content})]
        if response.choices[0].message.tool_calls:
            for tool_call in response.choices[0].message.tool_calls:
                content.append(serialize_content_block({
                    "type": "tool_calls",
                    "tool_calls": tool_call.to_dict()
                }))

        return AiAskOutput(
            content=content,
            cost_credits=cost_credits
        )