from server.api.models.skills.business.skills_business_create_pitch import BusinessCreatePitchOutput
from typing import List

async def create_pitch(
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
    pitch = ""

    return BusinessCreatePitchOutput(
        pitch=pitch,
        pitch_type=pitch_type,
        pitch_type_other_use_case=pitch_type_other_use_case
    )
