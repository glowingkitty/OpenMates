from server.api.models.teams.teams_get_all import TeamsGetAllOutput

async def get_teams(
    page: int = 1,
    pageSize: int = 25
) -> TeamsGetAllOutput:
    """Get all teams on the OpenMates server"""
    # TODO add processing
    return TeamsGetAllOutput(teams=[])