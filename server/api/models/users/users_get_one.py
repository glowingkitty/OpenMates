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

from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, ClassVar
from server.api.models.projects.projects_get_one import Project
from server.api.models.teams.teams_get_one import Team

class DefaultPrivacySettings(BaseModel):
    allowed_to_access_name: bool = Field(..., description="Whether the AI team mates are by default allowed to access the name of the user.")
    allowed_to_access_username: bool = Field(..., description="Whether the AI team mates are by default allowed to access the username of the user.")
    allowed_to_access_projects: bool = Field(..., description="Whether the AI team mates are by default allowed to access the projects of the user.")
    allowed_to_access_goals: bool = Field(..., description="Whether the AI team mates are by default allowed to access the goals of the user.")
    allowed_to_access_todos: bool = Field(..., description="Whether the AI team mates are by default allowed to access the To Do's of the user.")
    allowed_to_access_recent_topics: bool = Field(..., description="Whether the AI team mates are by default allowed to access the recent topics the user asked AI team mates about.")
    allowed_to_access_recent_emails: bool = Field(..., description="Whether the AI team mates are by default allowed to access the recent emails of the user.")
    allowed_to_access_calendar: bool = Field(..., description="Whether the AI team mates are by default allowed to access the calendar of the user.")
    allowed_to_access_likes: bool = Field(..., description="Whether the AI team mates are by default allowed to access the likes of the user.")
    allowed_to_access_dislikes: bool = Field(..., description="Whether the AI team mates are by default allowed to access the dislikes of the user.")

class Skill(BaseModel):
    id: int = Field(..., description="ID of the skill")
    name: str = Field(..., description="Name of the skill")
    software: str = Field(..., description="Software related to the skill")
    api_endpoint: str = Field(..., description="API endpoint for the skill")

class MateConfig(BaseModel):
    id: int = Field(..., description="ID of the Mate config")
    mate_username: str = Field(..., description="Username of the AI team mate this config is for.")
    team_slug: str = Field(..., description="Slug of the team this config is for.")
    systemprompt: str = Field(..., description="Custom system prompt for the AI team mate.")
    llm_endpoint: str = Field(..., description="The API endpoint of the Large Language Model (LLM) which is used by the AI team mate.")
    llm_model: str = Field(..., description="The LLM model which is used by the AI team mate.")
    skills: list[Skill] = Field(..., description="Custom selection of skills the AI team mate can use")
    allowed_to_access_user_name: bool = Field(..., description="Whether the AI team mate is allowed to access the name of the user.")
    allowed_to_access_user_username: bool = Field(..., description="Whether the AI team mate is allowed to access the username of the user.")
    allowed_to_access_user_projects: bool = Field(..., description="Whether the AI team mate is allowed to access the projects of the user.")
    allowed_to_access_user_goals: bool = Field(..., description="Whether the AI team mate is allowed to access the goals of the user.")
    allowed_to_access_user_todos: bool = Field(..., description="Whether the AI team mate is allowed to access the To Do's of the user.")
    allowed_to_access_user_recent_topics: bool = Field(..., description="Whether the AI team mate is allowed to access the recent topics the user asked AI team mates about.")
    allowed_to_access_user_recent_emails: bool = Field(..., description="Whether the AI team mate is allowed to access the recent emails of the user.")
    allowed_to_access_user_calendar: bool = Field(..., description="Whether the AI team mate is allowed to access the calendar of the user.")
    allowed_to_access_user_likes: bool = Field(..., description="Whether the AI team mate is allowed to access the likes of the user.") 
    allowed_to_access_user_dislikes: bool = Field(..., description="Whether the AI team mate is allowed to access the dislikes of the user.")


# GET /users/{user_username} (get a user)

