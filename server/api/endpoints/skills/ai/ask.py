from server.api.models.skills.ai.skills_ai_ask import AiAskOutput, AiAskInput
from typing import Union, List, Dict, Any
from fastapi.responses import StreamingResponse
from fastapi import HTTPException
import logging

# load providers
from server.api.endpoints.skills.ai.providers.claude.ask import ask as ask_claude
from server.api.endpoints.skills.ai.providers.chatgpt.ask import ask as ask_chatgpt
from server.api.endpoints.skills.ai.estimate_cost import estimate_cost
from server.api.models.skills.ai.skills_ai_ask import Tool
logger = logging.getLogger(__name__)


async def ask(
        input: AiAskInput,
        user_api_token: str,
        team_slug: str,
    ) -> Union[AiAskOutput, StreamingResponse]:
    """
    Ask a question to AI
    """
    logger.info(f"Asking AI with provider: {input.provider}")

    # TODO add cost estimation
    # TODO check if user has enough credits
    # TODO create task

    if input.provider.name == "claude":
        return await ask_claude(
            input=input
        )
    elif input.provider.name == "chatgpt":
        return await ask_chatgpt(
            input=input
        )
