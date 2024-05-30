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
from server.api.models.skills.chatgpt.skills_chatgpt_ask import ChatGPTAskOutput
from typing import Literal


async def ask(
        token: str,
        message: str,
        system_prompt: str = "You are a helpful assistant. Keep your answers concise.",
        ai_model: Literal["openai__gpt-4o","openai__gpt-3.5-turbo"] = "openai__gpt-4o",
        temperature: float = 0.5
    ) -> ChatGPTAskOutput:
    """
    Ask a question to ChatGPT
    """
    if ai_model != "openai__gpt-4o" and ai_model != "openai__gpt-3.5-turbo":
        raise ValueError("Invalid AI model. Please select 'openai__gpt-4o' or 'openai__gpt-3.5-turbo'.")

    add_to_log("Asking ChatGPT ...", module_name="OpenMates | Skills | ChatGPT | Ask", color="yellow")

    # TODO find the user with the token and check if the user has enough money to use the skill

    # Send request to ChatGPT to get a response
    load_dotenv()
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    response = client.chat.completions.create(
        model="gpt-4o" if ai_model == "openai__gpt-4o" else "gpt-3.5-turbo",
        messages=[
            {
            "role": "system",
            "content": [
                {
                "type": "text",
                "text": system_prompt
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

    return {
        "response": response.choices[0].message.content
    }