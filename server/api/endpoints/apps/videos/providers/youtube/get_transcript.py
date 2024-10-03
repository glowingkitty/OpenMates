from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled
from fastapi import HTTPException
from server.api.models.apps.videos.skills_videos_get_transcript import VideosGetTranscriptInput, VideosGetTranscriptOutput
import tiktoken
import logging

# Set up logger
logger = logging.getLogger(__name__)


def format_time(seconds: float) -> str:
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{seconds:06.3f}"

def count_tokens(
        message: str = None,
        message_history: list = None,
        model_name: str = "gpt-3.5-turbo") -> int:
    try:

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

        return tokens


    except Exception:
        logger.exception(f"An error occurred while counting the tokens")
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

        logger.debug(f"Getting transcript for video at URL: {input_data.url}")

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

        logger.debug(f"Got transcript for video at URL: {url}")

        # Return the transcript as a dictionary
        return VideosGetTranscriptOutput(
            transcript=transcript_blocks
        )

    except TranscriptsDisabled:
        logger.error(f"Currently there is no transcript available for the url '{input_data.url}'")
        raise HTTPException(status_code=404, detail="Currently there is no transcript available for this video.")

    except Exception:
        logger.exception(f"An error occurred while getting the transcript for this video.")
        raise HTTPException(status_code=500, detail="Failed to get the transcript for this video.")
