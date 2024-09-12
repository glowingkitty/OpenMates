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
from typing import List, Optional, Literal

# POST /skills/messages/connect

class MateConnectLinks(BaseModel):
    """Model for mate connect links across different platforms"""
    discord: Optional[str] = Field(None, description="Discord connect link")
    # slack: Optional[str] = Field(None, description="Slack connect link")
    # telegram: Optional[str] = Field(None, description="Telegram connect link")
    # mattermost: Optional[str] = Field(None, description="Mattermost connect link")

class Mate(BaseModel):
    """Model for a mate with connect links for multiple platforms"""
    name: str = Field(..., description="The name of the mate")
    description: str = Field(..., description="The description of the mate")
    connect_links: MateConnectLinks = Field(..., description="Connect links for different platforms")

class MessagesConnectInput(BaseModel):
    """Model for the messages connect server input"""
    team_name: str = Field(..., description="The name of the team")
    include_all_mates: bool = Field(..., description="Whether to include all mates")
    mates: Optional[List[str]] = Field(None, description="The names of the mates to include, if include_all_mates is false")
    include_all_platforms: bool = Field(..., description="Whether to include all platforms")
    platforms: Optional[List[Literal["discord", "slack", "telegram", "mattermost"]]] = Field(None, description="The platforms to include, if include_all_platforms is false")

    @model_validator(mode='after')
    def validate_platforms(self):
        if not self.include_all_platforms and not self.platforms:
            raise ValueError("At least one platform must be specified if include_all_platforms is false")
        return self

class MessagesConnectOutput(BaseModel):
    """Model for the messages connect output"""
    mates: List[Mate] = Field(..., description="The list of mates")

    model_config = ConfigDict(extra="forbid")

messages_connect_input_example = {
    "team_name": "OpenMates Development",
    "include_all_mates": False,
    "mates": ["Sophia", "Mark", "Elton"],
    "include_all_platforms": True,
    "platforms": []
}

messages_connect_output_example = {
    "mates": [
        {
            "name": "Sophia",
            "description": "Software development expert",
            "connect_links": {
                "discord": "https://discord.com/api/oauth2/authorize?client_id=123456789012345678&permissions=8&redirect_uri=https%3A%2F%2Fopenmates.com&response_type=code&scope=bot"
            }
        },
        {
            "name": "Mark",
            "description": "Marketing expert",
            "connect_links": {
                "discord": "https://discord.com/api/oauth2/authorize?client_id=234567890123456789&permissions=8&redirect_uri=https%3A%2F%2Fopenmates.com&response_type=code&scope=bot"
            }
        },
        {
            "name": "Elton",
            "description": "Electrical engineering expert",
            "connect_links": {
                "discord": "https://discord.com/api/oauth2/authorize?client_id=345678901234567890&permissions=8&redirect_uri=https%3A%2F%2Fopenmates.com&response_type=code&scope=bot"
            }
        }
    ]
}