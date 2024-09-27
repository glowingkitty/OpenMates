from server.api.models.skills.business.skills_business_plan_application import BusinessPlanApplicationOutput
from server.api.models.skills.business.skills_business_create_application import Applicant, Recipient
from typing import Optional, List
import json
import logging
from typing import Union

logger = logging.getLogger(__name__)

def generate_json_structure(cls):
    def get_structure(typ):
        if hasattr(typ, '__annotations__'):
            return {k: get_structure(v) for k, v in typ.__annotations__.items()}
        elif hasattr(typ, '__origin__'):
            if typ.__origin__ is list:
                return [get_structure(typ.__args__[0])]
            elif typ.__origin__ is Optional:
                inner_type = get_structure(typ.__args__[0])
                return f"{inner_type} (optional)"
            elif typ.__origin__ is Union:
                # Handle Union types excluding NoneType
                types = [get_structure(arg) for arg in typ.__args__ if arg is not type(None)]
                if len(types) == 1:
                    return f"{types[0]} (optional)"
                else:
                    return " | ".join(types)
        else:
            return typ.__name__

    return json.dumps(get_structure(cls), indent=4)


async def plan_application(
        applicant: Applicant,
        recipient_website_urls: Optional[List[str]],
        recipient_pdf_documents: Optional[List[str]],
        recipient_description: Optional[str],
        recipient_programs_description: Optional[str]
) -> BusinessPlanApplicationOutput:
    logger.debug(f"Planning application")
    recipient_name = ""
    recipient_writing_style = ""
    recipient_programs = []

    # generate the system prompt for the LLM
    system = f"""
    You are an expert in planning applications for funding programs.
    Based on the information provided, you will output a json in the following format:

    {generate_json_structure(BusinessPlanApplicationOutput)}

    Please ensure that the values are filled based on the provided information.
    """

    logger.debug(f"System prompt: {system}")

    # TODO


    logger.debug(f"Application planned")
    return BusinessPlanApplicationOutput(
        recipient=Recipient(
            name=recipient_name,
            writing_style=recipient_writing_style,
            programs=recipient_programs
        )
    )
