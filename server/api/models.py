from pydantic import BaseModel, Field
from typing import List

################
## Message Models
################

class IncomingMessage(BaseModel):
    """This is the model for incoming messages"""
    message: str = Field(..., 
                    description="Message to send to the AI team mate.", 
                    example="Write me some python code that prints 'Hello, AI!'"
                    )
    mate_username: str = Field(...,
                    description="Username of the AI team mate who the message is for.",
                    example="burton"
                    )


class OutgoingMessage(BaseModel):
    """This is the model for outgoing messages"""
    message: str = Field(..., 
                    description="The content of the message", 
                    example="Hello, AI!"
                    )


################
## Mate Models
################
    
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
    

class MatesResponse(BaseModel):
    mates: List[Mate] = Field(..., example=[
        {"username": "burton", "description": "Business development expert"}, 
        {"username": "sophia", "description": "Software development expert"},
        {"username": "mark", "description": "Marketing & sales expert"}
        ])