class User(BaseModel):
    """This is the base model for a user"""
    model_config = ConfigDict(extra='allow')

    id: str = Field(..., description="ID of the user")
    username: str = Field(..., description="Username of the user")
    email: Optional[str] = Field(None, description="Email address of the user")
    teams: Optional[List[Team]] = Field(None, description="Teams the user is a member of")
    profile_picture_url: Optional[str] = Field(None, description="URL of the profile picture of the user")
    balance_credits: int = Field(..., description="Balance of the user in credits. This balance can be used for using skills.")
    mates_default_privacy_settings: Optional[DefaultPrivacySettings] = Field(None, description="The default privacy settings for the AI team mates, which the user communicates with.")
    mates_custom_settings: Optional[list[MateConfig]] = Field(None, description="Custom settings for the AI team mates, such as system prompt, privacy settings, etc.")
    other_settings: Optional[dict] = Field(None, description="Other settings, such as notification settings, etc.")
    projects: Optional[List[Project]] = Field(None, description="Projects of the user")
    likes: Optional[List[str]] = Field(None, description="List of topics the user is interested in")
    dislikes: Optional[List[str]] = Field(None, description="List of topics the user is not interested in")
    topics_outside_my_bubble_that_i_should_consider: Optional[List[str]] = Field(None, description="List of topics the user is not interested in, but should consider")
    goals: Optional[List[dict]] = Field(None, description="Goals and priorities of the user, related to projects, learning, finances etc.")
    recent_topics: Optional[List[str]] = Field(None, description="Recent topics the user asked the AI team mates about.")
    is_server_admin: Optional[bool] = Field(None, description="Whether the user is a server admin")

    email_encrypted: Optional[str] = Field(None, description="Encrypted email address of the user")
    password_encrypted: Optional[str] = Field(None, description="Encrypted password of the user")
    api_token_encrypted: Optional[str] = Field(None, description="Encrypted API token of the user")
    other_settings_encrypted: Optional[str] = Field(None, description="Encrypted other settings of the user")
    likes_encrypted: Optional[str] = Field(None, description="Encrypted likes of the user")
    dislikes_encrypted: Optional[str] = Field(None, description="Encrypted dislikes of the user")
    goals_encrypted: Optional[str] = Field(None, description="Encrypted goals of the user")
    recent_topics_encrypted: Optional[str] = Field(None, description="Encrypted recent topics of the user")

    decrypted_fields: ClassVar[List[str]] = [
        'email',
        'other_settings',
        'likes',
        'dislikes',
        'goals',
        'recent_topics'
    ]

users_get_one_output_example = {
    "id": 1,
    "username": "johnd",
    "email": "johnd_openmates@gmail.com",
    "teams": [
        {
            "id": 1,
            "name": "AI Sales Team",
            "slug": "ai-sales-team"
        }
    ],
    "profile_picture_url": "/v1/ai-sales-team/uploads/johnd_image.jpeg",
    "balance_credits": 49200,
    "mates_default_privacy_settings": {
        "allowed_to_access_name": True,
        "allowed_to_access_username": True,
        "allowed_to_access_projects": True,
        "allowed_to_access_goals": True,
        "allowed_to_access_todos": True,
        "allowed_to_access_recent_topics": True,
        "allowed_to_access_recent_emails": True,
        "allowed_to_access_calendar": True,
        "allowed_to_access_likes": True,
        "allowed_to_access_dislikes": True
    },
    "mates_custom_settings": [],
    "other_settings": {
        "notifications": {
            "new_feature_announcements": {
                "turn_on": True,
                "send_via": "chat"
            }
        }
    },
    "projects": [
        {
            "id": 1,
            "name": "Integrate AI into sales software",
            "description": "Integrate AI into the sales software to provide better insights and predictions. We use Python, Pandas, NumPy, and TensorFlow."
        }
    ],
    "likes": [
        "AI",
        "Python",
        "software development"
    ],
    "dislikes": [
        "Java",
        "C++",
        "PHP",
        "clickbait articles"
    ],
    "goals": [
        {
            "name": "Release the updated sales software with AI integration",
            "priority": 1
        },
        {
            "name": "Get 1000 monthly users for the updated sales software",
            "priority": 2
        }
    ],
    "recent_topics": [
        "AI",
        "Python",
        "TensorFlow",
        "Pandas",
        "NumPy",
        "sales software",
        "FastAPI",
        "Docker"
    ]
}