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

from server.api.models.skills.videos.skills_videos_get_transcript import VideosGetTranscriptInput, VideosGetTranscriptOutput
from server.api.endpoints.skills.videos.providers.youtube.get_transcript import get_transcript as get_transcript_youtube


async def get_transcript(
        url: str,
        block_token_limit:int=None
        ) -> VideosGetTranscriptOutput:

    input_data = VideosGetTranscriptInput(
        url=url,
        block_token_limit=block_token_limit
    )

    add_to_log(module_name="Videos | Transcript", color="yellow", state="start")
    add_to_log(f"Getting transcript for video at URL: {input_data.url}")

    if 'youtube.com' in input_data.url:
        return await get_transcript_youtube(**input_data.model_dump())