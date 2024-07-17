from typing import Dict
import os

def build_llm_prompt(new_api_endpoint: str, requirements_answers: str, systemprompt: str, linked_files_content: Dict[str, str]) -> str:
    """
    Create the final prompt for the LLM by combining the new API endpoint description,
    user requirements, system prompt, and linked files content.

    Args:
        new_api_endpoint (str): The content of the new API endpoint description.
        requirements_answers (str): The user's answers to the requirements questions.
        systemprompt (str): The system prompt content.
        linked_files_content (Dict[str, str]): A dictionary of linked file contents.

    Returns:
        str: The final prompt for the LLM.
    """
    prompt_parts = [
        "# System Prompt",
        systemprompt,
        "\n# New API Endpoint Description",
        new_api_endpoint,
        "\n# User Requirements",
        requirements_answers,
        "\n# Linked Files"
    ]

    for file_path, content in linked_files_content.items():
        file_format = os.path.splitext(file_path)[1][1:]  # Get file extension without the dot
        prompt_parts.extend([
            f"\n## {file_path}",
            f"```{file_format}",
            content,
            "```"
        ])

    prompt_parts.extend([
        "\n# Task",
        "Based on the provided information, including the linked files, please generate the necessary code and modifications for implementing this new API endpoint. Include any new files that need to be created and any changes to existing files."
    ])

    return "\n\n".join(prompt_parts)