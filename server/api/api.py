
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
from fastapi import FastAPI, Depends, UploadFile, File, Form, Request, HTTPException, APIRouter, Path
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
from server.api.models.mates.mates_delete import (
    mates_delete_output_example
)
from server.api.models.users.users_get_one import (
    users_get_one_output_example
)
from server.api.models.users.users_get_all import (
    users_get_all_output_example
)
from server.api.models.teams.teams_get_all import (
    teams_get_all_output_example
)
from server.api.models.teams.teams_get_one import (
    teams_get_one_output_example
)
from server.api.models.users.users_create import (
    UsersCreateInput,
    users_create_input_example,
    users_create_output_example
)
from server.api.models.users.users_create_new_api_token import (
    UsersCreateNewApiTokenInput,
    users_create_new_api_token_input_example,
    users_create_new_api_token_output_example
)
from server.api.models.users.users_replace_profile_picture import (
    users_replace_profile_picture_output_example
)
from server.api.models.skills.skills_get_one import (
    skills_get_one_output_example
)
from server.api.models.skills.ai.skills_ai_ask import (
    AiAskInput,
    AiAskOutput,
    AiAskOutputStream,
    ai_ask_input_example,
    ai_ask_input_example_2,
    ai_ask_input_example_3,
    ai_ask_input_example_4,
    ai_ask_input_example_5,
    ai_ask_output_example,
    ai_ask_output_example_2,
    ai_ask_output_example_3,
    ai_ask_output_example_4,
    ai_ask_output_example_5
)
from server.api.models.skills.ai.skills_ai_estimate_cost import (
    AiEstimateCostInput,
    AiEstimateCostOutput,
    ai_estimate_cost_input_example,
    ai_estimate_cost_output_example
)
from server.api.models.skills.code.skills_code_plan import (
    CodePlanInput,
    CodePlanOutput,
    code_plan_input_example,
    code_plan_input_example_2,
    code_plan_output_example,
    code_plan_output_example_2
)
from server.api.models.skills.code.skills_code_write import (
    CodeWriteInput,
    CodeWriteOutput,
    code_write_input_example,
    code_write_output_example
)
from server.api.models.skills.finance.skills_finance_get_report import (
    FinanceGetReportInput,
    FinanceGetReportOutput,
    finance_get_report_input_example,
    finance_get_report_output_example
)
from server.api.models.skills.finance.skills_finance_get_transactions import (
    FinanceGetTransactionsInput,
    FinanceGetTransactionsOutput,
    finance_get_transactions_input_example,
    finance_get_transactions_output_example
)
from server.api.models.skills.videos.skills_videos_get_transcript import (
    VideosGetTranscriptInput,
    VideosGetTranscriptOutput,
    videos_get_transcript_input_example,
    videos_get_transcript_output_example
)
from server.api.models.skills.image_editor.skills_image_editor_resize_image import (
    image_editor_resize_output_example
)


from server.api.endpoints.mates.ask_mate import ask_mate as ask_mate_processing
from server.api.endpoints.mates.get_mates import get_mates as get_mates_processing
from server.api.endpoints.mates.get_mate import get_mate as get_mate_processing
from server.api.endpoints.mates.create_mate import create_mate as create_mate_processing
from server.api.endpoints.mates.update_mate import update_mate as update_mate_processing
from server.api.endpoints.mates.delete_mate import delete_mate as delete_mate_processing
from server.api.endpoints.users.get_user import get_user as get_user_processing
from server.api.endpoints.users.get_users import get_users as get_users_processing
from server.api.endpoints.users.create_user import create_user as create_user_processing
from server.api.endpoints.users.replace_profile_picture import replace_profile_picture as replace_profile_picture_processing
from server.api.endpoints.users.create_new_api_token import create_new_api_token as create_new_api_token_processing
from server.api.endpoints.teams.get_teams import get_teams as get_teams_processing
from server.api.endpoints.teams.get_team import get_team as get_team_processing
from server.api.endpoints.skills.get_skill import get_skill as get_skill_processing
from server.api.endpoints.skills.code.plan import plan as skill_code_plan_processing
from server.api.endpoints.skills.code.write import write as skill_code_write_processing
from server.api.endpoints.skills.ai.ask import ask as skill_ai_ask_processing
from server.api.endpoints.skills.ai.estimate_cost import estimate_cost as skill_ai_estimate_cost_processing
from server.api.endpoints.skills.finance.get_report import get_report as skill_finance_get_report_processing
from server.api.endpoints.skills.finance.get_transactions import get_transactions as skill_finance_get_transactions_processing
from server.api.endpoints.skills.videos.get_transcript import get_transcript as skill_videos_get_transcript_processing
from server.api.endpoints.skills.image_editor.resize_image import resize_image as skill_image_editor_resize_image_processing


