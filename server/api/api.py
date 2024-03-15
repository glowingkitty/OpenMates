
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

import uvicorn
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from fastapi import FastAPI
from server.api.models import OutgoingMessage, IncomingMessage, MatesResponse, YouTubeSearch, YouTubeTranscript
from server.api.endpoints.process_message import process_message
from server.api.endpoints.get_mates import get_all_mates
from fastapi import Depends
from server.api.verify_token import verify_token
from slowapi.errors import RateLimitExceeded
from fastapi import HTTPException
from starlette.status import HTTP_429_TOO_MANY_REQUESTS
from fastapi import Request
from skills.youtube.search import search_youtube
from skills.youtube.get_video_transcript import get_video_transcript
from fastapi import APIRouter

# Create new routers
mates_router = APIRouter()
skills_router = APIRouter()
youtube_router = APIRouter()

# Create a limiter instance
limiter = Limiter(key_func=get_remote_address)

tags_metadata = [
    {
        "name": "Mates",
        "description": "Mates are your AI team members. They can help you with various tasks.",
    },
    {
        "name": "Skills",
        "description": "Your team mates can perform various skills. But you can also use these skills directly via the API.",
    },
]

app = FastAPI(
    title="OpenMates API",
    description=(
        "Allows your code to interact with OpenMates server.\n"
        "# How to get started \n"
        "1. Login to your OpenMates account, go to the settings and find your API token there. \n"
        "2. Make a request to the endpoint you want to use. Make sure to include your 'token' in the header."
    ),
    version="1.0.0",
    redoc_url="/docs", 
    docs_url="/swagger_docs",
    openapi_tags=tags_metadata
    )

# Add the limiter as middleware
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def ratelimit_handler(request, exc):
    raise HTTPException(
        status_code=HTTP_429_TOO_MANY_REQUESTS, 
        detail="Too Many Requests"
    )

# Adding all GET endpoints
@mates_router.get("/all", response_model=MatesResponse, summary="Get all", description="This endpoint returns a list of all AI team mates on the server.")
@limiter.limit("20/minute")
def get_mates(request: Request, token: str = Depends(verify_token)):
    return get_all_mates()




# Adding all POST endpoints
######## /message ########
# Send a message to an AI team mate and you receive the response
@mates_router.post("/message",response_model=OutgoingMessage, summary="Message", description="This endpoint sends a message to an AI team mate and returns the response.")
@limiter.limit("20/minute")
def send_message(request: Request, parameters: IncomingMessage, token: str = Depends(verify_token)):
    return process_message(parameters)

######## /skills/youtube/search ########
# Search YouTube for videos
@youtube_router.get("/search", summary="YouTube | Search", description="This endpoint searches YouTube for videos.")
@limiter.limit("20/minute")
def skill_youtube_search(request: Request, parameters: YouTubeSearch, token: str = Depends(verify_token)):
    return search_youtube(
        parameters.query, 
        parameters.max_results, 
        parameters.order, 
        parameters.type, 
        parameters.region, 
        parameters.max_age_days)

######## /skills/youtube/transcript ########
# Get the transcript for a YouTube video
@youtube_router.get("/transcript", summary="YouTube | Transcript", description="This endpoint gets the transcript for a YouTube video.")
@limiter.limit("20/minute")
def skill_youtube_transcript(request: Request, parameters: YouTubeTranscript, token: str = Depends(verify_token)):
    return get_video_transcript(parameters.url)



# Include the 'YouTube' router in the 'Skills' router
skills_router.include_router(youtube_router, prefix="/youtube")

# Include the 'Mates' router in your FastAPI application
app.include_router(mates_router, prefix="/mates", tags=["Mates"])
# Include the 'Skills' router in your FastAPI application
app.include_router(skills_router, prefix="/skills", tags=["Skills"])


if __name__ == "__main__":
    uvicorn.run("server.api.api:app", host="0.0.0.0", port=8000, log_level="info")