
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

from pydantic import BaseModel, Field, validator


# POST /mates/ask (Send a message to an AI team mate and you receive the response)

class MatesAskInput(BaseModel):
    """This is the model for the incoming parameters for POST /mates/ask"""
    mate_username: str = Field(..., description="Username of the AI team mate who the message is for.")
    message: str = Field(..., description="Message to send to the AI team mate.")

    class Config:
        extra = "forbid"

    # validate that username is small letters
    @validator('mate_username')
    def validate_mate_username(cls, v):
        if not v.islower():
            raise ValueError(f"Username must be in lower case: {v}")
        return v


mates_ask_input_example = {
    "mate_username": "sophia",
    "message": "Write me some python code that prints 'Hello, AI!'"
}


class MatesAskOutput(BaseModel):
    """This is the model for outgoing message for POST /mates/ask"""
    message: str = Field(..., description="The content of the message")
    tokens_used_input: int = Field(..., description="The number of tokens used to process the input message")
    tokens_used_output: int = Field(..., description="The number of tokens used to generate the output message")
    total_costs_eur: float = Field(..., description="The total cost of processing the message, in EUR")

mates_ask_output_example = {
    "message": "Of course I can help you with that! Here is the python code you requested: print('Hello, AI!')\n\nI hope this helps you out. If you have any more questions, feel free to ask!",
    "tokens_used_input": 20,
    "tokens_used_output": 46,
    "total_costs_eur": 0.003
}