from server.api.validation.validate_permissions import validate_permissions
from server.api.validation.validate_invite_code import validate_invite_code
from server.cms.strapi_requests import get_strapi_upload

from starlette.responses import FileResponse
from starlette.status import HTTP_429_TOO_MANY_REQUESTS
from fastapi.openapi.utils import get_openapi
from server.api.parameters import (
    files_endpoints,
    mates_endpoints,
    skills_endpoints,
    skills_code_endpoints,
    skills_ai_endpoints,
    skills_finance_endpoints,
    skills_videos_endpoints,
    skills_image_editor_endpoints,
    users_endpoints,
    teams_endpoints,
    server_endpoints,
    set_example,
    tags_metadata,
    input_parameter_descriptions
)
from fastapi.security import HTTPBearer
from typing import Optional, List, Literal, Union
from fastapi.responses import StreamingResponse, JSONResponse
from io import BytesIO


##################################
######### Setup FastAPI ##########
##################################

# TODO dynamically load skill API endpoints, depending on which are in strapi database


# Create new routers
files_router = APIRouter()
mates_router = APIRouter()
skills_router = APIRouter()
skills_ai_router = APIRouter()
skills_code_router = APIRouter()
skills_finance_router = APIRouter()
skills_videos_router = APIRouter()
skills_image_editor_router = APIRouter()
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

    set_example(openapi_schema, "/v1/{team_slug}/mates/ask", "post", "requestBody", {
        "Example 1": mates_ask_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/mates/ask", "post", "responses", {
        "Example 1": mates_ask_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/mates/", "get", "responses", {
        "Example 1": mates_get_all_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/mates/", "post", "requestBody", {
        "Example 1": mates_create_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/mates/", "post", "responses", {
        "Example 1": mates_create_output_example
    }, "201")
    set_example(openapi_schema, "/v1/{team_slug}/mates/{mate_username}", "get", "responses", {
        "Example 1": mates_get_one_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/mates/{mate_username}", "patch", "requestBody", {
        "Example 1": mates_update_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/mates/{mate_username}", "patch", "responses", {
        "Example 1": mates_update_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/mates/{mate_username}", "delete", "responses", {
        "Example 1": mates_delete_output_example
    }, "200")
    set_example(openapi_schema, "/v1/teams", "get", "responses", {
        "Example 1": teams_get_all_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}", "get", "responses", {
        "Example 1": teams_get_one_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/users/", "get", "responses", {
        "Example 1": users_get_all_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/users/{username}", "get", "responses", {
        "Example 1": users_get_one_output_example
    }, "200")
    set_example(openapi_schema, "/v1/api_token", "patch", "requestBody", {
        "Example 1": users_create_new_api_token_input_example
    })
    set_example(openapi_schema, "/v1/api_token", "patch", "responses", {
        "Example 1": users_create_new_api_token_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/users/{username}/profile_picture", "patch", "responses", {
        "Example 1": users_replace_profile_picture_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/users/", "post", "requestBody", {
        "Example 1": users_create_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/users/", "post", "responses", {
        "Example 1": users_create_output_example
    }, "201")
    set_example(openapi_schema, "/v1/{team_slug}/skills/{software_slug}/{skill_slug}", "get", "responses", {
        "Example 1": skills_get_one_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/ai/ask", "post", "requestBody", {
        "Ask question": ai_ask_input_example,
        "Select a tool": ai_ask_input_example_2,
        "Process tool response": ai_ask_input_example_3,
        "Process image": ai_ask_input_example_4,
        "Ask question (stream)": ai_ask_input_example_5
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/ai/ask", "post", "responses", {
        "Ask question": ai_ask_output_example,
        "Select a tool": ai_ask_output_example_2,
        "Process tool response": ai_ask_output_example_3,
        "Process image": ai_ask_output_example_4,
    }, "200", "application/json")
    set_example(openapi_schema, "/v1/{team_slug}/skills/ai/ask", "post", "responses", {
        "Stream response": ai_ask_output_example_5
    }, "200", "text/event-stream")
    set_example(openapi_schema, "/v1/{team_slug}/skills/ai/estimate_cost", "post", "requestBody", {
        "Example 1": ai_estimate_cost_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/ai/estimate_cost", "post", "responses", {
        "Example 1": ai_estimate_cost_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/code/plan", "post", "requestBody", {
        "Q&A Round 1": code_plan_input_example,
        "Q&A Round 2": code_plan_input_example_2
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/code/plan", "post", "responses", {
        "Q&A Round 1": code_plan_output_example,
        "Q&A Round 2": code_plan_output_example_2
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/code/write", "post", "requestBody", {
        "Example 1": code_write_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/code/write", "post", "responses", {
        "Example 1": code_write_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/finance/get_report", "post", "requestBody", {
        "Example 1": finance_get_report_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/finance/get_report", "post", "responses", {
        "Example 1": finance_get_report_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/finance/get_transactions", "post", "requestBody", {
        "Example 1": finance_get_transactions_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/finance/get_transactions", "post", "responses", {
        "Example 1": finance_get_transactions_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/videos/transcript", "post", "requestBody", {
        "Example 1": videos_get_transcript_input_example
    })
    set_example(openapi_schema, "/v1/{team_slug}/skills/videos/transcript", "post", "responses", {
        "Example 1": videos_get_transcript_output_example
    }, "200")
    set_example(openapi_schema, "/v1/{team_slug}/skills/image_editor/resize", "post", "responses", {
        "Example 1": image_editor_resize_output_example
    }, "200")


    # Ensure AiAskOutput schema is correctly referenced
    openapi_schema["paths"]["/v1/{team_slug}/skills/ai/ask"]["post"]["responses"]["200"]["content"]["application/json"]["schema"] = {
        "$ref": "#/components/schemas/AiAskOutput"
    }

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


