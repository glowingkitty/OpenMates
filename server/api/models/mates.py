from pydantic import BaseModel, Field
from typing import List
from enum import Enum

##################################
######### Mates ##################
##################################

## Base models

class Mate(BaseModel):
    """This is the model for an AI team mate"""
    username: str = Field(..., 
                description="username of the AI team mate", 
                example="burton"
                )
    description: str = Field(..., 
                description="description of the AI team mate", 
                example="Business development expert"
                )



## Endpoint models

# POST /mates/ask (Send a message to an AI team mate and you receive the response)

class MatesAskInput(BaseModel):
    """This is the model for the incoming parameters for POST /mates/ask"""
    team_name: str = Field(...,
                    description="The name of your team.",
                    example="glowingkitties"
                    )
    mate_username: str = Field(...,
                    description="Username of the AI team mate who the message is for.",
                    example="sophia"
                    )
    message: str = Field(..., 
                    description="Message to send to the AI team mate.", 
                    example="Write me some python code that prints 'Hello, AI!'"
                    )


class MatesAskOutput(BaseModel):
    """This is the model for outgoing message for POST /mates/ask"""
    message: str = Field(..., 
                    description="The content of the message", 
                    example="Of course I can help you with that! Here is the python code you requested: print('Hello, AI!')\n\nI hope this helps you out. If you have any more questions, feel free to ask!"
                    )
    tokens_used_input: int = Field(...,
                    description="The number of tokens used to process the input message",
                    example=20
                    )
    tokens_used_output: int = Field(...,
                    description="The number of tokens used to generate the output message",
                    example=46
                    )
    total_costs_eur: float = Field(...,
                    description="The total cost of processing the message, in EUR",
                    example=0.003
                    )


# GET /mates (get all mates)

class MatesGetAllInput(BaseModel):
    team_name: str = Field(...,
                    description="The name of your team.",
                    example="glowingkitties"
                    )


class MatesGetAllOutput(BaseModel):
    mates: List[Mate] = Field(..., example=[
        {"username": "burton", "description": "Business development expert"}, 
        {"username": "sophia", "description": "Software development expert"},
        {"username": "mark", "description": "Marketing & sales expert"}
        ])
    

# GET /mates/{mate_username} (get a mate)

class MatesGetOneInput(BaseModel):
    team_name: str = Field(...,
                    description="The name of your team.",
                    example="glowingkitties"
                    )