from typing import Optional
from fastapi import HTTPException
from server.api.models.skills.code.skills_code_plan import CodePlanInput, CodePlanOutput, FileContext

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

    # TODO processing


    # TODO keep in mind processing can take a while thats why I wanted to implement tasks,
    # so at some point I need to implement task system


    return CodePlanOutput(

    )