# GET /v1/{team_slug}/uploads/{file_name} (get an uploaded file)
@files_router.get("/v1/{team_slug}/uploads/{file_name}", include_in_schema=False)
@limiter.limit("20/minute")
async def get_upload(
    request: Request,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: Optional[str] = Depends(optional_bearer_token)
    ):
    await validate_permissions(
        endpoint=f"/uploads/{request.path_params['file_name']}",
        user_api_token=token,
        team_slug=team_slug
    )
    return await get_strapi_upload(request.path_params['file_name'])



##################################
######### Mates ##################
##################################

# POST /mates/ask (Send a message to an AI team mate and you receive the response)
@mates_router.post("/v1/{team_slug}/mates/ask",**mates_endpoints["ask_mate"])
@limiter.limit("20/minute")
async def ask_mate(
    request: Request,
    parameters: MatesAskInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
    ):
    await validate_permissions(
        endpoint="/mates/ask",
        team_slug=team_slug,
        user_api_token=token
    )
    return await ask_mate_processing(
        team_slug=team_slug,
        message=parameters.message,
        mate_username=parameters.mate_username
        )


# GET /mates (get all mates)
@mates_router.get("/v1/{team_slug}/mates/", **mates_endpoints["get_all_mates"])
@limiter.limit("20/minute")
async def get_mates(
    request: Request,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials),
    page: int = 1,
    pageSize: int = 25
    ):
    await validate_permissions(
        endpoint="/mates",
        team_slug=team_slug,
        user_api_token=token
    )
    return await get_mates_processing(
        team_slug=team_slug,
        page=page,
        pageSize=pageSize
        )


