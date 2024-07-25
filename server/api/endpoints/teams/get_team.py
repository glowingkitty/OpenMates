from server.api.models.teams.teams_get_one import Team

async def get_team(
        team_slug: str,
        user_api_token: str
    ) -> Team:
    """Get all details about a specific team"""
    # TODO: Implement the actual logic to fetch team details
    # This is a placeholder implementation
    return Team(
        mates=["sophia", "alex"],
        settings={"privacy_level": "high", "default_language": "en"},
        invoices=["INV-001", "INV-002"],
        forbidden_skills=["delete_data", "send_email"],
        slug=team_slug,
        profile_image_url="https://example.com/team_image.jpg",
        balance=1000.50,
        users_allowed_to_use_team_balance=["john", "jane"],
        user_count=10,
        admin_count=2
    )