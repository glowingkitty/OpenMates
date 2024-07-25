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
from typing import Literal, Union
from fastapi.responses import StreamingResponse


async def ask(
        token: str,
        message: str,
        system_prompt: str = "You are a helpful assistant. Keep your answers concise.",
        ai_model: Literal["claude-3.5-sonnet", "claude-3-haiku"] = "claude-3.5-sonnet",
        temperature: float = 0.5,
        stream: bool = False
    ) -> Union[ClaudeAskOutput, StreamingResponse]:
    """
    Ask a question to Claude
    """
    if ai_model not in ["claude-3.5-sonnet", "claude-3-haiku"]:
        raise ValueError("Invalid AI model. Please select 'claude-3.5-sonnet' or 'claude-3-haiku'.")

    add_to_log("Asking Claude ...", module_name="OpenMates | Skills | Claude | Ask", color="yellow")

    # Select a more specific model
    if ai_model == "claude-3.5-sonnet":
        ai_model = "claude-3-5-sonnet-20240620"
    elif ai_model == "claude-3-haiku":
        ai_model = "claude-3-haiku-20240307"

    # # TODO implement check for user key / balance
    # user = get_user(token=token)

    # # Get the estimated minimum cost of the skill
    # estimated_minimum_cost = get_skill_costs(
    #     software="claude",
    #     skill="ask",
    #     token_count=count_tokens(system_prompt+message)+200 # assuming 200 tokens for the response
    # )

    # # Get the api credentials for Claude
    # api_credentials = get_api_credentials(
    #     user=user,
    #     software="claude",
    #     api_credentials="default",
    #     costs_eur=estimated_minimum_cost
    # )

    # # Send request to Claude to get a response
    # client = Anthropic(api_key=api_credentials["api_key"])

    # Send request to Claude to get a response
    load_dotenv()
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    if stream:
        async def event_stream():
            with client.messages.stream(
                model=ai_model,
                max_tokens=1000,
                system=system_prompt,
                messages=[{"role": "user", "content": message}],
                temperature=temperature
            ) as stream:
                for text in stream.text_stream:
                    yield f"data: {text}\n\n"
                yield "event: stream_end\ndata: Stream ended\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    else:
        response = client.messages.create(
            model=ai_model,
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": message}],
            temperature=temperature
        )
        return {"response": response.content[0].text}