# GET /mates/{mate_username} (get a mate)
@mates_router.get("/v1/{team_slug}/mates/{mate_username}", **mates_endpoints["get_mate"])
@limiter.limit("20/minute")
async def get_mate(
    request: Request,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials),
    mate_username: str = Path(..., **input_parameter_descriptions["mate_username"]),
    ):
    await validate_permissions(
        endpoint=f"/mates/{mate_username}",
        team_slug=team_slug,
        user_api_token=token
    )
    return await get_mate_processing(
        team_slug=team_slug,
        mate_username=mate_username,
        user_api_token=token,
        include_populated_data=True,
        output_raw_data=False,
        output_format="JSONResponse"
        )


# POST /mates (create a new mate)
@mates_router.post("/v1/{team_slug}/mates/", **mates_endpoints["create_mate"])
@limiter.limit("20/minute")
async def create_mate(
    request: Request,
    parameters: MatesCreateInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
    ):
    await validate_permissions(
        endpoint="/mates",
        team_slug=team_slug,
        user_api_token=token,
        required_permissions=["mates:create"]
    )
    return await create_mate_processing(
        name=parameters.name,
        username=parameters.username,
        description=parameters.description,
        profile_picture_url=parameters.profile_picture_url,
        default_systemprompt=parameters.default_systemprompt,
        default_skills=parameters.default_skills,
        default_llm_endpoint=parameters.default_llm_endpoint,
        default_llm_model=parameters.default_llm_model,
        team_slug=team_slug,
        user_api_token=token
        )


# PATCH /mates/{mate_username} (update a mate)
@mates_router.patch("/v1/{team_slug}/mates/{mate_username}", **mates_endpoints["update_mate"])
@limiter.limit("20/minute")
async def update_mate(
    request: Request,
    parameters: MatesUpdateInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials),
    mate_username: str = Path(..., **input_parameter_descriptions["mate_username"])
    ):
    await validate_permissions(
        endpoint=f"/mates/{mate_username}",
        team_slug=team_slug,
        user_api_token=token,
        required_permissions=["mates:update"]
    )
    return await update_mate_processing(
        mate_username=mate_username,
        new_name=parameters.name,                                   # updates mate, only if user has right to edit original mate
        new_username=parameters.username,                           # updates mate, only if user has right to edit original mate
        new_description=parameters.description,                     # updates mate, only if user has right to edit original mate
        new_profile_picture_url=parameters.profile_picture_url,     # updates mate, only if user has right to edit original mate
        new_default_systemprompt=parameters.default_systemprompt,   # updates mate, only if user has right to edit original mate
        new_default_skills=parameters.default_skills,               # updates mate, only if user has right to edit original mate
        new_default_llm_endpoint=parameters.default_llm_endpoint,   # updates mate, only if user has right to edit original mate
        new_default_llm_model=parameters.default_llm_model,         # updates mate, only if user has right to edit original mate
        new_custom_systemprompt=parameters.systemprompt,            # updates mate config - specific to user + team
        new_custom_skills=parameters.skills,                        # updates mate config - specific to user + team
        allowed_to_access_user_name=parameters.allowed_to_access_user_name,          # updates mate config - specific to user + team
        allowed_to_access_user_username=parameters.allowed_to_access_user_username,  # updates mate config - specific to user + team
        allowed_to_access_user_projects=parameters.allowed_to_access_user_projects,  # updates mate config - specific to user + team
        allowed_to_access_user_goals=parameters.allowed_to_access_user_goals,        # updates mate config - specific to user + team
        allowed_to_access_user_todos=parameters.allowed_to_access_user_todos,        # updates mate config - specific to user + team
        allowed_to_access_user_recent_topics=parameters.allowed_to_access_user_recent_topics, # updates mate config - specific to user + team
        team_slug=team_slug,
        user_api_token=token,
        )


