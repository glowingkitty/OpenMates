
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
from slowapi.errors import RateLimitExceeded
from fastapi import FastAPI, Depends, Header, Request, HTTPException, APIRouter
from fastapi.staticfiles import StaticFiles
from server.api.models.mates import MatesAskInput, MatesAskOutput, MatesGetAllOutput, Mate
from server.api.endpoints.mates.mates_ask import mates_ask_processing
from server.api.endpoints.mates.get_mates import get_mates_processing
from server.api.endpoints.mates.get_mate import get_mate_processing
from server.api.verify_token import verify_token
from server.cms.strapi_requests import get_strapi_upload
from starlette.responses import FileResponse
from starlette.status import HTTP_429_TOO_MANY_REQUESTS


# Create new routers
mates_router = APIRouter()
skills_router = APIRouter()
workflows_router = APIRouter()
tasks_router = APIRouter()
billing_router = APIRouter()
server_router = APIRouter()
teams_router = APIRouter()
users_router = APIRouter()

# Create a limiter instance
limiter = Limiter(key_func=get_remote_address)

tags_metadata = [
    {
        "name": "Mates",
        "description": "<img src='images/mates.png' alt='Mates are your AI team members. They can help you with various tasks. Each mate is specialized in a different area.'>"
    },
    {
        "name": "Skills",
        "description": "<img src='images/skills.png' alt='Your team mate can use a wide range of skills. Or, you can call them directly via the API. For example: ChatGPT, StableDiffusion, Notion or Figma.'>"
    },
    {
        "name": "Workflows",
        "description": "<img src='images/workflows.png' alt='A skill is powerful. Combining multiple skills in a workflow is magical.'>"
    },
    {
        "name": "Tasks",
        "description": "<img src='images/tasks.png' alt='A task is a scheduled run of a single skill or a whole workflow. It can happen once, or repeated.'>"
    },
    {
        "name": "Billing",
        "description": "<img src='images/billing.png' alt='Manage your billing settings, download invoices and more.'>"
    },
    {
        "name": "Server",
        "description": "<img src='images/server.png' alt='Manage your OpenMates server. Change settings, see how the server is doing and more.'>"
    },
    {
        "name": "Teams",
        "description": "<img src='images/teams.png' alt='Manage the teams on your OpenMates server.'>"
    },
    {
        "name": "Users",
        "description": "<img src='images/users.png' alt='Manage user accounts of a team. A user can get personalized responses from mates and access to the OpenMates API.'>"
    }
]

