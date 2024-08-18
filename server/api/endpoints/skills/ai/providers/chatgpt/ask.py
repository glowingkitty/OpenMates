################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from openai import OpenAI
from dotenv import load_dotenv
from server.api.models.skills.ai.skills_ai_ask import AiAskOutput
from typing import Literal


async def ask(
        token: str,
        message: str,
        system: str = "You are a helpful assistant. Keep your answers concise.",
        ai_model: Literal["gpt-4o","gpt-4o-mini"] = "gpt-4o",
        temperature: float = 0.5
    ) -> AiAskOutput:
    """
    Ask a question to ChatGPT
    """
    if ai_model != "gpt-4o" and ai_model != "gpt-4o-mini":
        raise ValueError("Invalid AI model. Please select 'gpt-4o' or 'gpt-4o-mini'.")

    add_to_log("Asking ChatGPT ...", module_name="OpenMates | Skills | ChatGPT | Ask", color="yellow")


    # # TODO implement check for user key / balance
    # user = get_user(token=token)

    # # Get the estimated minimum cost of the skill
    # estimated_minimum_cost = get_skill_costs(
    #     software="chatgpt",
    #     skill="ask",
    #     token_count=count_tokens(system+message)+200 # assumming 200 tokens for the response
    # )

    # # Get the api credentials for ChatGPT
    # api_credentials = get_api_credentials(
    #     user=user,
    #     software="chatgpt",
    #     api_credentials="default",
    #     costs_eur=estimated_minimum_cost
    # )

    # # Send request to ChatGPT to get a response
    # client = OpenAI(api_key=api_credentials["api_key"])

    # Send request to ChatGPT to get a response
    load_dotenv()
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    response = client.chat.completions.create(
        model=ai_model,
        messages=[
            {
            "role": "system",
            "content": [
                {
                "type": "text",
                "text": system
                }
            ]
            },
            {
            "role": "user",
            "content": [
                {
                "type": "text",
                "text": message
                }
            ]
            }
        ],
        temperature=temperature
    )

    return AiAskOutput(
        content=response.choices[0].message.content
    )