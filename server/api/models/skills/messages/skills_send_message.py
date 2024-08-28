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

from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import Literal, List, Optional

# POST /skills/messages/send

class Target(BaseModel):
    """This is the model for the message target"""
    provider: Literal["Discord", "Slack", "Mattermost"] = Field(..., description="Software where the message should be sent to")
    group_id: str = Field(..., description="ID of the group (guild in Discord, workspace in Slack, team in Mattermost)")
    channel_id: Optional[str] = Field(None, description="Channel ID where the message should be sent to")
    thread_id: Optional[str] = Field(None, description="Thread ID where the message should be sent to")

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode='after')
    def check_channel_id_or_thread_id(self):
        if self.channel_id is None and self.thread_id is None:
            raise ValueError("Either 'channel_id' or 'thread_id' must be provided.")
        return self

    @model_validator(mode='after')
    def validate_discord_fields(self):
        if self.provider == "Discord":
            if not self.group_id:
                raise ValueError("'group_id' (guild ID) is required for Discord.")
        return self

    @model_validator(mode='after')
    def validate_slack_fields(self):
        if self.provider == "Slack":
            if not self.group_id:
                raise ValueError("'group_id' (workspace ID) is required for Slack.")
        return self

    @model_validator(mode='after')
    def validate_mattermost_fields(self):
        if self.provider == "Mattermost":
            if not self.group_id:
                raise ValueError("'group_id' (team ID) is required for Mattermost.")
        return self

class Source(BaseModel):
    """This is the model for the message source"""
    bot_name: str = Field(..., description="Name of the bot that sends the message")
    ai_mate_name: str = Field(..., description="Name of the AI Mate that sends the message")

    model_config = ConfigDict(extra="forbid")

class Attachment(BaseModel):
    """This is the model for the message attachment"""
    filename: str = Field(..., description="Filename of the attachment")
    base64_content: str = Field(..., description="Base64 encoded content of the attachment")

class MessagesSendInput(BaseModel):
    """This is the model for sending a message"""
    message: str = Field(..., description="Message to send")
    source: Source = Field(..., description="Source information for the message")
    target: Target = Field(..., description="Target information for the message")
    attachments: Optional[List[Attachment]] = Field(None, description="List of attachments to send with the message")

    model_config = ConfigDict(extra="forbid")

class MessagesSendOutput(BaseModel):
    """This is the model for the output of POST /skills/messages/send"""
    message_id: str = Field(..., description="ID of the message")


skills_send_message_input_example = {
    "message": "Hey there, do you have any coding related questions?",
    "attachments": [
        {
            "filename": "screenshot.png",
            "base64_content": "iVBORw0KGgoAAAANSUhEUgAAAAUA..."
        }
    ],
    "target": {
        "provider": "Discord",
        "group_id": "923456789012345678",
        "channel_id": "987654321098765432",
        "thread_id": "123456789012345678"
    },
    "source": {
        "bot_name": "sophia_bot",
        "ai_mate_name": "sophia"
    }
}

skills_send_message_output_example = {
    "message_id": "1234567890123456789"
}