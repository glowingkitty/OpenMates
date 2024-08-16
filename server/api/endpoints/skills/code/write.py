from typing import List, Dict, Any
from fastapi import HTTPException
from server.api.models.skills.code.skills_code_write import CodeWriteInput, CodeWriteOutput, CodeChange

async def write(
    token: str,
    team_slug: str,
    requirements: str,
    coding_guidelines: str,
    files_for_context: List[Dict[str, str]],
    file_tree_for_context: Dict[str, Any]
) -> CodeWriteOutput:
    # Initialize the input model
    input_data = CodeWriteInput(
        requirements=requirements,
        coding_guidelines=coding_guidelines,
        files_for_context=files_for_context,
        file_tree_for_context=file_tree_for_context
    )

    # TODO processing


    return CodeWriteOutput(

    )