from server.api.models.skills.business.skills_business_plan_application import BusinessPlanApplicationOutput
from server.api.models.skills.business.skills_business_create_application import Applicant, Recipient
from server.api.endpoints.skills.web.read import read as read_website
from server.api.models.skills.web.skills_web_read import WebReadOutput
from server.api.endpoints.skills.ai.ask import ask
from server.api.models.skills.ai.skills_ai_ask import AiAskOutput, AiAskInput
from typing import Optional, List, get_origin, get_args, Union
import json
import logging
from typing import Union
from pydantic import BaseModel

logger = logging.getLogger(__name__)

def generate_json_structure(cls):
    def get_structure(typ):
        if isinstance(typ, type) and issubclass(typ, BaseModel):
            return {
                k: add_description(get_structure(v.annotation), v)
                for k, v in typ.model_fields.items()
            }
        elif get_origin(typ) is list:
            return [get_structure(get_args(typ)[0])]
        elif get_origin(typ) is Union:
            types = [get_structure(arg) for arg in get_args(typ) if arg is not type(None)]
            return " | ".join(map(str, types))
        elif get_origin(typ) is Optional:
            return add_description(get_structure(get_args(typ)[0]), None, True)
        else:
            return typ.__name__.lower()

    def add_description(structure, field=None, optional=False):
        description = f" # {field.description}" if field and field.description else ""
        optional_str = " (optional)" if optional or (field and field.default is None) else ""

        if isinstance(structure, list):
            return structure  # Return the list as is, we'll format it later
        elif isinstance(structure, dict):
            return structure  # Don't modify nested structures
        else:
            return f"{structure}{optional_str}{description}"

    def format_output(structure, indent=0):
        if isinstance(structure, dict):
            lines = ["{"]
            for k, v in structure.items():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    lines.append(f'{"    " * (indent + 1)}"{k}": [')
                    lines.extend(format_output(item, indent + 2) for item in v)
                    lines.append(f'{"    " * (indent + 1)}],')
                else:
                    lines.append(f'{"    " * (indent + 1)}"{k}": {format_output(v, indent + 1)},')
            lines.append("    " * indent + "}")
            return "\n".join(lines)
        elif isinstance(structure, list):
            if structure and isinstance(structure[0], dict):
                return "{\n" + ",\n".join(f'{"    " * (indent + 1)}"{k}": {v}' for k, v in structure[0].items()) + "\n" + "    " * indent + "}"
            else:
                return json.dumps(structure)
        else:
            return str(structure)

    result = get_structure(cls)
    return format_output(result)

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
    You are an expert in planning applications for funding programs.
    Your output will be extensive and highly relevant, so based on your output someone can write a successful application.
    Make sure to consider the information provided and always output a valid tool call.
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
    tool = Recipient.to_tool()
    response: AiAskOutput = await ask(
        user_api_token=user_api_token,
        team_slug=team_slug,
        input=AiAskInput(
            system=system,
            message=message,
            provider={"name": "chatgpt", "model": "gpt-4o-mini"},
            stream=False,
            tools=[tool]
        )
    )
    logger.info(f"Response: {response}")
    if response.content:
        tool_use = response.content[0].tool_use
        if tool_use and tool_use.input:
            recipient_data = tool_use.input
        else:
            raise ValueError("No tool use input in the response")
    else:
        raise ValueError("No content in the response")

    recipient = Recipient(**recipient_data)

    logger.debug(f"Application planned")
    return BusinessPlanApplicationOutput(
        recipient=recipient
    )
