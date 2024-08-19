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

    response = client.chat.completions.create(
        model=ai_ask_input.provider.model,
        messages=[
            {
            "role": "system",
            "content": [
                {
                "type": "text",
                "text": ai_ask_input.system
                }
            ]
            },
            {
            "role": "user",
            "content": [
                {
                "type": "text",
                "text": ai_ask_input.message
                }
            ]
            }
        ],
        temperature=ai_ask_input.temperature
    )

    return AiAskOutput(
        content=response.choices[0].message.content
    )