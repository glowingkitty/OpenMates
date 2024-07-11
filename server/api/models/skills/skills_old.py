
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

from pydantic import BaseModel, Field, field_validator
from typing import List
from enum import Enum
from server.api.models.software import Software

##################################
######### Skills #################
##################################

## Base models

class Skill(BaseModel):
    id: int = Field(..., description="ID of the skill")
    name: str = Field(..., description="Name of the skill")
    description: str = Field(..., description="Description of the skill")
    software: Software = Field(..., description="Software related to the skill")
    api_endpoint: str = Field(..., description="API endpoint for the skill")

    @field_validator('api_endpoint')
    @classmethod
    def validate_api_endpoint(cls, v):
        pattern = r'^/v1/[a-z0-9-]+/skills/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$'
        if not re.match(pattern, v):
            raise ValueError(f"Invalid API endpoint format: {v}")
        return v


################
## YouTube Models
################
class OrderOptions(str, Enum):
    date = "date"
    rating = "rating"
    relevance = "relevance"
    title = "title"
    videoCount = "videoCount"
    viewCount = "viewCount"

class TypeOptions(str, Enum):
    video = "video"
    channel = "channel"
    playlist = "playlist"

class YouTubeSearch(BaseModel):
    query: str = Field(..., description="The search query to find videos.")
    max_age_days: int = Field(None, description="The maximum age of the videos in days.")
    max_results: int = Field(10, description="The maximum number of results to return.")
    order: OrderOptions = Field(OrderOptions.relevance.value, description="The order in which to return the results.")
    type: TypeOptions = Field(TypeOptions.video.value, description="The type of content to search for.")
    region: str = Field("US", description="The region in which to search for content.")

class YouTubeTranscript(BaseModel):
    url: str = Field(..., description="The URL of the YouTube video for which to get the transcript.")
