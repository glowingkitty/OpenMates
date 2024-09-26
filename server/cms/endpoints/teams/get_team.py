from typing import Optional
from server.cms.cms import make_strapi_request, get_nested
from server.api.models.teams.teams_get_one import Team
from fastapi import HTTPException


async def get_team(
        team_slug: Optional[str] = None,
        discord_guild_id: Optional[str] = None
    ) -> Team:
    """
    Get a specific team.
    """
    try:
        fields = [
            "name",
            "slug",
            "balance",
            "monthly_usage_limit_per_user",
            "discord_guild_id"
        ]
        populate = []
        # populate = [
        #     "mates.username",
        # ]
        filters = []
        if team_slug:
            filters.append({
                "field": "slug",
                "operator": "$eq",
                "value": team_slug
            })
        if discord_guild_id:
            filters.append({
                "field": "discord_guild_id",
                "operator": "$eq",
                "value": discord_guild_id
            })
        status_code, json_response = await make_strapi_request(
            method="get",
            endpoint="teams",
            filters=filters,
            fields=fields,
            populate=populate
        )
        if status_code == 200:
            team = json_response["data"]
            if len(team) == 0:
                raise HTTPException(status_code=404, detail="Team not found")
            elif len(team) > 1:
                raise HTTPException(status_code=404, detail="Multiple teams found")
            else:
                team = Team(
                    id=team["id"],
                    name=team["name"],
                    slug=team["slug"],
                    balance=team["balance"],
                    discord_guild_id=team["discord_guild_id"]
                )
                return team

        else:
            raise HTTPException(status_code=status_code, detail=json_response["detail"])

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))