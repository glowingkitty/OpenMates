from pydantic import BaseModel, Field
from typing import List
from enum import Enum

##################################
######### Skills #################
##################################
    
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
    query: str = Field(..., 
                description="The search query to find videos.",
                example="Python programming tutorial"
                )
    max_age_days: int = Field(
                        None, 
                        description="The maximum age of the videos in days.", 
                        example=30
                        )
    max_results: int = Field(
                        10, 
                        description="The maximum number of results to return.", 
                        example=5
                        )
    order: OrderOptions = Field(
                OrderOptions.relevance.value, 
                description="The order in which to return the results.",
                )
    type: TypeOptions = Field(
                TypeOptions.video.value, 
                description="The type of content to search for.",
                )
    region: str = Field(
                "US", 
                description="The region in which to search for content.", 
                example="US"
                )

class YouTubeTranscript(BaseModel):
    url: str = Field(..., 
                description="The URL of the YouTube video for which to get the transcript.",
                example="https://www.youtube.com/watch?v=Dbog8Yw3kEM"
                )