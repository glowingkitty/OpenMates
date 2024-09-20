from server.api.models.skills.ai.skills_ai_ask import AiAskOutput, AiAskInput
from typing import Union, List, Dict, Any
from fastapi.responses import StreamingResponse
from fastapi import HTTPException
import logging

# load providers
from server.api.endpoints.skills.ai.providers.claude.ask import ask as ask_claude
from server.api.endpoints.skills.ai.providers.chatgpt.ask import ask as ask_chatgpt
from server.api.endpoints.skills.ai.estimate_cost import estimate_cost

logger = logging.getLogger(__name__)


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
    logger.info(f"Asking AI with provider: {provider}")

    # TODO add cost estimation
    # TODO check if user has enough credits
    # TODO create task

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

    if input.provider.name == "claude":
        return await ask_claude(**input.model_dump())
    elif input.provider.name == "chatgpt":
        return await ask_chatgpt(**input.model_dump())