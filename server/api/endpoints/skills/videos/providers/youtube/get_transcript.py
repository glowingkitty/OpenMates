from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled
import os
import re
import sys

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

from skills.intelligence.costs.count_tokens import count_tokens
from fastapi import HTTPException
from server.api.models.skills.videos.skills_videos_get_transcript import VideosGetTranscriptInput, VideosGetTranscriptOutput


def format_time(seconds: float) -> str:
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{seconds:06.3f}"


async def get_transcript(
        url: str,
        block_token_limit:int=None
        ) -> VideosGetTranscriptOutput:
    try:
        input_data = VideosGetTranscriptInput(
            url=url,
            block_token_limit=block_token_limit
        )

        add_to_log(module_name="YouTube | Transcript", color="yellow", state="start")
        add_to_log(f"Getting transcript for video at URL: {input_data.url}")

        # Extract the video ID from the URL
        video_id = input_data.url.split("v=")[1]

        # Get the transcript for the video ID
        transcript = YouTubeTranscriptApi.get_transcript(video_id)

        # Create a dictionary with timestamps as keys and text as values
        transcript_blocks = {}
        token_count = 0
        for entry in transcript:
            start_time = format_time(entry['start'])
            text = entry['text']
            text_tokens = count_tokens(text)
            if input_data.block_token_limit is not None and token_count + text_tokens > input_data.block_token_limit:
                transcript_blocks[start_time] = text
                token_count = text_tokens
            else:
                if start_time in transcript_blocks:
                    transcript_blocks[start_time] += text
                else:
                    transcript_blocks[start_time] = text
                token_count += text_tokens

        add_to_log(f"Got transcript for video at URL: {url}", state="success")

        # Return the transcript as a dictionary
        return VideosGetTranscriptOutput(
            transcript=transcript_blocks
        )

    except TranscriptsDisabled:
        add_to_log(f"Currently there is no transcript available for the url '{input_data.url}'", state="error")
        raise HTTPException(status_code=404, detail="Currently there is no transcript available for this video.")

    except Exception:
        process_error(f"Failed to get the transcript for the video url '{input_data.url}'", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to get the transcript for this video.")