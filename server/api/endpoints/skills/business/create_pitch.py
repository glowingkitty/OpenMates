from server.api.models.skills.business.skills_business_create_pitch import BusinessCreatePitchOutput, BusinessCreatePitchInput
from server.api.models.skills.ai.skills_ai_ask import AiAskOutput
from server.api.endpoints.skills.ai.ask import ask
from typing import List
import logging

logger = logging.getLogger(__name__)

async def create_pitch(
        user_api_token: str,
        team_slug: str,
        pitch_input: BusinessCreatePitchInput
) -> BusinessCreatePitchOutput:
    logger.debug(f"Creating pitch")

    # generate the system prompt for the LLM
    system = """
    You are an expert in creating pitches for projects and companies.
    Based on the information provided, create an amazing pitch for the project or company.
    """

    # generate the message for the LLM
    message = "\n".join([
        f"*{pitch_input.model_fields[field_name].description}*\n{getattr(pitch_input, field_name)}\n"
        for field_name in pitch_input.model_fields
        if getattr(pitch_input, field_name) is not None
    ])

    # send the prompt to the LLM
    response: AiAskOutput = await ask(
        user_api_token=user_api_token,
        team_slug=team_slug,
        system=system,
        message=message,
        provider={"name": "chatgpt", "model": "gpt-4o-mini"},
        stream=False
    )
    if response.content:
        pitch = response.content[0].text
    else:
        raise ValueError("No content in the response")

    logger.debug(f"Pitch created")
    return BusinessCreatePitchOutput(
        pitch=pitch,
        pitch_type=pitch_input.pitch_type,
        pitch_type_other_use_case=pitch_input.pitch_type_other_use_case
    )
