
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
from fastapi import FastAPI, Depends, Request, HTTPException, APIRouter, Path
from fastapi.staticfiles import StaticFiles
from server.api.models.mates.mates_ask import (
    MatesAskInput,
    mates_ask_input_example,
    mates_ask_output_example
)
from server.api.models.mates.mates_get_all import (
    mates_get_all_output_example
)
from server.api.models.mates.mates_get_one import (
    mates_get_one_output_example
)
from server.api.models.mates.mates_create import (
    MatesCreateInput,
    mates_create_input_example,
    mates_create_output_example
)
from server.api.models.mates.mates_update import (
    MatesUpdateInput,
    mates_update_input_example,
    mates_update_output_example
)
from server.api.models.users.users_get_one import (
    users_get_one_output_example
)
from server.api.models.users.users_get_all import (
    users_get_all_output_example
)
from server.api.endpoints.mates.mates_ask import mates_ask_processing
from server.api.endpoints.mates.get_mates import get_mates_processing
from server.api.endpoints.mates.get_mate import get_mate_processing
from server.api.endpoints.mates.create_mate import create_mate_processing
from server.api.endpoints.mates.update_mate import update_mate_processing
from server.api.endpoints.users.get_user import get_user_processing
from server.api.endpoints.users.get_users import get_users_processing
from server.api.validation.validate_file_access import validate_file_access
from server.api.validation.validate_token import validate_token
from server.cms.strapi_requests import get_strapi_upload
from starlette.responses import FileResponse
from starlette.status import HTTP_429_TOO_MANY_REQUESTS
from fastapi.openapi.utils import get_openapi
from server.api.parameters import set_example, tags_metadata, endpoint_metadata, input_parameter_descriptions
from fastapi.security import HTTPBearer
from typing import Optional


##################################
######### Setup FastAPI ##########
##################################

# TODO add tests for api endpoints


# Create new routers
mates_router = APIRouter()
skills_router = APIRouter()
software_router = APIRouter()
workflows_router = APIRouter()
tasks_router = APIRouter()
billing_router = APIRouter()
server_router = APIRouter()
teams_router = APIRouter()
users_router = APIRouter()


# Create a limiter instance
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    redoc_url="/docs", 
    docs_url="/swagger_docs"
)

bearer_scheme = HTTPBearer(
    scheme_name="Bearer Token", 
    description="""Enter your bearer token. Here's an example of how to use it in a request:

    ```python
    import requests

    url = "https://{server_url}/{endpoint}"
    headers = {"Authorization": "Bearer {your_token}"}

    # Make a get request (replace with post, patch, etc. as needed)
    response = requests.get(url, headers=headers)
    print(response.json())
    ```
    """
)

async def get_credentials(bearer: HTTPBearer = Depends(bearer_scheme)):
    return bearer.credentials

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="OpenMates API",
        version="1.0.0",
        description=(
            "Allows your code to interact with OpenMates server.<br>"
            "<h2>How to get started</h1>"
            "<ol>"
            "<li>Login to your OpenMates account, go to the settings and find your API token there.</li>"
            "<li>Make a request to the endpoint you want to use. Make sure to include your 'token' in the header.</li>"
            "</ol>"
        ),
        routes=app.routes,
        tags=tags_metadata
    )

    set_example(openapi_schema, "/{team_url}/mates/ask", "post", "requestBody", mates_ask_input_example)
    set_example(openapi_schema, "/{team_url}/mates/ask", "post", "responses", mates_ask_output_example, "200")
    set_example(openapi_schema, "/{team_url}/mates/", "get", "responses", mates_get_all_output_example, "200")
    set_example(openapi_schema, "/{team_url}/mates/", "post", "requestBody", mates_create_input_example)
    set_example(openapi_schema, "/{team_url}/mates/", "post", "responses", mates_create_output_example, "201")
    set_example(openapi_schema, "/{team_url}/mates/{mate_username}", "get", "responses", mates_get_one_output_example, "200")
    set_example(openapi_schema, "/{team_url}/mates/{mate_username}", "patch", "requestBody", mates_update_input_example)
    set_example(openapi_schema, "/{team_url}/mates/{mate_username}", "patch", "responses", mates_update_output_example, "200")
    set_example(openapi_schema, "/{team_url}/users/", "get", "responses", users_get_all_output_example, "200")
    set_example(openapi_schema, "/{team_url}/users/{username}", "get", "responses", users_get_one_output_example, "200")
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# Add the limiter as middleware
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def ratelimit_handler(request, exc):
    raise HTTPException(
        status_code=HTTP_429_TOO_MANY_REQUESTS, 
        detail="Too Many Requests"
    )

