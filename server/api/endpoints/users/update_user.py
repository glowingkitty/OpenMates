

async def update_user(
        id: int,
        uid: str = None,
        api_token: str = None,
        username: str = None,
        email: str = None,
        teams: list[int] = None, # the ids of the team
        profile_image: str = None,
        balance_eur: float = None,
        mates_default_privacy_settings__allowed_to_access_name: bool = None,
        mates_default_privacy_settings__allowed_to_access_username: bool = None,
        mates_default_privacy_settings__allowed_to_access_projects: bool = None,
        mates_default_privacy_settings__allowed_to_access_goals: bool = None,
        mates_default_privacy_settings__allowed_to_access_todos: bool = None,
        mates_default_privacy_settings__allowed_to_access_recent_topics: bool = None,
        mates_default_privacy_settings__allowed_to_access_recent_emails: bool = None,
        mates_default_privacy_settings__allowed_to_access_calendar: bool = None,
        mates_default_privacy_settings__allowed_to_access_likes: bool = None,
        mates_default_privacy_settings__allowed_to_access_dislikes: bool = None,
        mate_configs: list[int] = None,
        app_settings: dict = None,
        other_settings: dict = None,
        projects: list[int] = None

        # TODO add missing fields and processing
    ):
    pass