# DELETE /mates/{mate_username} (delete a mate)
@mates_router.delete("/v1/{team_slug}/mates/{mate_username}", **mates_endpoints["delete_mate"])
@limiter.limit("20/minute")
async def delete_mate(
    request: Request,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials),
    mate_username: str = Path(..., **input_parameter_descriptions["mate_username"])
    ):
    await validate_permissions(
        endpoint=f"/mates/{mate_username}",
        team_slug=team_slug,
        user_api_token=token,
        required_permissions=["mates:delete"]
    )
    return await delete_mate_processing(
        team_slug=team_slug,
        mate_username=mate_username,
        user_api_token=token
        )



##################################
######### Skills #################
##################################

# Explaination:
# A skill is a single piece of functionality that a mate can use to help you. For example, ChatGPT, StableDiffusion, Notion or Figma.


# GET /skills/{software_slug}/{skill_slug} (get a skill)
@skills_router.get("/v1/{team_slug}/skills/{software_slug}/{skill_slug}", **skills_endpoints["get_skill"])
@limiter.limit("20/minute")
async def get_skill(
    request: Request,
    software_slug: str = Path(..., **input_parameter_descriptions["software_slug"]),
    skill_slug: str = Path(..., **input_parameter_descriptions["skill_slug"]),
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
    ):
    await validate_permissions(
        endpoint=f"/skills/{software_slug}/{skill_slug}",
        team_slug=team_slug,
        user_api_token=token
    )
    return await get_skill_processing(
        team_slug=team_slug,
        software_slug=software_slug,
        skill_slug=skill_slug,
        include_populated_data=True,
        output_raw_data=False,
        output_format="JSONResponse"
    )


