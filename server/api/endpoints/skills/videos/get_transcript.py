from server.api.models.skills.videos.skills_videos_get_transcript import VideosGetTranscriptInput, VideosGetTranscriptOutput
from server.api.endpoints.skills.videos.providers.youtube.get_transcript import get_transcript as get_transcript_youtube

import logging
from fastapi import HTTPException
# Set up logger
logger = logging.getLogger(__name__)


async def get_transcript(
        url: str,
        block_token_limit:int=None
        ) -> VideosGetTranscriptOutput:

    input_data = VideosGetTranscriptInput(
        url=url,
        block_token_limit=block_token_limit
    )

    logger.debug(f"Getting transcript for video at URL: {input_data.url}")

    if 'youtube.com' in input_data.url:
        return await get_transcript_youtube(**input_data.model_dump())
    else:
        raise HTTPException(status_code=400, detail="Unsupported video platform")
