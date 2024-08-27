################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################


from typing import Optional
from fastapi import HTTPException
from server.api.models.skills.code.skills_code_plan import CodePlanInput, CodePlanOutput, FileContext
# from server.utils.code_extractor import extract_file_tree  # Assuming you have a utility to extract file trees
from server.api.endpoints.skills.ai.ask import ask
import json
from server.api.models.skills.code.skills_code_plan import code_plan_output_example
from server.api.endpoints.skills.ai.utils import load_prompt


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

    add_to_log("Making plan ...", module_name="OpenMates | Skills | Code | Plan", color="blue")

    # Extract file tree from the provided code source
    # file_tree = extract_file_tree(code_git_url, code_zip, code_file)
    file_tree = "{}"

    # Determine the phase based on the input
    if q_and_a_followup is None:
        # Phase 1: Generate follow-up questions
        system_prompt = load_prompt("/server/api/endpoints/skills/code/prompts/plan/generate_q_and_a_followup_system.md", {
            "q_and_a_followup_example": code_plan_output_example["q_and_a_followup"]
        })

        # Ensure q_and_a_basics is a dict and remove keys with None values for the answer
        q_and_a_basics = q_and_a_basics if type(q_and_a_basics) == dict else q_and_a_basics.model_dump()
        q_and_a_basics = {k: v for k, v in q_and_a_basics.items() if v is not None and v.get('answer') is not None}

        message = load_prompt("/server/api/endpoints/skills/code/prompts/plan/generate_q_and_a_followup_message.md", {
            "q_and_a_basics": q_and_a_basics,
            "file_tree": file_tree,
            "other_context_files": other_context_files
        })

        # TODO retry a second time if the response is not valid JSON
        # TODO clean up the code (seperate functions)

        response = await ask(
            user_api_token=token,
            team_slug=team_slug,
            system=system_prompt,
            message=message,
            provider={"name": "claude", "model": "claude-3.5-sonnet"},
            temperature=0
        )
        q_and_a_followup = json.loads(response["content"][0]["text"])

        return CodePlanOutput(
            q_and_a_followup=q_and_a_followup,
            costs_in_credits=1
        )
    else:
        # Phase 2: Generate full plan
        system_prompt = "You are an AI assistant tasked with generating a comprehensive project plan based on the provided requirements and context. Your output should include detailed requirements, coding guidelines, and a code logic draft."

        message = f"""
        Initial requirements:
        {q_and_a_basics}

        Follow-up questions and answers:
        {q_and_a_followup}

        File tree:
        {file_tree}

        Other context files:
        {other_context_files}

        Please generate a comprehensive project plan including:
        1. Detailed requirements in markdown format
        2. Coding guidelines in markdown format
        3. Code logic draft in markdown format
        4. Suggestions for files that should be included for context
        """

        response = await ask(
            user_api_token=token,
            team_slug=team_slug,
            system=system_prompt,
            message=message,
            provider={"name": "claude", "model": "claude-3.5-sonnet"},
            temperature=0.7
        )

        # Parse the response content
        content_parts = response.content.split('---')
        requirements = content_parts[0].strip() if len(content_parts) > 0 else ""
        coding_guidelines = content_parts[1].strip() if len(content_parts) > 1 else ""
        code_logic_draft = content_parts[2].strip() if len(content_parts) > 2 else ""
        files_for_context = content_parts[3].strip().split('\n') if len(content_parts) > 3 else []

        return CodePlanOutput(
            requirements=requirements,
            coding_guidelines=coding_guidelines,
            code_logic_draft=code_logic_draft,
            files_for_context=[FileContext(path=f, content="") for f in files_for_context],
            file_tree_for_context=file_tree,
            costs_in_credits=response.costs_in_credits  # Assuming the response includes this information
        )

    # Note: Phase 3 (corrections) is not implemented in this example
    # You may want to add an additional parameter to handle correction requests