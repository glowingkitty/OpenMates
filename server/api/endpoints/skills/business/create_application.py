from server.api.models.skills.business.skills_business_create_application import BusinessCreateApplicationOutput, BusinessCreateApplicationInput
from typing import List
import logging
from server.api.endpoints.skills.ai.ask import ask
from server.api.models.skills.ai.skills_ai_ask import AiAskOutput, AiAskInput, Tool
from server.api.models.skills.business.skills_business_create_application import ApplicationFormQuestion
logger = logging.getLogger(__name__)


async def create_application(
        user_api_token: str,
        team_slug: str,
        input: BusinessCreateApplicationInput
) -> BusinessCreateApplicationOutput:
    logger.debug(f"Creating application")
    application = []

    # generate the system prompt for the LLM
    system = f"""
    You are an expert in writing applications for funding programs.
    You will write a winning application that will match perfectly to the recipient, the applicant, and the questions from the form.
    """

    # generate the message for the LLM
    questions_json = "\n".join([question.model_dump_json(indent=4) for question in input.application_form_questions])
    message = f"""
    Recipient:
    {input.recipient.model_dump_json(indent=4)}

    Applicant:
    {input.applicant.model_dump_json(indent=4)}

    Application form questions:
    {questions_json}
    """

    # send the prompt to the LLM
    tool: Tool = BusinessCreateApplicationOutput.to_tool()
    response: AiAskOutput = await ask(
        user_api_token=user_api_token,
        team_slug=team_slug,
        input=AiAskInput(
            system=system,
            message=message,
            provider={"name": "chatgpt", "model": "gpt-4o"},
            stream=False,
            tools=[tool]
        )
    )
    logger.debug(f"Response received")
    logger.debug(f"Response content: {response.content}")
    if response.content:
        # go over every content item up to the first tool use
        for content_item in response.content:
            if content_item.type == "tool_use":
                tool_use = content_item.tool_use
                if tool_use and tool_use.input:
                    application_data = tool_use.input
                    break
        else:
            logger.error(f"No tool use input in the response: {response.content}")
            raise ValueError("No tool use input in the response")
    else:
        raise ValueError("No content in the response")

    application = [ApplicationFormQuestion(**application_item) for application_item in application_data["application"]]

    logger.debug(f"Application created")
    return BusinessCreateApplicationOutput(
        selected_program=input.recipient.programs[0].name,
        application=application
    )
