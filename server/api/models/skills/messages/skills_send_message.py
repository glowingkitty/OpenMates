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

from server.api import *
################

from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import Literal, List, Optional

# POST /skills/messages/send

class Target(BaseModel):
    """This is the model for the message target"""
    team: str = Field(..., description="Provider and team name in the format 'Provider | Team Name'")
    channel_name: Optional[str] = Field(None, description="Name of the channel where the message should be sent to")
    channel_id: Optional[str] = Field(None, description="Channel ID where the message should be sent to")
    thread_id: Optional[str] = Field(None, description="Thread ID where the message should be sent to")

    model_config = ConfigDict(extra="forbid")

    @property
    def provider(self) -> str:
        """Generate the provider based on the team field."""
        return self.team.split(" | ")[0].strip()

    @model_validator(mode='after')
    def check_channel_id_or_name(self):
        if self.channel_id is not None and self.channel_name is not None:
            raise ValueError("Only one of 'target.channel_id' or 'target.channel_name' should be provided, not both.")
        if self.channel_id is None and self.channel_name is None and self.thread_id is None:
            raise ValueError("Either 'target.channel_id', 'target.channel_name', or 'target.thread_id' must be provided.")
        return self

    @model_validator(mode='after')
    def validate_team_format(self):
        valid_providers = ["Discord", "Slack", "Mattermost"]
        parts = self.team.split("|")
        if len(parts) != 2 or parts[0].strip() not in valid_providers:
            raise ValueError("'team' must be in the format 'Provider | Team Name' with a valid provider")
        return self

    @model_validator(mode='after')
    def validate_mattermost_fields(self):
        if self.provider == "Mattermost":
            if not getattr(self, 'group_id', None):
                raise ValueError("'target.group_id' (team ID) is required for Mattermost.")
        return self

class Attachment(BaseModel):
    """This is the model for the message attachment"""
    filename: str = Field(..., description="Filename of the attachment")
    base64_content: str = Field(..., description="Base64 encoded content of the attachment")

class MessagesSendInput(BaseModel):
    """This is the model for sending a message"""
    message: str = Field(..., description="Message to send")
    ai_mate_username: str = Field(..., description="Username of the AI team mate sending the message")
    target: Target = Field(..., description="Target information for the message")
    attachments: Optional[List[Attachment]] = Field(None, description="List of attachments to send with the message")

    model_config = ConfigDict(extra="forbid")

class MessagesSendOutput(BaseModel):
    """This is the model for the output of POST /skills/messages/send"""
    message_id: Optional[str] = Field(None, description="ID of the message")
    channel_id: Optional[str] = Field(None, description="ID of the channel")
    thread_id: Optional[str] = Field(None, description="ID of the thread")
    error: Optional[str] = Field(None, description="Error message")


skills_send_message_input_example = {
    "message": "Hey there, do you have any coding related questions?",
    "ai_mate_username": "sophia",
    "target": {
        "team": "Discord | OpenMates Development",
        "channel_name": "general"
    },
    "attachments": [
        {
            "filename": "screenshot.png",
            "base64_content": "iVBORw0KGgoAAAANSUhEUgAAAAUA..."
        }
    ]
}

skills_send_message_output_example = {
    "message_id": "1234567890123456789",
    "channel_id": "987654321098765432",
    "thread_id": None
}