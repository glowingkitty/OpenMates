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

from server.api import *
################

from server.api.models.skills.ai.skills_ai_ask import AiAskOutput, AiAskInput
from typing import Union, List, Dict, Any
from server.api.models.skills.ai.skills_ai_ask import AiAskOutput, AiAskInput
from typing import Union, List, Dict, Any
from fastapi.responses import StreamingResponse

# load providers
from server.api.endpoints.skills.ai.providers.claude.ask import ask as ask_claude
from server.api.endpoints.skills.ai.providers.chatgpt.ask import ask as ask_chatgpt
from server.api.endpoints.skills.ai.estimate_cost import estimate_cost
from server.api.endpoints.billing.check_user_balance import check_user_balance
from fastapi import HTTPException


async def ask(
        user_api_token: str,
        team_slug: str,
        system: str = "You are a helpful assistant. Keep your answers concise.",
        message: str = None,
        message_history: List[Dict[str, Any]] = None,
        provider: dict = {"name":"claude", "model":"claude-3.5-sonnet"},
        temperature: float = 0.5,
        stream: bool = False,
        cache: bool = False,
        max_tokens: int = 4096,
        stop_sequence: str = None,
        tools: List[dict] = None,
    ) -> Union[AiAskOutput, StreamingResponse]:
    """
    Ask a question to AI
    """

    input = AiAskInput(
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

    # # Estimate the cost of the request
    # estimated_cost = estimate_cost(**input.model_dump())
    # required_credits = estimated_cost.total_credits_cost_estimated.credits_for_500_output_tokens

    # add_to_log(f"Estimated cost: {required_credits} credits", module_name="OpenMates | Skills | Claude | Ask", color="yellow")

    # # Check if the user has enough balance
    # has_sufficient_balance = await check_user_balance(
    #     team_slug=team_slug,
    #     api_token=user_api_token,
    #     required_credits=required_credits
    # )

    # if not has_sufficient_balance:
    #     raise HTTPException(status_code=402, detail="Insufficient credits. You need to have at least " + str(required_credits) + " credits on your balance to perform this action.")

    # TODO █ OpenMates | API | Verify Token | get_user.py:257 => ❌ Traceback (most recent call last):
    # █   File "/usr/src/OpenMates/server/api/endpoints/users/get_user.py", line 131, in get_user
    # █     fields=fields[user_access],
    # █            ~~~~~~^^^^^^^^^^^^^
    # █ KeyError: None

    # TODO check for user api key or billing / enough credits
    # TODO add pricing at the end of the response, both for streaming and non-streaming
    # TODO add caching of user data via dragonflys

    add_to_log("Asking AI ...", module_name="OpenMates | Skills | AI | Ask", color="yellow")

    if input.provider.name == "claude":
        return await ask_claude(**input.model_dump())
    elif input.provider.name == "chatgpt":
        return await ask_chatgpt(**input.model_dump())