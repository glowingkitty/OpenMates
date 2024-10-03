from fastapi import HTTPException
from server.api.endpoints.apps.files.providers.openmates.upload import upload as openmates_upload
from server.api.models.apps.files.skills_files_upload import FilesUploadOutput
from typing import List, Optional

import logging

logger = logging.getLogger(__name__)


async def upload(
    team_slug: str,
    api_token: str,
    provider: str,
    file_name: str,
    file_data: bytes,
    expiration_datetime: str,
    access_public: bool = False,
    folder_path: Optional[str] = None,
    read_access_limited_to_teams: Optional[List[int]] = None,
    read_access_limited_to_users: Optional[List[int]] = None,
    write_access_limited_to_teams: Optional[List[int]] = None,
    write_access_limited_to_users: Optional[List[int]] = None
) -> FilesUploadOutput:
    """
    Upload a file to a provider
    """
    logger.info(f"Uploading file to provider {provider}")

    if provider == "dropbox":
        # return await dropbox_upload(file_path)
        # TODO: implement dropbox upload
        pass
    else:
        return await openmates_upload(
            file_name=file_name,
            team_slug=team_slug,
            file_data=file_data,
            folder_path=folder_path,
            api_token=api_token,
            expiration_datetime=expiration_datetime,
            access_public=access_public,
            read_access_limited_to_teams=read_access_limited_to_teams,
            read_access_limited_to_users=read_access_limited_to_users,
            write_access_limited_to_teams=write_access_limited_to_teams,
            write_access_limited_to_users=write_access_limited_to_users
        )