##################################
######### Files ##################
##################################

async def optional_bearer_token(request: Request):
    try:
        credentials = await bearer_scheme.__call__(request)
        return credentials.credentials
    except HTTPException:
        return None

# GET /images/{file_path} (get an image)
app.mount("/images", StaticFiles(directory=os.path.join(os.path.dirname(__file__), 'endpoints/images')), name="images")

# GET / (get the index.html file)
@app.get("/",include_in_schema=False)
@limiter.limit("20/minute")
def read_root(request: Request):
    return FileResponse(os.path.join(os.path.dirname(__file__), 'endpoints/index.html'))

# GET /{team_url}/uploads/{file_name} (get an uploaded file)
@app.get("/{team_url}/uploads/{file_name}", include_in_schema=False)
@limiter.limit("20/minute")
async def get_upload(
    request: Request, 
    team_url: str = Path(..., **input_parameter_descriptions["team_url"]),
    token: Optional[str] = Depends(optional_bearer_token)
    ):
    await validate_file_access(
        filename=request.path_params['file_name'],
        team_url=team_url,
        user_api_token=token,
        scope="uploads:read"
        )
    return await get_strapi_upload(request.path_params['file_name'])



##################################
######### Mates ##################
##################################

# POST /mates/ask (Send a message to an AI team mate and you receive the response)
@mates_router.post("/{team_url}/mates/ask",**endpoint_metadata["ask_mate"])
@limiter.limit("20/minute")
async def mates_ask(
    request: Request,
    parameters: MatesAskInput,
    team_url: str = Path(..., **input_parameter_descriptions["team_url"]),
    token: str = Depends(get_credentials)
    ):
    await validate_token(
        team_url=team_url,
        token=token
        )
    return await mates_ask_processing(
        team_url=team_url, 
        message=parameters.message, 
        mate_username=parameters.mate_username
        )


# GET /mates (get all mates)
@mates_router.get("/{team_url}/mates/", **endpoint_metadata["get_all_mates"])
@limiter.limit("20/minute")
async def get_mates(
    request: Request, 
    team_url: str = Path(..., **input_parameter_descriptions["team_url"]),
    token: str = Depends(get_credentials),
    page: int = 1,
    pageSize: int = 25
    ):
    await validate_token(
        team_url=team_url,
        token=token
        )
    return await get_mates_processing(
        team_url=team_url, 
        page=page, 
        pageSize=pageSize
        )


# GET /mates/{mate_username} (get a mate)
@mates_router.get("/{team_url}/mates/{mate_username}", **endpoint_metadata["get_mate"])
@limiter.limit("20/minute")
async def get_mate(
    request: Request,
    team_url: str = Path(..., **input_parameter_descriptions["team_url"]),
    token: str = Depends(get_credentials),
    mate_username: str = Path(..., **input_parameter_descriptions["mate_username"]),
    ):
    await validate_token(
        team_url=team_url,
        token=token
        )
    return await get_mate_processing(
        team_url=team_url, 
        mate_username=mate_username, 
        user_api_token=token
        )