@skills_ai_router.post("/v1/{team_slug}/skills/ai/ask", **skills_ai_endpoints["ask"])
@limiter.limit("20/minute")
async def skill_ai_ask(
    request: Request,
    parameters: AiAskInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> Union[AiAskOutput, StreamingResponse]:
    await validate_permissions(
        endpoint="/skills/ai/ask",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_ai_ask_processing(
        user_api_token=token,
        team_slug=team_slug,
        system=parameters.system,
        message=parameters.message,
        message_history=parameters.message_history,
        provider=parameters.provider,
        temperature=parameters.temperature,
        stream=parameters.stream,
        cache=parameters.cache,
        max_tokens=parameters.max_tokens,
        stop_sequence=parameters.stop_sequence,
        tools=parameters.tools
    )


@skills_ai_router.post("/v1/{team_slug}/skills/ai/estimate_cost", **skills_ai_endpoints["estimate_cost"])
@limiter.limit("20/minute")
async def skill_ai_estimate_cost(
    request: Request,
    parameters: AiEstimateCostInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> AiEstimateCostOutput:
    await validate_permissions(
        endpoint="/skills/ai/estimate_cost",
        team_slug=team_slug,
        user_api_token=token
    )
    return skill_ai_estimate_cost_processing(
        token_count=parameters.token_count,
        system=parameters.system,
        message=parameters.message,
        message_history=parameters.message_history,
        provider=parameters.provider,
        temperature=parameters.temperature,
        stream=parameters.stream,
        cache=parameters.cache,
        max_tokens=parameters.max_tokens,
        stop_sequence=parameters.stop_sequence,
        tools=parameters.tools
    )


# POST /skills/code/plan (plan code requirements and logic)
@skills_code_router.post("/v1/{team_slug}/skills/code/plan", **skills_code_endpoints["plan"])
@limiter.limit("10/minute")
async def skill_code_plan(
    request: Request,
    parameters: CodePlanInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> CodePlanOutput:
    await validate_permissions(
        endpoint="/skills/code/plan",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_code_plan_processing(
        token=token,
        team_slug=team_slug,
        q_and_a_basics=parameters.q_and_a_basics,
        q_and_a_followup=parameters.q_and_a_followup,
        code_git_url=parameters.code_git_url,
        code_zip=parameters.code_zip,
        code_file=parameters.code_file,
        other_context_files=parameters.other_context_files
    )


# POST /skills/code/write (generate or update code based on requirements)
@skills_code_router.post("/v1/{team_slug}/skills/code/write", **skills_code_endpoints["write"])
@limiter.limit("5/minute")
async def skill_code_write(
    request: Request,
    parameters: CodeWriteInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> CodeWriteOutput:
    await validate_permissions(
        endpoint="/skills/code/write",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_code_write_processing(
        token=token,
        team_slug=team_slug,
        requirements=parameters.requirements,
        coding_guidelines=parameters.coding_guidelines,
        files_for_context=parameters.files_for_context,
        file_tree_for_context=parameters.file_tree_for_context
    )


@skills_finance_router.post("/v1/{team_slug}/skills/finance/get_report", **skills_finance_endpoints["get_report"])
@limiter.limit("20/minute")
async def skill_finance_get_report(
    request: Request,
    parameters: FinanceGetReportInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> FinanceGetReportOutput:
    await validate_permissions(
        endpoint="/skills/finance/get_report",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_finance_get_report_processing(
        report=parameters.report,
        date_from=parameters.date_from,
        date_to=parameters.date_to,
        format=parameters.format,
        include_attachments=parameters.include_attachments
    )


@skills_finance_router.post("/v1/{team_slug}/skills/finance/get_transactions", **skills_finance_endpoints["get_transactions"])
@limiter.limit("20/minute")
async def skill_finance_get_transactions(
    request: Request,
    parameters: FinanceGetTransactionsInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> FinanceGetTransactionsOutput:
    await validate_permissions(
        endpoint="/skills/finance/get_transactions",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_finance_get_transactions_processing(
        token=token,
        from_date=parameters.from_date,
        to_date=parameters.to_date,
        bank=parameters.bank,
        account=parameters.account,
        count=parameters.count,
        type=parameters.type
    )


@skills_videos_router.post("/v1/{team_slug}/skills/videos/transcript", **skills_videos_endpoints["get_transcript"])
@limiter.limit("20/minute")
async def skill_videos_get_transcript(
    request: Request,
    parameters: VideosGetTranscriptInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> VideosGetTranscriptOutput:
    await validate_permissions(
        endpoint="/skills/videos/transcript",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_videos_get_transcript_processing(
        url=parameters.url,
        block_token_limit=parameters.block_token_limit
    )


# TODO add test
# POST /skills/image_editor/resize (resize an image)
@skills_image_editor_router.post("/v1/{team_slug}/skills/image_editor/resize", **skills_image_editor_endpoints["resize_image"])
@limiter.limit("20/minute")
async def skill_image_editor_resize(
    request: Request,
    file: UploadFile = File(..., **input_parameter_descriptions["file"]),
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials),
    target_resolution_width: int = Form(None, description="The target resolution width"),
    target_resolution_height: int = Form(None, description="The target resolution height"),
    max_length: int = Form(None, description="The maximum length of the image"),
    method: Literal["scale", "crop"] = Form("scale", description="The method to use for resizing."),
    use_ai_upscaling_if_needed: bool = Form(False, description="If set to True, AI upscaling will be used if needed"),
    output_square: bool = Form(False, description="If set to True, the output image will be square")
    ) -> StreamingResponse:
    await validate_permissions(
        endpoint="/skills/image_editor/resize",
        team_slug=team_slug,
        user_api_token=token
    )

    image_data = await file.read()
    return await skill_image_editor_resize_image_processing(
        image_data=image_data,
        target_resolution_width=target_resolution_width,
        target_resolution_height=target_resolution_height,
        max_length=max_length,
        method=method,
        use_ai_upscaling_if_needed=use_ai_upscaling_if_needed,
        output_square=output_square
    )



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

# TODO add test
# GET /server/status (get server status)
@server_router.get("/server/status", **server_endpoints["get_status"])
@limiter.limit("20/minute")
async def get_status(
    request: Request,
    token: str = Depends(get_credentials)
    ):
    return {"status": "online"}


# TODO add test
# GET /server/settings (get server settings)
@server_router.get("/server/settings", **server_endpoints["get_settings"])
@limiter.limit("20/minute")
async def get_settings(
    request: Request,
    token: str = Depends(get_credentials)
    ):
    return {"info": "endpoint still needs to be implemented"}


# TODO add test
# PATCH /server/settings (update server settings)
@server_router.patch("/server/settings", **server_endpoints["update_settings"])
@limiter.limit("20/minute")
async def update_settings(
    request: Request,
    token: str = Depends(get_credentials)
    ):
    return {"info": "endpoint still needs to be implemented"}



##################################
######### Teams ##################
##################################

# Explaination:
# A server can have multiple teams. Each team can have multiple users and multiple mates. Teams can be used to separate different work environments, departments or companies.

# TODO implement
# TODO add test
# GET /teams (get all teams)
@teams_router.get("/v1/teams", **teams_endpoints["get_all_teams"])
@limiter.limit("20/minute")
async def get_teams(
    request: Request,
    token: str = Depends(get_credentials),
    page: int = 1,
    pageSize: int = 25
    ):
    await validate_permissions(
        endpoint="/teams",# TODO need to make function compatible with this endpoint
        user_api_token=token,
        required_permissions=["teams:get_all"]
    )
    return await get_teams_processing(
        page=page,
        pageSize=pageSize
    )


# TODO implement
# TODO add test
# GET /teams/{team_slug} (get a team)
@teams_router.get("/v1/{team_slug}", **teams_endpoints["get_team"])
@limiter.limit("20/minute")
async def get_team(
    request: Request,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
    ):
    await validate_permissions(
        endpoint="/team/{team_slug}", # TODO need to make function compatible with this endpoint
        team_slug=team_slug,
        user_api_token=token
    )
    return await get_team_processing(
        team_slug=team_slug,
        user_api_token=token
    )



##################################
########## Users #################
##################################

# Explaination:
# User accounts are used to store user data like what projects the user is working on, what they are interested in, what their goals are, etc.
# The OpenMates admin can choose if users who message mates via the chat software (mattermost, slack, etc.) are required to have an account. If not, the user will be treated as a guest without personalized responses.

# GET /users (get all users on a team)
@users_router.get("/v1/{team_slug}/users/", **users_endpoints["get_all_users"])
@limiter.limit("20/minute")
async def get_users(
    request: Request,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials),
    page: int = 1,
    pageSize: int = 25
    ):
    await validate_permissions(
        endpoint="/users",
        team_slug=team_slug,
        user_api_token=token
    )
    return await get_users_processing(
        team_slug=team_slug,
        request_sender_api_token=token,
        page=page,
        pageSize=pageSize
        )


# TODO add test
# POST /users (create a new user)
@users_router.post("/v1/{team_slug}/users/", **users_endpoints["create_user"])
@limiter.limit("20/minute")
async def create_user(
    request: Request,
    parameters: UsersCreateInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"])
    ):
    await validate_invite_code(
        team_slug=team_slug,
        invite_code=parameters.invite_code
        )
    return await create_user_processing(
        name=parameters.name,
        username=parameters.username,
        email=parameters.email,
        password=parameters.password,
        team_slug=team_slug
        )


# TODO add test
# GET /users/{username} (get a user)
@users_router.get("/v1/{team_slug}/users/{username}", **users_endpoints["get_user"])
@limiter.limit("20/minute")
async def get_user(
    request: Request,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials),
    username: str = Path(..., **input_parameter_descriptions["user_username"])
    ):
    await validate_permissions(
        endpoint=f"/users/{username}",
        team_slug=team_slug,
        user_api_token=token
    )
    return await get_user_processing(
        team_slug=team_slug,
        request_sender_api_token=token,
        api_token=token,
        username=username,
        decrypt_data=True
        )


# TODO add test
# PATCH /users/{username} (update a user)
@users_router.patch("/v1/{team_slug}/users/{username}", **users_endpoints["update_user"])
@limiter.limit("20/minute")
async def update_user(
    request: Request,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials),
    username: str = Path(..., **input_parameter_descriptions["user_username"])
    ):
    await validate_permissions(
        endpoint=f"/users/{username}",
        team_slug=team_slug,
        user_api_token=token,
        required_permissions=["users:update"]
    )
    return {"info": "endpoint still needs to be implemented"}


# TODO add test
# PATCH /users/{username}/profile_picture (replace a user's profile picture)
@users_router.patch("/v1/{team_slug}/users/{username}/profile_picture", **users_endpoints["replace_profile_picture"])
@limiter.limit("5/minute")
async def replace_user_profile_picture(
    request: Request,
    file: UploadFile = File(..., **input_parameter_descriptions["file"]),
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials),
    username: str = Path(..., **input_parameter_descriptions["user_username"]),
    visibility: Literal["public", "team", "server"] = Form("server", description="Who can see the profile picture? Public means everyone on the internet can see it, team means only team members can see it, server means every user on the server can see it.")
    ):
    access = await validate_permissions(
        endpoint=f"/users/{username}/profile_picture",
        user_api_token=token,
        team_slug=team_slug,
        required_permissions=["users:replace_profile_picture"]
    )

    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="No file provided")

    if len(contents) > 3 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File size exceeds 3MB limit")

    return await replace_profile_picture_processing(
        team_slug=team_slug,
        api_token=token,
        username=username,
        user_access=access,
        file=contents,
        visibility=visibility
    )


# TODO add test
# PATCH /api_token (generate a new API token for a user)
@users_router.patch("/v1/api_token", **users_endpoints["create_new_api_token"])
@limiter.limit("5/minute")
async def generate_new_user_api_token(
    request: Request,
    parameters: UsersCreateNewApiTokenInput
    ):
    await validate_permissions(
        endpoint="/api_token",
        user_username=parameters.username,
        user_password=parameters.password,
        required_permissions=["api_token:create"]
    )
    return await create_new_api_token_processing(
        username=parameters.username,
        password=parameters.password
    )



# Include the routers in your FastAPI application
app.include_router(files_router,                    tags=["Files"])
app.include_router(mates_router,                    tags=["Mates"])
app.include_router(skills_router,                   tags=["Skills"])
app.include_router(skills_ai_router,                tags=["Skills | AI"])
app.include_router(skills_code_router,              tags=["Skills | Code"])
app.include_router(skills_finance_router,           tags=["Skills | Finance"])
app.include_router(skills_videos_router,            tags=["Skills | Videos"])
app.include_router(skills_image_editor_router,      tags=["Skills | Image Editor"])
app.include_router(software_router,                 tags=["software"])
app.include_router(workflows_router,                tags=["Workflows"])
app.include_router(tasks_router,                    tags=["Tasks"])
app.include_router(billing_router,                  tags=["Billing"])
app.include_router(server_router,                   tags=["Server"])
app.include_router(teams_router,                    tags=["Teams"])
app.include_router(users_router,                    tags=["Users"])

if __name__ == "__main__":
    uvicorn.run("server.api.api:app", host="0.0.0.0", port=8000, log_level="info")