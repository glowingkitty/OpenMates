
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

from server import *
################

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled
from fastapi import HTTPException
from server.api.models.skills.videos.skills_videos_get_transcript import VideosGetTranscriptInput, VideosGetTranscriptOutput
import tiktoken

def format_time(seconds: float) -> str:
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{seconds:06.3f}"

def count_tokens(
        message: str = None,
        message_history: list = None,
        model_name: str = "gpt-3.5-turbo") -> int:
    try:
        add_to_log(state="start", module_name="LLMs", color="yellow")
        add_to_log(f"Counting the tokens ...")

        if message_history and not message:
            message = ""
            for message_item in message_history:
                if message_item.get("message"):
                    message += message_item["message"]
                elif message_item.get("content"):
                    if type(message_item["content"]) == list:
                        for content_item in message_item["content"]:
                            if content_item.get("text"):
                                message += content_item["text"]
                    else:
                        message += message_item["content"]

        message = str(message)
        if model_name == "gpt-3.5":
            model_name = "gpt-3.5-turbo"
        encoding = tiktoken.encoding_for_model(model_name)
        tokens = len(encoding.encode(message))

        add_to_log(state="success", message=f"Successfully counted the tokens: {tokens}")

        return tokens


    except Exception:
        add_to_log(state="error", message=traceback.format_exc())
        return None


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
        add_to_log(state="error", message=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to get the transcript for this video.")