from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import Literal, List, Optional
from server.api.models.apps.messages.skills_send_message import Target, Attachment

# POST /apps/messages/receive

class MessagesReceiveOutput(BaseModel):
    """This is the model for the messages receive output"""
    message: str = Field(..., description="The message received")
    target: Target = Field(..., description="The target of the message")
    attachments: Optional[List[Attachment]] = Field(None, description="The attachments of the message")

    model_config = ConfigDict(extra="forbid")

messages_receive_output_example = {
    "message": "Hey @sophia, can you help me with this issue?",
    "target": {
        "team": "Discord | OpenMates Development",
        "channel_name": "coding"
    },
    "attachments": [
        {
            "filename": "screenshot.png",
            "base64_content": "iVBORw0KGgoAAAANSUhEUgAAAAUA..."
        }
    ]
}