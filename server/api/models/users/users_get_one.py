from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, ClassVar, Dict, Any
from server.api.models.projects.projects_get_one import Project
from pydantic import model_validator
import json
import logging
from server.api.models.apps.skills_get_one import SkillMini

logger = logging.getLogger(__name__)

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


class MateConfig(BaseModel):
    id: int = Field(..., description="ID of the Mate config")
    mate_username: str = Field(..., description="Username of the AI team mate this config is for.")
    team_slug: str = Field(..., description="Slug of the team this config is for.")
    systemprompt: Optional[str] = Field(None, description="Custom system prompt for the AI team mate.")
    llm_endpoint: Optional[str] = Field(None, description="The API endpoint of the Large Language Model (LLM) which is used by the AI team mate.")
    llm_model: Optional[str] = Field(None, description="The LLM model which is used by the AI team mate.")
    skills: Optional[list[SkillMini]] = Field(None, description="Custom selection of skills the AI team mate can use")
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


class MyTeam(BaseModel):
    id: int = Field(..., description="ID of the team")
    name: str = Field(..., description="Name of the team")
    slug: str = Field(..., description="Slug of the team")
    admin: bool = Field(..., description="Whether the user is an admin of the team")

# GET /users/{user_username} (get a user)

class UserGetOneInput(BaseModel):
    team_slug: Optional[str] = Field(None, description="Slug of the team the user is a member of")
    user_id: str = Field(None, description="ID of the user")
    api_token: str = Field(None, description="API token of the user")
    user_access: str = Field("basic_access", description="Access level of the user.")
    username: str = Field(None, description="Username of the user")
    password: Optional[str] = Field(None, description="Password of the user")
    fields: Optional[List[str]] = Field(None, description="Fields of the user to include in the response")

    # if api_token is given and user_id is not given, then auto set user_id to the first 32 characters of the api_token
    @model_validator(mode='after')
    def set_user_id(self):
        """Set user_id to the first 32 characters of api_token if user_id is not provided."""
        if not self.user_id and self.api_token:
            self.user_id = self.api_token[:32]

class UserGetOneOutput(BaseModel):
    """This is the base model for a user"""
    model_config = ConfigDict(extra='allow')

    id: str = Field(..., description="ID of the user")
    username: str = Field(..., description="Username of the user")
    email: Optional[str] = Field(None, description="Email address of the user")
    teams: Optional[List[MyTeam]] = Field(None, description="Teams the user is a member of")
    profile_image: Optional[str] = Field(None, description="URL of the profile picture of the user")
    balance_credits: Optional[int] = Field(None, description="Balance of the user in credits. This balance can be used for using skills.")
    mates_default_privacy_settings: Optional[DefaultPrivacySettings] = Field(None, description="The default privacy settings for the AI team mates, which the user communicates with.")
    mate_configs: Optional[list[MateConfig]] = Field(None, description="Custom settings for the AI team mates, such as system prompt, privacy settings, etc.")
    other_settings: Optional[dict] = Field(None, description="Other settings, such as notification settings, etc.")
    projects: Optional[List[Project]] = Field(None, description="Projects of the user")
    likes: Optional[List[str]] = Field(None, description="List of topics the user is interested in")
    dislikes: Optional[List[str]] = Field(None, description="List of topics the user is not interested in")
    topics_outside_my_bubble_that_i_should_consider: Optional[List[str]] = Field(None, description="List of topics the user is not interested in, but should consider")
    goals: Optional[List[dict]] = Field(None, description="Goals and priorities of the user, related to projects, learning, finances etc.")
    recent_topics: Optional[List[str]] = Field(None, description="Recent topics the user asked the AI team mates about.")
    is_server_admin: Optional[bool] = Field(None, description="Whether the user is a server admin")

    api_output_fields: ClassVar[List[str]] = [
        'id',
        'username',
        'email',
        'teams',
        'profile_image',
        'balance_credits',
        'mates_default_privacy_settings',
        'mate_configs',
        'other_settings',
        'projects',
        'likes',
        'dislikes',
        'topics_outside_my_bubble_that_i_should_consider',
        'goals',
        'recent_topics',
        'is_server_admin'
    ]

    def to_api_output(self, fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """Convert User object to a dictionary suitable for API output."""
        if fields:
            user_dict = self.model_dump(include=fields, exclude_none=True)
        else:
            user_dict = self.model_dump(exclude_none=True)
        return user_dict


class UserGetOneOutputEncrypted(UserGetOneOutput):
    email: Optional[str] = Field(None, description="Encrypted Email address of the user")
    password: Optional[str] = Field(None, description="Encrypted password of the user")
    api_token: Optional[str] = Field(None, description="Encrypted API token of the user")
    other_settings: Optional[str] = Field(None, description="Encrypted Other settings, such as notification settings, etc.")
    likes: Optional[str] = Field(None, description="Encrypted likes of the user")
    dislikes: Optional[str] = Field(None, description="Encrypted dislikes of the user")
    goals: Optional[str] = Field(None, description="Encrypted goals of the user")
    recent_topics: Optional[str] = Field(None, description="Encrypted recent topics of the user")

    def to_redis_dict(self) -> Dict[str, str]:
        """Convert User object to a dictionary suitable for Redis storage."""
        user_dict = self.model_dump(exclude_none=True)
        for key, value in user_dict.items():
            if isinstance(value, (list, dict, BaseModel)):
                user_dict[key] = json.dumps(value, default=lambda o: o.model_dump() if isinstance(o, BaseModel) else None)
            elif isinstance(value, bool):
                user_dict[key] = str(value).lower()
            else:
                user_dict[key] = str(value)
        return user_dict

    @classmethod
    def from_redis_dict(cls, data: Dict[str, str]) -> 'UserGetOneOutput':
        """Create a User object from Redis data."""
        def parse_value(key: str, value: str) -> Any:
            if value.lower() in ('true', 'false'):
                return value.lower() == 'true'
            try:
                parsed = json.loads(value)
                if key == 'teams' and isinstance(parsed, list):
                    return [MyTeam(**team) for team in parsed]
                elif key == 'projects' and isinstance(parsed, list):
                    return [Project(**project) for project in parsed]
                elif key == 'mates_default_privacy_settings':
                    return DefaultPrivacySettings(**parsed)
                elif key == 'mate_configs' and isinstance(parsed, list):
                    return [MateConfig(**config) for config in parsed]
                return parsed
            except json.JSONDecodeError:
                return value

        parsed_data = {k: parse_value(k, v) for k, v in data.items()}
        return cls(**parsed_data)


users_get_one_output_example = {
    "id": "caa778864ce8ac4b0a820f750643ddd6",
    "username": "johnd",
    "email": "johnd_openmates@gmail.com",
    "teams": [
        {
            "id": 1,
            "name": "AI Sales Team",
            "slug": "ai-sales-team",
            "admin": True
        }
    ],
    "profile_image": "/v1/ai-sales-team/uploads/johnd_image.jpeg",
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
    "mate_configs": [],
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