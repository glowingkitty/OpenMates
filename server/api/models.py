from pydantic import BaseModel, Field

################
## Message Models
################

class IncomingMessage(BaseModel):
    """This is the model for incoming messages"""
    message: str = Field(..., description="Message to send to the AI team mate.", example="Write me some python code that prints 'Hello, AI!'")
    mate_username: str = Field(..., description="Username of the AI team mate who the message is for.", example="burton")


class OutgoingMessage(BaseModel):
    """This is the model for outgoing messages"""
    message: str = Field(..., description="The content of the message", example="Hello, AI!")


################
## Mate Models
################
    
class Mate(BaseModel):
    """This is the model for an AI team mate"""
    name: str = Field(..., description="Name of the AI team mate", example="burton")