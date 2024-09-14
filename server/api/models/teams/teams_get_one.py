from pydantic import BaseModel, Field
from typing import List, Dict, Optional

class Team(BaseModel):
    id: str = Field(..., description="Team ID")
    name: str = Field(..., description="Team name")
    slug: str = Field(..., description="Team slug")
    mates: List[str] = Field(..., description="List of mate usernames in the team")
    settings: Dict[str, str] = Field(..., description="Team settings")
    invoices: List[str] = Field(..., description="List of invoice IDs")
    forbidden_skills: List[str] = Field(..., description="List of forbidden skill slugs")
    profile_image_url: Optional[str] = Field(None, description="URL of the team's profile image")
    balance: float = Field(..., description="Team balance")
    users_allowed_to_use_team_balance: List[str] = Field(..., description="List of usernames allowed to use team balance")
    user_count: int = Field(..., description="Number of users in the team")
    admin_count: int = Field(..., description="Number of admins in the team")
    discord_guild_id: Optional[str] = Field(None, description="Discord guild ID")

teams_get_one_output_example = {
    "id": "1234567890",
    "name": "OpenMates Enthusiasts",
    "slug": "openmates_enthusiasts",
    "mates": ["sophia", "alex"],
    "settings": {"privacy_level": "high", "default_language": "en"},
    "invoices": ["INV-001", "INV-002"],
    "forbidden_skills": ["delete_data", "send_email"],
    "profile_image_url": "https://example.com/team_image.jpg",
    "balance": 1000.50,
    "users_allowed_to_use_team_balance": ["john", "jane"],
    "user_count": 10,
    "admin_count": 2,
    "discord_guild_id": "1234567890"
}