# POST /mates (create a new mate)
@mates_router.post("/{team_url}/mates/", **endpoint_metadata["create_mate"])
@limiter.limit("20/minute")
async def create_mate(
    request: Request,
    parameters: MatesCreateInput,
    team_url: str = Path(..., **input_parameter_descriptions["team_url"]),
    token: str = Depends(get_credentials)
    ):
    await validate_token(
        team_url=team_url,
        token=token
        )
    return await create_mate_processing(
        name=parameters.name,
        username=parameters.username,
        description=parameters.description,
        profile_picture_url=parameters.profile_picture_url,
        default_systemprompt=parameters.default_systemprompt,
        default_skills=parameters.default_skills,
        team_url=team_url,
        user_api_token=token
        )


# PATCH /mates/{mate_username} (update a mate)
@mates_router.patch("/{team_url}/mates/{mate_username}", **endpoint_metadata["update_mate"])
@limiter.limit("20/minute")
async def update_mate(
    request: Request,
    parameters: MatesUpdateInput,
    team_url: str = Path(..., **input_parameter_descriptions["team_url"]),
    token: str = Depends(get_credentials),
    mate_username: str = Path(..., **input_parameter_descriptions["mate_username"])
    ):
    await validate_token(
        team_url=team_url,
        token=token
        )
    return await update_mate_processing(
        mate_username=mate_username,
        new_name=parameters.name,                                   # updates mate, only if user has right to edit original mate
        new_username=parameters.username,                           # updates mate, only if user has right to edit original mate
        new_description=parameters.description,                     # updates mate, only if user has right to edit original mate
        new_profile_picture_url=parameters.profile_picture_url,     # updates mate, only if user has right to edit original mate
        new_default_systemprompt=parameters.default_systemprompt,   # updates mate, only if user has right to edit original mate
        new_default_skills=parameters.default_skills,               # updates mate, only if user has right to edit original mate
        new_custom_systemprompt=parameters.systemprompt,            # updates mate config - specific to user + team
        new_custom_skills=parameters.skills,                        # updates mate config - specific to user + team
        team_url=team_url,
        user_api_token=token
        )




##################################
######### Skills #################
##################################

# Explaination:
# A skill is a single piece of functionality that a mate can use to help you. For example, ChatGPT, StableDiffusion, Notion or Figma.

# POST /skills/chatgpt/ask (ask a question to ChatGPT from OpenAI)
@skills_router.post("/{team_url}/skills/chatgpt/ask", summary="ChatGPT | Ask", description="<img src='images/skills/chatgpt/ask.png' alt='Ask ChatGPT from OpenAI a question, and it will answer it based on its knowledge.'>")
@limiter.limit("20/minute")
def skill_chatgpt_ask(request: Request, team_url: str,token: str = Depends(validate_token)):
    return {"info": "endpoint still needs to be implemented"}


# POST /skills/claude/message (ask a question to Claude from Anthropic)
@skills_router.post("/{team_url}/skills/claude/ask", summary="Claude | Ask", description="<img src='images/skills/claude/ask.png' alt='Ask Claude from Anthropic a question, and it will answer it based on its knowledge.'>")
@limiter.limit("20/minute")
def skill_claude_ask(request: Request, team_url: str, token: str = Depends(validate_token)):
    return {"info": "endpoint still needs to be implemented"}


# POST /skills/youtube/ask (ask a question about a video)
@skills_router.post("/{team_url}/skills/youtube/ask", summary="YouTube | Ask", description="<img src='images/skills/youtube/ask.png' alt='Ask a question about a video, and Claude will answer it based on the transcript and video details.'>")
@limiter.limit("20/minute")
def skill_youtube_ask(request: Request, team_url: str, token: str = Depends(validate_token)):
    return {"info": "endpoint still needs to be implemented"}


