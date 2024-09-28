from server.api.models.skills.business.skills_business_plan_application import BusinessPlanApplicationOutput
from server.api.models.skills.business.skills_business_create_application import Applicant, Recipient
from server.api.endpoints.skills.web.read import read as read_website
from server.api.models.skills.web.skills_web_read import WebReadOutput
from server.api.endpoints.skills.ai.ask import ask
from server.api.models.skills.ai.skills_ai_ask import AiAskOutput
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
        user_api_token: str,
        team_slug: str,
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
    You are an expert in planning applications for funding programs. Your output will be extensive and highly relevant, so based on your output someone can write a successful application.
    Based on the information provided, you will output a valid json in the following format and nothing else:

    {generate_json_structure(BusinessPlanApplicationOutput)}
    """

    # TODO add processing pdf documents as well

    # get the text from the website urls
    website_text = ""
    if recipient_website_urls:
        for url in recipient_website_urls:
            website_text += f"Website:\n`{url}`\n"
            website_read_output: WebReadOutput = await read_website(url)
            website_text += f"Content:\n```\n{website_read_output.content}\n```\n"

    # generate the message for the LLM
    message = f"""
    Applicant:
    {applicant.model_dump_json(indent=4)}
    """

    if website_text:
        message += f"\nRecipient websites:\n{website_text}"

    if recipient_description:
        message += f"\nRecipient description:\n{recipient_description}"

    if recipient_programs_description:
        message += f"\nRecipient programs description:\n{recipient_programs_description}"

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
        recipient_json = response.content[0].text
        recipient_json = json.loads(recipient_json)
        # Extract the 'recipient' key from the parsed JSON
        recipient_data = recipient_json.get('recipient', {})
    else:
        raise ValueError("No content in the response")

    recipient = Recipient(**recipient_data)

    logger.debug(f"Application planned")
    return BusinessPlanApplicationOutput(
        recipient=recipient
    )
