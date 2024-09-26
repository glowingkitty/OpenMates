from server.api.models.skills.business.skills_business_create_pitch import BusinessCreatePitchOutput
from server.api.models.skills.ai.skills_ai_ask import AiAskOutput
from server.api.endpoints.skills.ai.ask import ask
from typing import List
import logging

logger = logging.getLogger(__name__)

async def create_pitch(
        user_api_token: str,
        team_slug: str,
        what: str,
        name: str,
        existing_pitch: str,
        short_description: str,
        in_depth_description: str,
        highlights: List[str],
        impact: str,
        potential_future: str,
        target_audience: str,
        unique_selling_proposition: str,
        goals: str,
        market_analysis: str,
        users: str,
        problems: str,
        solutions: str,
        team_information: str,
        financial_projections: str,
        customer_testimonials: List[str],
        pitch_type: str,
        pitch_type_other_use_case: str
) -> BusinessCreatePitchOutput:
    logger.debug(f"Creating pitch")
    pitch = ""

    # generate the system prompt for the LLM
    system = f"""
    You are an expert in creating pitches for projects and companies.
    Based on the information provided, create an amazing pitch for the project or company.
    """

    # generate the message for the LLM
    message = f"""
    What: {what}
    Name: {name}
    Existing pitch: {existing_pitch}
    Short description: {short_description}
    In-depth description: {in_depth_description}
    Highlights: {highlights}
    Impact: {impact}
    Potential future: {potential_future}
    Target audience: {target_audience}
    Unique selling proposition: {unique_selling_proposition}
    Goals: {goals}
    Market analysis: {market_analysis}
    Users: {users}
    Problems: {problems}
    Solutions: {solutions}
    Team information: {team_information}
    Financial projections: {financial_projections}
    Customer testimonials: {customer_testimonials}
    Pitch type: {pitch_type}
    Pitch type other use case: {pitch_type_other_use_case}
    """
    logger.debug(f"System: {system}")
    logger.debug(f"Prompt: {message}")

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
        pitch_type=pitch_type,
        pitch_type_other_use_case=pitch_type_other_use_case
    )
