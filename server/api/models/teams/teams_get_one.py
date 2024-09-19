from pydantic import BaseModel, Field
from typing import List, Dict, Optional

class Team(BaseModel):
    id: int = Field(..., description="Team ID")
    name: str = Field(..., description="Team name")
    slug: str = Field(..., description="Team slug")
    mates: Optional[List[str]] = Field(None, description="List of mate usernames in the team")
    settings: Optional[Dict[str, str]] = Field(None, description="Team settings")
    invoices: Optional[List[str]] = Field(None, description="List of invoice IDs")
    forbidden_skills: Optional[List[str]] = Field(None, description="List of forbidden skill slugs")
    profile_image_url: Optional[str] = Field(None, description="URL of the team's profile image")
    balance_credits: Optional[int] = Field(None, description="Team balance in credits")
    users_allowed_to_use_team_balance: Optional[List[str]] = Field(None, description="List of usernames allowed to use team balance")
    user_count: Optional[int] = Field(None, description="Number of users in the team")
    admin_count: Optional[int] = Field(None, description="Number of admins in the team")
    discord_guild_id: Optional[str] = Field(None, description="Discord guild ID")

teams_get_one_output_example = {
    "id": 1,
    "name": "OpenMates Enthusiasts",
    "slug": "openmates_enthusiasts",
    "mates": ["sophia", "alex"],
    "settings": {"privacy_level": "high", "default_language": "en"},
    "invoices": ["INV-001", "INV-002"],
    "forbidden_skills": ["delete_data", "send_email"],
    "profile_image_url": "https://example.com/team_image.jpg",
    "balance_credits": 129920,
    "users_allowed_to_use_team_balance": ["john", "jane"],
    "user_count": 10,
    "admin_count": 2,
    "discord_guild_id": "1234567890"
}