# # GET /skills/youtube/search (search YouTube for videos)
# @skills_router.get("/youtube/search", summary="YouTube | Search", description="<img src='images/skills/youtube/search.png' alt='Search & filter for videos on YouTube.'>")
# @limiter.limit("20/minute")
# def skill_youtube_search(request: Request, parameters: YouTubeSearch, token: str = Depends(validate_token)):
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
# def skill_youtube_transcript(request: Request, parameters: YouTubeTranscript, token: str = Depends(validate_token)):
#     return get_video_transcript(parameters.url)


##################################
######### Software ###############
##################################

# Explaination:
# A software can be interacted with using skills. For example, Notion, Figma, YouTube or Google Calendar.





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
def get_status(request: Request, token: str = Depends(validate_token)):
    return {"status": "online"}


# GET /server/settings (get server settings)
@server_router.get("/server/settings", summary="Get settings", description="<img src='images/server/get_settings.png' alt='Get all the current settings of your OpenMates server.'>")
@limiter.limit("20/minute")
def get_settings(request: Request, token: str = Depends(validate_token)):
    return {"info": "endpoint still needs to be implemented"}


# PATCH /server/settings (update server settings)
@server_router.patch("/server/settings", summary="Update settings", description="<img src='images/server/update_settings.png' alt='Update any of the setting on your OpenMates server.'>")
@limiter.limit("20/minute")
def update_settings(request: Request, token: str = Depends(validate_token)):
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

# GET /users (get all users on a team)
@users_router.get("/{team_url}/users/", summary="Get all", description="<img src='images/users/get_all.png' alt='Get an overview list of all users on your OpenMates server.'>")
@limiter.limit("20/minute")
async def get_users(
    request: Request,
    team_url: str = Path(..., **input_parameter_descriptions["team_url"]),
    token: str = Depends(get_credentials),
    page: int = 1,
    pageSize: int = 25
    ):
    await validate_token(
        team_url=team_url,
        token=token
        )
    return await get_users_processing(
        team_url=team_url,
        request_sender_api_token=token,
        page=page,
        pageSize=pageSize
        )


# GET /users/{username} (get a user)
@users_router.get("/{team_url}/users/{username}", **endpoint_metadata["get_user"])
@limiter.limit("20/minute")
async def get_user(
    request: Request, 
    team_url: str = Path(..., **input_parameter_descriptions["team_url"]),
    token: str = Depends(get_credentials),
    username: str = Path(..., **input_parameter_descriptions["user_username"])
    ):
    await validate_token(
        team_url=team_url,
        token=token
        )
    return await get_user_processing(
        team_url=team_url,
        request_sender_api_token=token,
        search_by_user_api_token=token if username == None else None,
        search_by_username=username
        )



# POST /users (create a new user)
@users_router.post("/{team_url}/users/", summary="Create", description="<img src='images/users/create.png' alt='Create a new user on your OpenMates server.'>")
@limiter.limit("20/minute")
async def create_user(request: Request, team_url: str, username: str, token: str = Depends(validate_token)):
    return {"info": "endpoint still needs to be implemented"}


# PATCH /users/{username} (update a user)
@users_router.patch("/{team_url}/users/{username}", summary="Update", description="<img src='images/users/update.png' alt='Update a user on your OpenMates server.'>")
@limiter.limit("20/minute")
async def update_user(request: Request, team_url: str, username: str, token: str = Depends(validate_token)):
    return {"info": "endpoint still needs to be implemented"}




# Include the routers in your FastAPI application
app.include_router(mates_router,        tags=["Mates"])
app.include_router(skills_router,       tags=["Skills"])
app.include_router(software_router,     tags=["software"])
app.include_router(workflows_router,    tags=["Workflows"])
app.include_router(tasks_router,        tags=["Tasks"])
app.include_router(billing_router,      tags=["Billing"])
app.include_router(server_router,       tags=["Server"])
app.include_router(teams_router,        tags=["Teams"])
app.include_router(users_router,        tags=["Users"])

if __name__ == "__main__":
    uvicorn.run("server.api.api:app", host="0.0.0.0", port=8000, log_level="info")