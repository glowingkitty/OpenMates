
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


# GET /users/{user_username} (get a user)

class User(BaseModel):
    """This is the base model for a user"""
    id: int = Field(..., description="ID of the user")
    username: str = Field(..., description="Username of the user")
    email: str = Field(..., description="Email address of the user")
    profile_picture_url: str = Field(..., description="URL of the profile picture of the user")
    balance: float = Field(..., description="Balance of the user. This balance can be used for using paid skills.")
    software_settings: dict = Field(..., description="Software settings, such as privacy settings, which cloud accounts are connected, default settings and more.")
    other_settings: dict = Field(..., description="Other settings, such as notification settings, etc.")
    projects: List[Project] = Field(..., description="Projects of the user")
    goals: List[dict] = Field(..., description="Goals and priorities of the user, related to projects, learning, finances etc.")
    todos: List[str] = Field(..., description="List of current To Do's of the user")
    recent_topics: List[str] = Field(..., description="Recent topics the user asked the AI team mates about.")


users_get_one_output_example = {
    "id": 1,
    "username": "johnd",
    "email": "johnd_openmates@gmail.com",
    "profile_picture_url": "/{team_url}/uploads/johnd_image.jpeg",
    "balance": 100.0,
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
                "allowed_to_access_my_recent_topics": True
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
    "goals": [
        {
            "name": "Release the updated sales software with AI integration",
            "priority": 1,
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
        "sales software"
        "FastAPI",
        "Docker"
    ]
}