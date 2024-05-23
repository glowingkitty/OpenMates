
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

from pydantic import BaseModel, Field
from typing import List
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
    mate_username: str = Field(..., description="Username of the AI team mate this config is for.")
    team_slug: str = Field(..., description="Slug of the team this config is for.")
    systemprompt: str = Field(..., description="Custom system prompt for the AI team mate.")
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
    id: int = Field(..., description="ID of the user")
    username: str = Field(..., description="Username of the user")
    email: str = Field(..., description="Email address of the user")
    teams: List[Team] = Field(..., description="Teams the user is a member of")
    profile_picture_url: str = Field(..., description="URL of the profile picture of the user")
    balance_in_EUR: float = Field(..., description="Balance of the user in EUR. This balance can be used for using paid skills.")
    mates_default_privacy_settings: DefaultPrivacySettings = Field(..., description="The default privacy settings for the AI team mates, which the user communicates with.")
    mates_custom_settings: list[MateConfig] = Field(..., description="Custom settings for the AI team mates, such as system prompt, privacy settings, etc.")
    software_settings: dict = Field(..., description="Software settings, such as privacy settings, which cloud accounts are connected, default settings and more.")
    other_settings: dict = Field(..., description="Other settings, such as notification settings, etc.")
    projects: List[Project] = Field(..., description="Projects of the user")
    likes: List[str] = Field(..., description="List of topics the user is interested in")
    dislikes: List[str] = Field(..., description="List of topics the user is not interested in")
    goals: List[dict] = Field(..., description="Goals and priorities of the user, related to projects, learning, finances etc.")
    todos: List[str] = Field(..., description="List of current To Do's of the user")
    recent_topics: List[str] = Field(..., description="Recent topics the user asked the AI team mates about.")
    recent_emails: List[dict] = Field(..., description="Recent incoming and outgoing emails of the user, of connected email accounts.")
    calendar: dict = Field(..., description="Calendar of the user, with past events of the past month and upcoming events of the next year.")


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
    "profile_picture_url": "/ai-sales-team/uploads/johnd_image.jpeg",
    "balance_in_EUR": 100.0,
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
    "software_settings": {
        "dropbox": {
            "accounts": [
                {
                    "name": "John's Dropbox",
                    "default": True,
                    "email": "johnd_dropbox@gmail.com",
                    "default_upload_folder": "/openmates"
                }
            ]
        },
        "rss": {
            "feeds": [
                {
                    "name": "The Verge - Science",
                    "url": "https://www.theverge.com/rss/science/index.xml"
                }
            ]
        },
        "youtube": {
            "privacy":{
                "allowed_to_access_my_project_data": True,
                "allowed_to_access_my_goals": True,
                "allowed_to_access_my_todos": True,
                "allowed_to_access_my_recent_topics": True,
                "allowed_to_access_my_recent_emails": True,
                "allowed_to_access_my_calendar": True,
                "allowed_to_access_my_likes": True,
                "allowed_to_access_my_dislikes": True
            }
        }
    },
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
    "todos": [
        "learn TensorFlow",
        "check out new Python AI libraries"
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
    ],
    "recent_emails": {
        "work_emails": {
            "incoming": [
                {
                    "subject": "Meeting with the AI team",
                    "from": "AI Team",
                    "date": "2021-09-01T09:00:00Z",
                    "read": False,
                    "summary": "We have a meeting to discuss the AI integration into the sales software."
                },
                {
                    "subject": "New AI team member",
                    "from": "AI Team",
                    "date": "2021-09-01T10:00:00Z",
                    "read": False,
                    "summary": "We have a new team member joining the AI team."
                }
            ]
        }
    },
    "calendar": {
        "2024-08-01T09:00:00Z": {
            "title": "Meeting with the AI team",
            "description": "We have a meeting to discuss the AI integration into the sales software."
        },
        "2024-08-01T10:00:00Z": {
            "title": "Sales software demo",
            "description": "Demo of the updated sales software with AI integration."
        }
    }
}