app = FastAPI(
    title="OpenMates API",
    description=(
        "Allows your code to interact with OpenMates server.<br>"
        "<h2>How to get started</h1>"
        "<ol>"
        "<li>Login to your OpenMates account, go to the settings and find your API token there.</li>"
        "<li>Make a request to the endpoint you want to use. Make sure to include your 'token' in the header.</li>"
        "</ol>"
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

# Adding endpoints
app.mount("/images", StaticFiles(directory=os.path.join(os.path.dirname(__file__), 'endpoints/images')), name="images")
@app.get("/",include_in_schema=False)
@limiter.limit("20/minute")
def read_root(request: Request):
    return FileResponse(os.path.join(os.path.dirname(__file__), 'endpoints/index.html'))

# Forward the /uploads endpoint to the strapi server
@app.get("/{team_url}/uploads/{file_path:path}", include_in_schema=False)
@limiter.limit("20/minute")
async def get_upload(request: Request, team_url: str, token: str = Header(None,example="123456789",description="Your API token to authenticate and show you have access to the requested OpenMates server.")):
    # TODO: remove the need for the team parameter and properly check the token
    # TODO: consider what happens if a team is upload a custom image for a mate. How to handle this?
    # TODO: add team_url to the url, so that the team can only access their own files and mates and skills and so on
    # example: /{team_url}/uploads/{file_path:path}
    # example: /{team_url}/mates/{mate_username}
    # example: /{team_url}/skills/{skill_name}
    verify_token(
        team_url=team_url,
        token=token,
        scope="uploads:get"
        )
    return await get_strapi_upload(request.path_params['file_path'])



##################################
######### Mates ##################
##################################

# POST /mates/ask (Send a message to an AI team mate and you receive the response)
@mates_router.post("/{team_url}/mates/ask",response_model=MatesAskOutput, summary="Ask", description="<img src='images/mates/ask.png' alt='Send a ask to one of your AI team mates. It will then automatically decide what skills to use to answer your question or fulfill the task.'>")
@limiter.limit("20/minute")
def mates_ask(request: Request, team_url: str, parameters: MatesAskInput, token: str = Header(None,example="123456789",description="Your API token to authenticate and show you have access to the requested OpenMates server.")):
    verify_token(
        team_url=team_url,
        token=token,
        scope="mates:ask"
        )
    return mates_ask_processing(team_url=team_url, parameters=parameters)


# GET /mates (get all mates)
@mates_router.get("/{team_url}/mates/", response_model=MatesGetAllOutput, summary="Get all", description="<img src='images/mates/get_all.png' alt='Get an overview list of all AI team mates currently active on the OpenMates server.'>")
@limiter.limit("20/minute")
async def get_mates(request: Request, team_url: str, token: str = Header(None,example="123456789",description="Your API token to authenticate and show you have access to the requested OpenMates server.")):
    verify_token(
        team_url=team_url,
        token=token,
        scope="mates:get_all"
        )
    return await get_mates_processing(team_url=team_url)


# GET /mates/{mate_username} (get a mate)
@mates_router.get("/{team_url}/mates/{mate_username}", response_model=Mate, summary="Get mate", description="<img src='images/mates/get_mate.png' alt='Get all details about a specific mate. Including system prompt, available skills and more.'>")
@limiter.limit("20/minute")
def get_mate(request: Request, team_url: str, mate_username: str, token: str = Depends(verify_token)):
    return get_mate_processing(mate_username)


# POST /mates (create a new mate)
@mates_router.post("/{team_url}/mates/", summary="Create", description="<img src='images/mates/create.png' alt='Create a new mate on the OpenMates server, with a custom system prompt, accessible skills and other settings.'>")
@limiter.limit("20/minute")
def create_mate(request: Request, team_url: str, token: str = Depends(verify_token)):
    return {"info": "endpoint still needs to be implemented"}


# PATCH /mates/{mate_username} (update a mate)
@mates_router.patch("/{team_url}/mates/{mate_username}", summary="Update", description="<img src='images/mates/update.png' alt='Update an existing mate on the server. For example change the system prompt, the available skills and more.'>")
@limiter.limit("20/minute")
def update_mate(request: Request, team_url: str, mate_username: str, token: str = Depends(verify_token)):
    return {"info": "endpoint still needs to be implemented"}




##################################
######### Skills #################
##################################

# Explaination:
# A skill is a single piece of functionality that a mate can use to help you. For example, ChatGPT, StableDiffusion, Notion or Figma.

# POST /skills/chatgpt/ask (ask a question to ChatGPT from OpenAI)
@skills_router.post("/{team_url}/skills/chatgpt/ask", summary="ChatGPT | Ask", description="<img src='images/skills/chatgpt/ask.png' alt='Ask ChatGPT from OpenAI a question, and it will answer it based on its knowledge.'>")
@limiter.limit("20/minute")
def skill_chatgpt_ask(request: Request, team_url: str,token: str = Depends(verify_token)):
    return {"info": "endpoint still needs to be implemented"}


# POST /skills/claude/message (ask a question to Claude from Anthropic)
@skills_router.post("/{team_url}/skills/claude/ask", summary="Claude | Ask", description="<img src='images/skills/claude/ask.png' alt='Ask Claude from Anthropic a question, and it will answer it based on its knowledge.'>")
@limiter.limit("20/minute")
def skill_claude_ask(request: Request, team_url: str, token: str = Depends(verify_token)):
    return {"info": "endpoint still needs to be implemented"}


# POST /skills/youtube/ask (ask a question about a video)
@skills_router.post("/{team_url}/skills/youtube/ask", summary="YouTube | Ask", description="<img src='images/skills/youtube/ask.png' alt='Ask a question about a video, and Claude will answer it based on the transcript and video details.'>")
@limiter.limit("20/minute")
def skill_youtube_ask(request: Request, team_url: str, token: str = Depends(verify_token)):
    return {"info": "endpoint still needs to be implemented"}


# # GET /skills/youtube/search (search YouTube for videos)
# @skills_router.get("/youtube/search", summary="YouTube | Search", description="<img src='images/skills/youtube/search.png' alt='Search & filter for videos on YouTube.'>")
# @limiter.limit("20/minute")
# def skill_youtube_search(request: Request, parameters: YouTubeSearch, token: str = Depends(verify_token)):
#     return search_youtube(
#         parameters.query, 
#         parameters.max_results, 
#         parameters.order, 
#         parameters.type, 
#         parameters.region, 
#         parameters.max_age_days)

# # GET /skills/youtube/transcript (get transcript for a YouTube video)
# @skills_router.get("/youtube/transcript", summary="YouTube | Transcript", description="<img src='images/skills/youtube/transcript.png' alt='Get the full transcript of a YouTube video.'>")
# @limiter.limit("20/minute")
# def skill_youtube_transcript(request: Request, parameters: YouTubeTranscript, token: str = Depends(verify_token)):
#     return get_video_transcript(parameters.url)


##################################
######### Workflows ##############
##################################

# Explaination:
# A workflow is a sequence of skills that are executed in a specific order, to fullfill a task.




##################################
######### Tasks ##################
##################################

# Explaination:
# A task is a scheduled run of a single skill or a whole workflow. It can happen once, or repeated.




##################################
######### Billing ################
##################################

# Explaination:
# The billing endpoints allow users or team owners to manage their billing settings, download invoices and more.




##################################
######### Server #################
##################################

# Explaination:
# The server is the core software that runs OpenMates.

# GET /server/status (get server status)
@server_router.get("/server/status", summary="Status", description="<img src='images/server/status.png' alt='Get a summary of your current server status.'>")
@limiter.limit("20/minute")
def get_status(request: Request, token: str = Depends(verify_token)):
    return {"status": "online"}


# GET /server/settings (get server settings)
@server_router.get("/server/settings", summary="Get settings", description="<img src='images/server/get_settings.png' alt='Get all the current settings of your OpenMates server.'>")
@limiter.limit("20/minute")
def get_settings(request: Request, token: str = Depends(verify_token)):
    return {"info": "endpoint still needs to be implemented"}


# PATCH /server/settings (update server settings)
@server_router.patch("/server/settings", summary="Update settings", description="<img src='images/server/update_settings.png' alt='Update any of the setting on your OpenMates server.'>")
@limiter.limit("20/minute")
def update_settings(request: Request, token: str = Depends(verify_token)):
    return {"info": "endpoint still needs to be implemented"}



##################################
######### Teams ##################
##################################

# Explaination:
# A server can have multiple teams. Each team can have multiple users and multiple mates. Teams can be used to separate different work environments, departments or companies.




##################################
########## Users #################
##################################

# Explaination:
# User accounts are used to store user data like what projects the user is working on, what they are interested in, what their goals are, etc.
# The OpenMates admin can choose if users who message mates via the chat software (mattermost, slack, etc.) are required to have an account. If not, the user will be treated as a guest without personalized responses.

# GET /users (get all users)
@users_router.get("/{team_url}/users/", summary="Get all", description="<img src='images/users/get_all.png' alt='Get an overview list of all users on your OpenMates server.'>")
@limiter.limit("20/minute")
def get_users(request: Request, team_url: str, token: str = Depends(verify_token)):
    return {"info": "endpoint still needs to be implemented"}


# GET /users/{username} (get a user)
@users_router.get("/{team_url}/users/{username}", summary="Get", description="<img src='images/users/get_user.png' alt='Get all details about a specific user.'>")
@limiter.limit("20/minute")
def get_user(request: Request, team_url: str, username: str, token: str = Depends(verify_token)):
    return {"info": "endpoint still needs to be implemented"}


# POST /users (create a new user)
@users_router.post("/{team_url}/users/", summary="Create", description="<img src='images/users/create.png' alt='Create a new user on your OpenMates server.'>")
@limiter.limit("20/minute")
def create_user(request: Request, team_url: str, username: str, token: str = Depends(verify_token)):
    return {"info": "endpoint still needs to be implemented"}


# PATCH /users/{username} (update a user)
@users_router.patch("/{team_url}/users/{username}", summary="Update", description="<img src='images/users/update.png' alt='Update a user on your OpenMates server.'>")
@limiter.limit("20/minute")
def update_user(request: Request, team_url: str, username: str, token: str = Depends(verify_token)):
    return {"info": "endpoint still needs to be implemented"}




# Include the routers in your FastAPI application
app.include_router(mates_router,        tags=["Mates"])
app.include_router(skills_router,       tags=["Skills"])
app.include_router(workflows_router,    tags=["Workflows"])
app.include_router(tasks_router,        tags=["Tasks"])
app.include_router(billing_router,      tags=["Billing"])
app.include_router(server_router,       tags=["Server"])
app.include_router(teams_router,        tags=["Teams"])
app.include_router(users_router,        tags=["Users"])

if __name__ == "__main__":
    uvicorn.run("server.api.api:app", host="0.0.0.0", port=8000, log_level="info")