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



async def update_user(
        id: int,
        uid: str = None,
        api_token: str = None,
        username: str = None,
        email: str = None,
        teams: list[int] = None, # the ids of the team
        profile_picture_url: str = None,
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
        mates_custom_settings: list[int] = None,
        software_settings: dict = None,
        other_settings: dict = None,
        projects: list[int] = None

        # TODO add missing fields and processing
    ):
    pass