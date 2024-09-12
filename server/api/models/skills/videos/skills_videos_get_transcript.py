
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

from pydantic import BaseModel, Field, field_validator, ConfigDict


# POST /{team_slug}/skills/video/transcript (get transcript of a video)

class VideosGetTranscriptInput(BaseModel):
    """This is the model for the incoming parameters for POST /{team_slug}/skills/video/transcript"""
    url: str = Field(..., description="URL of the YouTube video", min_length=26, max_length=60)
    block_token_limit: int | None = Field(None, description="Maximum number of tokens per transcript block. If None, no limit is applied.")

    # prevent extra fields from being passed to API
    model_config = ConfigDict(extra="forbid")

    @field_validator('url')
    @classmethod
    def url_must_be_youtube_url(cls, v):
        if not re.search(r"youtube\.com/watch\?v=[a-zA-Z0-9_-]+$", v):
            raise ValueError('URL must be a valid YouTube video URL')
        return v


videos_get_transcript_input_example = {
    "url": "https://www.youtube.com/watch?v=ZJbu3NEPJN0"
}


class VideosGetTranscriptOutput(BaseModel):
    """This is the model for the output of POST /{team_slug}/skills/videos/transcript"""
    transcript: dict[str,str] = Field(..., description="Transcript of the YouTube video with timestamps as keys and text as values.")

    @field_validator('transcript')
    @classmethod
    def validate_transcript_format(cls, v):
        for timestamp, text in v.items():
            if not re.match(r'^\d{2}:\d{2}:\d{2}\.\d{3}$', timestamp):
                raise ValueError(f'Invalid timestamp format: {timestamp}')
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f'Invalid text for timestamp {timestamp}')
        return v


videos_get_transcript_output_example = {
    "transcript": {
        "00:00:00.120": "it's smarter in most ways cheaper faster",
        "00:00:03.959": "better at coding multimodal in and out",
        "00:00:07.560": "and perfectly timed to steal the",
        "00:00:09.880": "spotlight from Google it's gp4 Omni I've",
        "00:00:14.080": "gone through all the benchmarks and the",
        "00:00:16.480": "release videos to give you the",
        "00:00:18.640": "highlights my first reaction was it's",
        "00:00:21.039": "more flirtatious sigh than AGI but a",
        "00:00:25.560": "notable step forward nonetheless first",
        "00:00:28.039": "things first GPT 40 meaning Omni which",
        "00:00:31.320": "is all or everywhere referencing the",
        "00:00:34.239": "different modalities it's got is Free by"
    }
}