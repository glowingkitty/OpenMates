from typing import Optional
from fastapi import HTTPException
from server.api.models.skills.code.skills_code_plan import CodePlanInput, CodePlanOutput, FileContext
# from server.utils.code_extractor import extract_file_tree  # Assuming you have a utility to extract file trees
from server.api.endpoints.skills.ai.ask import ask
from server.api.models.skills.ai.skills_ai_ask import AiAskOutput, AiAskInput
import json
from server.api.models.skills.code.skills_code_plan import code_plan_output_example, code_plan_processing_output_example
from server.api.endpoints.skills.ai.utils import load_prompt
import logging

# Set up logger
logger = logging.getLogger(__name__)


async def plan(
    token: str,
    team_slug: str,
    q_and_a_basics: dict,
    q_and_a_followup: Optional[dict] = None,
    code_git_url: Optional[str] = None,
    code_zip: Optional[str] = None,
    code_file: Optional[str] = None,
    other_context_files: Optional[dict] = None
) -> CodePlanOutput:
    # Initialize the input model
    input_data = CodePlanInput(
        q_and_a_basics=q_and_a_basics,
        q_and_a_followup=q_and_a_followup,
        code_git_url=code_git_url,
        code_zip=code_zip,
        code_file=code_file,
        other_context_files=other_context_files
    )

    logger.debug("Making plan ...")

    # Extract file tree from the provided code source
    # file_tree = extract_file_tree(code_git_url, code_zip, code_file)
    file_tree = "{}"

    # Ensure q_and_a_basics is a dict and remove keys with None values for the answer
    q_and_a_basics = q_and_a_basics if type(q_and_a_basics) == dict else q_and_a_basics.model_dump()
    q_and_a_basics = {k: v for k, v in q_and_a_basics.items() if v is not None and v.get('answer') is not None}

    # Ensure q_and_a_followup is a dict and remove keys with None values for the answer
    if q_and_a_followup is not None:
        q_and_a_followup = q_and_a_followup if type(q_and_a_followup) == dict else q_and_a_followup.model_dump()
        q_and_a_followup = {k: (v if type(v) == dict else v.model_dump()) for k, v in q_and_a_followup.items() if v is not None and (v.get('answer') if type(v) == dict else v.answer is not None)}

    # Determine the phase based on the input
    if q_and_a_followup is None:
        # Phase 1: Generate follow-up questions
        system_prompt = load_prompt("/server/api/endpoints/skills/code/prompts/plan/generate_q_and_a_followup_system.md", {
            "q_and_a_followup_example": code_plan_output_example["q_and_a_followup"]
        })

        message = load_prompt("/server/api/endpoints/skills/code/prompts/plan/generate_q_and_a_followup_message.md", {
            "q_and_a_basics": q_and_a_basics,
            "file_tree": file_tree,
            "other_context_files": other_context_files
        })

        # TODO clean up the code (seperate functions)

        response: AiAskOutput = await ask(
            user_api_token=token,
            team_slug=team_slug,
            input=AiAskInput(
                system=system_prompt,
                message=message,
                provider={"name": "claude", "model": "claude-3.5-sonnet"},
                temperature=0.2
            )
        )
        try:
            # TODO: use tool processing instead of JSON parsing?
            q_and_a_followup = json.loads(response.content[0].text)
        except Exception as e:
            logger.error(f"LLM did not return valid JSON: {e}")
            raise Exception("LLM did not return valid JSON")

        return CodePlanOutput(
            q_and_a_followup=q_and_a_followup,
            costs_in_credits=1  # TODO: Implement cost calculation
        )
    else:
        # Phase 2: Generate full plan
        system_prompt = load_prompt("/server/api/endpoints/skills/code/prompts/plan/generate_full_plan_system.md",{
            "code_plan_processing_output_example": code_plan_processing_output_example
        })

        message = load_prompt("/server/api/endpoints/skills/code/prompts/plan/generate_full_plan_message.md", {
            "q_and_a_basics": q_and_a_basics,
            "q_and_a_followup": q_and_a_followup,
            "file_tree": file_tree,
            "other_context_files": other_context_files
        })

        response = await ask(
            user_api_token=token,
            team_slug=team_slug,
            system=system_prompt,
            message=message,
            provider={"name": "claude", "model": "claude-3.5-sonnet"},
            temperature=0.2
        )

        try:
            # TODO cant be parsed. therefore use tools!!!
            response_content = json.loads(response["content"][0]["text"])
        except Exception as e:
            logger.error(f"LLM did not return valid JSON: {e}")
            raise Exception("LLM did not return valid JSON")

        return CodePlanOutput(
            requirements=response_content["requirements"],
            coding_guidelines=response_content["coding_guidelines"],
            code_logic_draft=response_content["code_logic_draft"],
            files_for_context=response_content["files_for_context"],
            # file_tree_for_context=file_tree_for_context,
            costs_in_credits=1  # TODO: Implement cost calculation
        )

    # TODO:
    # - use tools / function calling instead of JSON parsing for more reliable output
    # - implement tasks instead of waiting for full response
    # - add correction phase 3, maybe by adding a new field to the input model