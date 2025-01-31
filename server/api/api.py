from server.api import *
from server.api.docs.docs import setup_docs, bearer_scheme
from server.server_config import get_server_config
from datetime import datetime, timedelta, timezone
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from typing import Optional, Set
import os
from pydantic import BaseModel
from fastapi import Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
from server.api.security.crypto import hashing, verify_hash

logger = logging.getLogger(__name__)

##################################
######### Setup FastAPI ##########
##################################

def register_app_router(
    app: FastAPI,
    router: APIRouter,
    app_name: str,
    config_path: str,
    tags: List[str]
) -> None:
    """
    Register an app router if it's enabled in the server config.

    Args:
        app: FastAPI application instance
        router: Router to include
        app_name: Name of the app for logging
        config_path: Path to the config setting (e.g., 'apps.ai.allowed')
        tags: List of tags for the router
    """
    logger.debug(f"Checking if app '{app_name}' is enabled...")

    if get_server_config(config_path):
        app.include_router(router, tags=tags)
        logger.info(f"Routes for app '{app_name}' included")
    else:
        logger.info(f"Routes for app '{app_name}' excluded (disabled in config)")

def require_feature(config_path: str | None = None):
    """
    Decorator to check if a feature is enabled before executing the endpoint.
    If config_path is None, the endpoint will be included without checking.

    Args:
        config_path: Path to the config setting, or None to skip checking
    """
    def decorator(func):
        # Store the config path on the function for later reference
        func._config_path = config_path

        if config_path and not get_server_config(config_path):
            logger.debug(f"Endpoint disabled: {config_path} is not enabled")
            return None
        return func
    return decorator

# TODO dynamically load skill API endpoints, depending on which are in strapi database


# Create new routers
router = APIRouter()

##########################################################
# Mates
##########################################################
mates_router = APIRouter()

##########################################################
# Teams
##########################################################
teams_router = APIRouter()

##########################################################
# Users
##########################################################
users_router = APIRouter()

##########################################################
# Skills
##########################################################
skills_router = APIRouter()

##########################################################
# Tasks
##########################################################
tasks_router = APIRouter()

##########################################################
# Billing
##########################################################
billing_router = APIRouter()

##########################################################
# Server
##########################################################
server_router = APIRouter()

##########################################################
# Workflows
##########################################################
workflows_router = APIRouter()

##########################################################
# Apps
##########################################################
apps_router = APIRouter()
# AI
apps_ai_router = APIRouter()
# Audio
apps_audio_router = APIRouter()
# Books
apps_books_router = APIRouter()
# Docs
apps_docs_router = APIRouter()
# Files
apps_files_router = APIRouter()
# Finance
apps_finance_router = APIRouter()
# Health
apps_health_router = APIRouter()
# Home
apps_home_router = APIRouter()
# Maps
apps_maps_router = APIRouter()
# Messages
apps_messages_router = APIRouter()
# PDF Editor
apps_pdf_editor_router = APIRouter()
# Photos
apps_photos_router = APIRouter()
# Travel
apps_travel_router = APIRouter()
# Videos
apps_videos_router = APIRouter()
# Web
apps_web_router = APIRouter()


async def get_credentials(bearer: HTTPBearer = Depends(bearer_scheme)):
    return bearer.credentials

async def lifespan(app: FastAPI):
    await api_startup()
    yield
    await api_shutdown()


# Create the FastAPI app
app = FastAPI(
    redoc_url="/redoc_docs",
    docs_url=None,
    lifespan=lifespan
)

# Add logging for CORS configuration
logger.debug("Setting up CORS middleware with following configuration:")
allowed_origins = [
    os.getenv("FRONTEND_URL", "http://localhost:5174"),
    os.getenv("PRODUCTION_URL", "https://app.openmates.org")
]
logger.debug(f"Allowed origins: {allowed_origins}")

# Add CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept", "Origin"],  # Added 'Origin'
    expose_headers=["*"],
)


# Add rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# Setup custom documentation
setup_docs(app)

# Mount the static files directory
base_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(base_dir.split('server')[0], 'server', 'web_app', 'static')
app.mount("/static", StaticFiles(directory=static_dir), name="static")

##################################
######### Web interface ##########
##################################

# GET / (get the index.html file)
@app.get("/",include_in_schema=False)
@limiter.limit("20/minute")
def read_root(request: Request):
    return FileResponse(os.path.join(os.path.dirname(__file__), 'endpoints/index.html'))


##########################################################
# Mates
##########################################################

# POST /mates/ask (Send a message to an AI team mate and you receive the response)
@mates_router.post("/v1/{team_slug}/mates/ask", **mates_endpoints["ask_mate"])
@limiter.limit("20/minute")
async def ask_mate(
    request: Request,
    parameters: MatesAskInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> Task:
    await validate_permissions(
        endpoint="/mates/ask",
        team_slug=team_slug,
        user_api_token=token
    )

    task_info = {
        "title": f"/{team_slug}/mates/ask",
        "endpoint": "/mates/ask",
        "team_slug": team_slug,
        "mate_username": parameters.mate_username
    }

    # Create the task with additional info
    task = ask_mate_task.apply_async(
        args=[
            team_slug,
            parameters.message,
            parameters.mate_username
        ],
        kwargs={
            'task_info': task_info
        }
    )

    return Task(
        task_url=f"/v1/{team_slug}/tasks/{task.id}",
        task_id=task.id
    )


# GET /mates/call (get the call.html file)
@app.get("/mates/call", include_in_schema=False)
@limiter.limit("20/minute")
def read_mates_call(request: Request):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    new_base_dir = os.path.join(base_dir.split('api')[0], 'web_app', 'static')
    return FileResponse(os.path.join(new_base_dir, 'call.html'))


# WEBSOCKET /mates/call (call a mate)
@router.websocket("/v1/{team_slug}/mates/call")
async def call_mate(
    websocket: WebSocket,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"])
    ):
    await call_mate_processing(
        team_slug=team_slug,
        websocket=websocket
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
        profile_image=parameters.profile_image,
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
        new_profile_image=parameters.profile_image,     # updates mate, only if user has right to edit original mate
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


##########################################################
# Teams
##########################################################

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


##########################################################
# Users
##########################################################

# Explaination:
# User accounts are used to store user data like what projects the user is working on, what they are interested in, what their goals are, etc.
# The OpenMates admin can choose if users who message mates via the chat software (mattermost, slack, etc.) are required to have an account. If not, the user will be treated as a guest without personalized responses.





##### For auth testing only #####

# Constants for JWT
ACCESS_TOKEN_EXPIRE_MINUTES = 30  # Short-lived access token
REFRESH_TOKEN_EXPIRE_DAYS = 7     # Longer-lived refresh token
ALGORITHM = "HS256"

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    email: str

# Add a simple in-memory blocklist (TODO: Replace with Redis)
REFRESH_TOKEN_BLOCKLIST: Set[str] = set()

@users_router.post("/v1/auth/login", response_model=Token)
@limiter.limit("5/minute")
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    response: Response = None
) -> Token:
    """
    Authenticate user and return JWT tokens
    """
    
    # Get credentials from environment
    env_email = os.getenv("WEB_APP_ADMIN_EMAIL")
    env_password = os.getenv("WEB_APP_ADMIN_PASSWORD")
    
    if not env_email or not env_password:
        logger.error("Admin credentials not configured in environment")
        raise HTTPException(
            status_code=500,
            detail="Server configuration error"
        )

    # First check if email matches
    if form_data.username != env_email:
        logger.warning(f"Failed login attempt - email mismatch")
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Hash the provided password and verify
    try:
        # Hash the provided password before comparing
        hashed_input = hashing(form_data.password)
        
        if verify_hash(hashed_input, env_password):
            logger.info(f"Successful login for user")
            
            # Create tokens
            access_token = create_access_token(
                data={"sub": form_data.username}
            )
            refresh_token = create_refresh_token(
                data={"sub": form_data.username}
            )

            # Set cookies
            response.set_cookie(
                key="access_token",
                value=f"Bearer {access_token}",
                httponly=True,
                secure=True,
                samesite="lax",
                max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
            )
            
            response.set_cookie(
                key="refresh_token",
                value=refresh_token,
                httponly=True,
                secure=True,
                samesite="lax",
                max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
            )

            return Token(
                access_token=access_token,
                refresh_token=refresh_token,
                token_type="bearer",
                email=form_data.username
            )
        else:
            logger.warning(f"Failed login attempt - password mismatch")
            raise HTTPException(
                status_code=401,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except Exception as e:
        logger.error(f"Error during password verification: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail="Authentication error",
            headers={"WWW-Authenticate": "Bearer"},
        )

@users_router.post("/v1/auth/refresh")
async def refresh_token(
    response: Response,
    refresh_token: str = Cookie(None)
) -> Token:
    """
    Use refresh token to get new access token
    """
    if not refresh_token:
        raise HTTPException(
            status_code=401,
            detail="Refresh token missing"
        )

    # Check if token is in blocklist
    if refresh_token in REFRESH_TOKEN_BLOCKLIST:
        logger.warning("Attempt to use blocked refresh token")
        raise HTTPException(
            status_code=401,
            detail="Token has been invalidated"
        )

    try:
        payload = jwt.decode(
            refresh_token,
            os.getenv("JWT_SECRET_KEY"),
            algorithms=[ALGORITHM]
        )
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid refresh token"
            )

        # Create new tokens
        new_access_token = create_access_token(data={"sub": email})
        new_refresh_token = create_refresh_token(data={"sub": email})

        # Add the old refresh token to blocklist
        REFRESH_TOKEN_BLOCKLIST.add(refresh_token)
        logger.debug("Added old refresh token to blocklist during refresh")

        # Set cookies
        response.set_cookie(
            key="access_token",
            value=f"Bearer {new_access_token}",
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )

        response.set_cookie(
            key="refresh_token",
            value=new_refresh_token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
        )

        return Token(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            email=email
        )
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid refresh token"
        )

@users_router.post("/v1/auth/logout")
async def logout(
    response: Response,
    refresh_token: str = Cookie(None)
):
    """
    Clear auth cookies and invalidate refresh token
    """
    try:
        logger.info("Processing logout request")
        # TODO add to separate file, also, add tests?
        
        # If there's a refresh token, add it to the blocklist
        if refresh_token:
            # TODO replace with dragonfly/redis
            REFRESH_TOKEN_BLOCKLIST.add(refresh_token)
            logger.debug("Added refresh token to blocklist")

        # Clear cookies with same settings they were set with
        response.delete_cookie(
            key="access_token",
            httponly=True,
            secure=True,
            samesite="lax"
        )
        response.delete_cookie(
            key="refresh_token",
            httponly=True,
            secure=True,
            samesite="lax"
        )
        
        logger.info("Successfully cleared auth cookies")
        return {"message": "Successfully logged out"}
        
    except Exception as e:
        logger.error(f"Error during logout: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Error during logout process"
        )

# Helper functions
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create JWT access token with explicit UTC timestamps
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "type": "access",
        "iat": datetime.now(timezone.utc)  # Add issued at time
    })
    
    return jwt.encode(
        to_encode,
        os.getenv("JWT_SECRET_KEY"),
        algorithm=ALGORITHM
    )

def create_refresh_token(data: dict) -> str:
    """
    Create JWT refresh token with explicit UTC timestamps
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    
    to_encode.update({
        "exp": expire,
        "type": "refresh",
        "iat": datetime.now(timezone.utc)  # Add issued at time
    })
    
    return jwt.encode(
        to_encode,
        os.getenv("JWT_SECRET_KEY"),
        algorithm=ALGORITHM
    )

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
    user_access: str = await validate_permissions(
        endpoint="/users",
        team_slug=team_slug,
        user_api_token=token
    )
    return await get_users_processing(
        user_access=user_access,
        team_slug=team_slug,
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
    ) -> UsersCreateOutput:
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
    username: str = Path(..., **input_parameter_descriptions["user_username"]),
    fields: Optional[List[str]] = Query(None, description="Which fields to include in the response. If not specified, all fields are returned.")
) -> dict:
    user_access: str = await validate_permissions(
        endpoint=f"/users/{username}",
        team_slug=team_slug,
        user_api_token=token
    )
    user: UserGetOneOutput = await get_user_processing(
        input=UserGetOneInput(
            team_slug=team_slug,
            api_token=token,
            username=username,
            user_access=user_access,
            fields=fields
        )
        )

    return user.to_api_output(fields)


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


##########################################################
# Skills
##########################################################

# Explaination:
# A skill is a single piece of functionality that a mate can use to help you. For example, ChatGPT, StableDiffusion, Notion or Figma.


# GET /apps/{app_slug}/{skill_slug} (get a skill)
@skills_router.get("/v1/{team_slug}/apps/{app_slug}/{skill_slug}", **skills_endpoints["get_skill"])
@limiter.limit("20/minute")
async def get_skill(
    request: Request,
    app_slug: str = Path(..., **input_parameter_descriptions["app_slug"]),
    skill_slug: str = Path(..., **input_parameter_descriptions["skill_slug"]),
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
    ):
    await validate_permissions(
        endpoint=f"/apps/{app_slug}/{skill_slug}",
        team_slug=team_slug,
        user_api_token=token
    )
    return await get_skill_processing(
        team_slug=team_slug,
        app_slug=app_slug,
        skill_slug=skill_slug,
        include_populated_data=True,
        output_raw_data=False,
        output_format="JSONResponse"
    )


##########################################################
# Tasks
##########################################################

# Explaination:
# A task is a scheduled run of a single skill or a whole workflow. It can happen once, or repeated.
@tasks_router.get("/v1/{team_slug}/tasks/{task_id}", **tasks_endpoints["get_task"])
@limiter.limit("30/minute")
async def get_task(
    request: Request,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    task_id: str = Path(..., description="The ID of the task"),
    token: str = Depends(get_credentials)
) -> Task:
    await validate_permissions(
        endpoint="/tasks/{task_id}",
        team_slug=team_slug,
        user_api_token=token
    )

    return await tasks_get_task_processing(task_id)


@tasks_router.delete("/v1/{team_slug}/tasks/{task_id}", **tasks_endpoints["cancel"])
@limiter.limit("20/minute")
async def cancel_task(
    request: Request,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    task_id: str = Path(..., description="The ID of the task to cancel"),
    token: str = Depends(get_credentials)
) -> TasksCancelOutput:
    await validate_permissions(
        endpoint="/tasks/{task_id}",
        team_slug=team_slug,
        user_api_token=token
    )

    return await tasks_cancel_processing(task_id)


##########################################################
# Billing
##########################################################

# Explaination:
# The billing endpoints allow users or team owners to manage their billing settings, download invoices and more.

# POST /billing/get_balance (get the balance of the user or the team)
@billing_router.post("/v1/{team_slug}/billing/get_balance", **billing_endpoints["get_balance"])
@limiter.limit("20/minute")
async def get_balance(
    request: Request,
    parameters: BillingGetBalanceInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> BillingBalanceOutput:
    await validate_permissions(
        endpoint="/billing/get_balance",
        team_slug=team_slug,
        user_api_token=token
    )
    return await billing_get_balance_processing(
        team_slug=team_slug,
        api_token=token,
        for_team=parameters.for_team
    )


##########################################################
# Server
##########################################################

# Explaination:
# The server is the core software that runs OpenMates.

# TODO add test
# GET /server/status (get server status)
@server_router.get("/v1/server/status", **server_endpoints["get_status"])
@limiter.limit("20/minute")
async def get_status(
    request: Request,
    token: str = Depends(get_credentials)
    ):
    await validate_permissions(
        endpoint="/server/status",
        user_api_token=token
    )
    return {"status": "online"}

# TODO add test
# GET /server/settings (get server settings)
@server_router.get("/v1/server/settings", **server_endpoints["get_settings"])
@limiter.limit("20/minute")
async def get_settings(
    request: Request,
    token: str = Depends(get_credentials)
    ):
    return {"info": "endpoint still needs to be implemented"}


# TODO add test
# PATCH /server/settings (update server settings)
@server_router.patch("/v1/server/settings", **server_endpoints["update_settings"])
@limiter.limit("20/minute")
async def update_settings(
    request: Request,
    token: str = Depends(get_credentials)
    ):
    return {"info": "endpoint still needs to be implemented"}


##########################################################
# Workflows
##########################################################
# will be placed here...


##########################################################
# Apps
##########################################################

# AI

# POST /apps/ai/ask (ask a question to an AI)
@require_feature('apps.ai.skills.ask.allowed')
@apps_ai_router.post("/v1/{team_slug}/apps/ai/ask", **apps_ai_endpoints["ask"])
@limiter.limit("20/minute")
async def skill_ai_ask(
    request: Request,
    parameters: AiAskInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> Union[AiAskOutput, StreamingResponse]:
    await validate_permissions(
        endpoint="/apps/ai/ask",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_ai_ask_processing(
        user_api_token=token,
        team_slug=team_slug,
        input=parameters
    )


# POST /apps/ai/estimate_cost (estimate the cost of an AI call)
@require_feature('apps.ai.skills.estimate_cost.allowed')
@apps_ai_router.post("/v1/{team_slug}/apps/ai/estimate_cost", **apps_ai_endpoints["estimate_cost"])
@limiter.limit("20/minute")
async def skill_ai_estimate_cost(
    request: Request,
    parameters: AiEstimateCostInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> AiEstimateCostOutput:
    await validate_permissions(
        endpoint="/apps/ai/estimate_cost",
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


# Audio

# POST /apps/audio/generate_transcript (generate transcript)
@require_feature('apps.audio.skills.generate_transcript.allowed')
@apps_audio_router.post("/v1/{team_slug}/apps/audio/generate_transcript", **apps_audio_endpoints["generate_transcript"])
@limiter.limit("20/minute")
async def skill_audio_generate_transcript(
    request: Request,
    file: UploadFile = File(..., **input_parameter_descriptions["file"]),
    provider: str = Form(..., description="The provider to use for generating the transcript"),
    model: str = Form(..., description="The model to use for generating the transcript"),
    stream: bool = Form(False, description="Whether to stream the transcript"),
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> AudioGenerateTranscriptOutput:
    # TODO output either StreamingResponse or Task
    await validate_permissions(
        endpoint="/apps/audio/generate_transcript",
        team_slug=team_slug,
        user_api_token=token
    )

    audio_data = await file.read()
    if len(audio_data) == 0:
        raise HTTPException(status_code=400, detail="No audio data provided")
    if len(audio_data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio size exceeds 10MB limit")

    return await skill_audio_generate_transcript_processing(
        input=AudioGenerateTranscriptInput(
            audio_data=audio_data,
            provider=AudioTranscriptAiProvider(
                name=provider,
                model=model
            ),
            stream=stream
        )
)


# # POST /apps/audio/generate_speech (generate speech)
# @require_feature('apps.audio.skills.generate_speech.allowed')
# @apps_audio_router.post("/v1/{team_slug}/apps/audio/generate_speech", **apps_audio_endpoints["generate_speech"])
# @limiter.limit("20/minute")
# async def skill_audio_generate_speech(
#     request: Request,
#     parameters: AudioGenerateSpeechInput,
#     team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
#     token: str = Depends(get_credentials)
# ) -> AudioGenerateSpeechOutput:
#     # TODO output either StreamingResponse or Task.
#     await validate_permissions(
#         endpoint="/apps/audio/generate_speech",
#         team_slug=team_slug,
#         user_api_token=token
#     )

#
# TODO add websocket endpoint for generate_transcript
# TODO add websocket endpoint for generate_speech


# Books

# POST /apps/books/translate
@require_feature('apps.books.skills.translate.allowed')
@apps_books_router.post("/v1/{team_slug}/apps/books/translate", **apps_books_endpoints["translate"])
@limiter.limit("20/minute")
async def skill_books_translate(
    request: Request,
    file: UploadFile = File(..., **input_parameter_descriptions["file"]),
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials),
    output_language: str = Form(None, description="The output language of the ebook."),
    output_format: Literal["epub", "pdf"] = Form("epub", description="The output format of the ebook.")
) -> Task:
    await validate_permissions(
        endpoint="/apps/books/translate",
        team_slug=team_slug,
        user_api_token=token
    )

    ebook_data = await file.read()
    if len(ebook_data) == 0:
        raise HTTPException(status_code=400, detail="No epub file provided")

    if len(ebook_data) > 40 * 1024 * 1024:  # Example size limit of 40MB
        raise HTTPException(status_code=413, detail="Ebook size exceeds 40MB limit")

    # Save the bytes to a temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as temp_file:
        temp_file.write(ebook_data)
        temp_file_path = temp_file.name

    try:
        epub.read_epub(temp_file_path)  # Pass the file path to read_epub
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid EPUB file: {str(e)}")
    finally:
        os.remove(temp_file_path)  # Clean up the temporary file

    task = await tasks_create_processing(
        team_slug=team_slug,
        title="apps/Books/Translate",
        api_endpoint="/apps/books/translate"
    )

    # Create the task
    book_translate_task.apply_async(
        args=[
            task.id,
            team_slug,
            token,
            ebook_data,
            output_language,
            output_format
        ],
        task_id=task.id
    )

    return task


# Docs

# POST /apps/docs/create (create a new document)
@require_feature('apps.docs.skills.create.allowed')
@apps_docs_router.post("/v1/{team_slug}/apps/docs/create", **apps_docs_endpoints["create"])
@limiter.limit("20/minute")
async def skill_docs_create(
    request: Request,
    parameters: DocsCreateInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> FilesUploadOutput:
    await validate_permissions(
        endpoint="/apps/docs/create",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_docs_create_processing(
        team_slug=team_slug,
        api_token=token,
        title=parameters.title,
        elements=parameters.elements
    )


# Files

# POST /apps/files/upload (upload a file)
@require_feature('apps.files.skills.upload.allowed')
@apps_files_router.post("/v1/{team_slug}/apps/files/upload", **apps_files_endpoints["upload"])
@limiter.limit("20/minute")
async def skill_files_upload(
    request: Request,
    file: UploadFile = File(..., description="The file to upload"),
    team_slug: str = Path(..., description="The team slug"),
    token: str = Depends(get_credentials),
    provider: str = Form(..., description="The storage provider"),
    file_name: str = Form(..., description="The name of the file"),
    folder_path: str = Form(..., description="The folder path where the file will be stored"),
    expiration_datetime: Optional[str] = Form(None, description="The expiration date and time of the file"),
    access_public: bool = Form(False, description="If set to True, the file will be publicly accessible"),
    read_access_limited_to_teams: Optional[List[str]] = Form(None, description="List of teams with read access"),
    read_access_limited_to_users: Optional[List[str]] = Form(None, description="List of users with read access"),
    write_access_limited_to_teams: Optional[List[str]] = Form(None, description="List of teams with write access"),
    write_access_limited_to_users: Optional[List[str]] = Form(None, description="List of users with write access")
) -> FilesUploadOutput:
    await validate_permissions(
        endpoint="/apps/files/upload",
        team_slug=team_slug,
        user_api_token=token,
        required_permissions=["files:upload"]
    )

    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="No file provided")

    if len(contents) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File size exceeds 20MB limit")

    return await skill_files_upload_processing(
        team_slug=team_slug,
        api_token=token,
        provider=provider,
        file_name=file_name,
        file_data=contents,
        expiration_datetime=expiration_datetime,
        access_public=access_public,
        folder_path=folder_path,
        read_access_limited_to_teams=read_access_limited_to_teams,
        read_access_limited_to_users=read_access_limited_to_users,
        write_access_limited_to_teams=write_access_limited_to_teams,
        write_access_limited_to_users=write_access_limited_to_users
    )


# TODO add endpoint for shared files
# # GET /apps/files/{provider}/shared/{file_path} (download a shared file)
# @apps_files_router.get("/v1/{team_slug}/apps/files/{provider}/shared/{file_path:path}", **apps_files_endpoints["download_shared"])
# @limiter.limit("20/minute")
# async def skill_files_download_shared(
#     request: Request,
#     provider: str = Path(..., **input_parameter_descriptions["provider"]),
#     file_path: str = Path(..., **input_parameter_descriptions["file_path"]),
#     team_slug: str = Path(..., **input_parameter_descriptions["team_slug"])
# ) -> StreamingResponse:
#     return await skill_files_download_processing(
#         provider=provider,
#         file_path=file_path
#     )


# GET /apps/files/{provider}/{file_path} (download a file)
@require_feature('apps.files.skills.download.allowed')
@apps_files_router.get("/v1/{team_slug}/apps/files/{provider}/{file_path:path}", **apps_files_endpoints["download"])
@limiter.limit("20/minute")
async def skill_files_download(
    request: Request,
    provider: str = Path(..., **input_parameter_descriptions["provider"]),
    file_path: str = Path(..., **input_parameter_descriptions["file_path"]),
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> StreamingResponse:
    await validate_permissions(
        endpoint=f"/apps/files/{provider}/{file_path}",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_files_download_processing(
        provider=provider,
        api_token=token,
        file_path=file_path
    )


# DELETE /apps/files/{provider}/{file_path} (delete a file)
@apps_files_router.delete("/v1/{team_slug}/apps/files/{provider}/{file_path:path}", **apps_files_endpoints["delete"])
@limiter.limit("20/minute")
async def skill_files_delete(
    request: Request,
    provider: str = Path(..., **input_parameter_descriptions["provider"]),
    file_path: str = Path(..., **input_parameter_descriptions["file_path"]),
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> FilesDeleteOutput:
    await validate_permissions(
        endpoint=f"/apps/files/{provider}/{file_path}",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_files_delete_processing(
        provider=provider,
        file_path=file_path
    )


# Finance

# POST /apps/finance/get_report (get a finance report)
@require_feature('apps.finance.skills.get_report.allowed')
@apps_finance_router.post("/v1/{team_slug}/apps/finance/get_report", **apps_finance_endpoints["get_report"])
@limiter.limit("20/minute")
async def skill_finance_get_report(
    request: Request,
    parameters: FinanceGetReportInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> FinanceGetReportOutput:
    await validate_permissions(
        endpoint="/apps/finance/get_report",
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


# POST /apps/finance/get_transactions (get transactions)
@require_feature('apps.finance.skills.get_transactions.allowed')
@apps_finance_router.post("/v1/{team_slug}/apps/finance/get_transactions", **apps_finance_endpoints["get_transactions"])
@limiter.limit("20/minute")
async def skill_finance_get_transactions(
    request: Request,
    parameters: FinanceGetTransactionsInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> FinanceGetTransactionsOutput:
    await validate_permissions(
        endpoint="/apps/finance/get_transactions",
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


# Health

# POST /apps/health/search_doctors (search for doctors)
@require_feature('apps.health.skills.search_doctors.allowed')
@apps_health_router.post("/v1/{team_slug}/apps/health/search_doctors", **apps_health_endpoints["search_doctors"])
@limiter.limit("20/minute")
async def skill_health_search_doctors(
    request: Request,
    parameters: HealthSearchDoctorsInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> HealthSearchDoctorsOutput:
    await validate_permissions(
        endpoint="/apps/health/search_doctors",
        team_slug=team_slug,
        user_api_token=token
    )

    task = await tasks_create_processing(
        team_slug=team_slug,
        title="apps/Health/SearchDoctors",
        api_endpoint="/apps/health/search_doctors"
    )

    # Create the task
    health_search_doctors_task.apply_async(
        args=[
            task.id,
            team_slug,
            token,
            parameters
        ],
        task_id=task.id
    )
    return task


# POST /apps/health/search_appointments (search for appointments)
@require_feature('apps.health.skills.search_appointments.allowed')
@apps_health_router.post("/v1/{team_slug}/apps/health/search_appointments", **apps_health_endpoints["search_appointments"])
@limiter.limit("20/minute")
async def skill_health_search_appointments(
    request: Request,
    parameters: HealthSearchAppointmentsInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> HealthSearchAppointmentsOutput:
    await validate_permissions(
        endpoint="/apps/health/search_appointments",
        team_slug=team_slug,
        user_api_token=token
    )

    task = await tasks_create_processing(
        team_slug=team_slug,
        title="apps/Health/SearchAppointments",
        api_endpoint="/apps/health/search_appointments"
    )

    # Create the task
    health_search_appointments_task.apply_async(
        args=[
            task.id,
            team_slug,
            token,
            parameters
        ],
        task_id=task.id
    )
    return task


# Home

# POST /apps/home/get_all_devices (get all devices at home)
@require_feature('apps.home.skills.get_all_devices.allowed')
@apps_home_router.post("/v1/{team_slug}/apps/home/get_all_devices", **apps_home_endpoints["get_all_devices"])
@limiter.limit("20/minute")
async def skill_home_get_all_devices(
    request: Request,
    parameters: HomeGetAllDevicesInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> HomeGetAllDevicesOutput:
    await validate_permissions(
        endpoint="/apps/home/get_all_devices",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_home_get_all_devices_processing(
        team_slug=team_slug,
        api_token=token,
        input=parameters
    )


# POST /apps/home/get_all_scenes (get all scenes at home)
@require_feature('apps.home.skills.get_all_scenes.allowed')
@apps_home_router.post("/v1/{team_slug}/apps/home/get_all_scenes", **apps_home_endpoints["get_all_scenes"])
@limiter.limit("20/minute")
async def skill_home_get_all_scenes(
    request: Request,
    parameters: HomeGetAllScenesInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> HomeGetAllScenesOutput:
    await validate_permissions(
        endpoint="/apps/home/get_all_scenes",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_home_get_all_scenes_processing(
        team_slug=team_slug,
        api_token=token,
        input=parameters
    )


# POST /apps/home/add_device (add a device to the smart home)
@require_feature('apps.home.skills.add_device.allowed')
@apps_home_router.post("/v1/{team_slug}/apps/home/add_device", **apps_home_endpoints["add_device"])
@limiter.limit("20/minute")
async def skill_home_add_device(
    request: Request,
    parameters: HomeAddDeviceInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> HomeAddDeviceOutput:
    await validate_permissions(
        endpoint="/apps/home/add_device",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_home_add_device_processing(
        team_slug=team_slug,
        api_token=token,
        input=parameters
    )


# POST /apps/home/add_scene (add a scene to the smart home)
@require_feature('apps.home.skills.add_scene.allowed')
@apps_home_router.post("/v1/{team_slug}/apps/home/add_scene", **apps_home_endpoints["add_scene"])
@limiter.limit("20/minute")
async def skill_home_add_scene(
    request: Request,
    parameters: HomeAddSceneInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> HomeAddSceneOutput:
    await validate_permissions(
        endpoint="/apps/home/add_scene",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_home_add_scene_processing(
        team_slug=team_slug,
        api_token=token,
        input=parameters
    )


# PUT /apps/home/set_scene (set a scene at home)
@require_feature('apps.home.skills.set_scene.allowed')
@apps_home_router.put("/v1/{team_slug}/apps/home/set_scene", **apps_home_endpoints["set_scene"])
@limiter.limit("20/minute")
async def skill_home_set_scene(
    request: Request,
    parameters: HomeSetSceneInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> HomeSetSceneOutput:
    await validate_permissions(
        endpoint="/apps/home/set_scene",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_home_set_scene_processing(
        team_slug=team_slug,
        api_token=token,
        input=parameters
    )


# PUT /apps/home/set_device (set a device at home)
@require_feature('apps.home.skills.set_device.allowed')
@apps_home_router.put("/v1/{team_slug}/apps/home/set_device", **apps_home_endpoints["set_device"])
@limiter.limit("20/minute")
async def skill_home_set_device(
    request: Request,
    parameters: HomeSetDeviceInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> HomeSetDeviceOutput:
    await validate_permissions(
        endpoint="/apps/home/set_device",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_home_set_device_processing(
        team_slug=team_slug,
        api_token=token,
        input=parameters
    )


# POST /apps/home/get_temperature (get the temperature at home)
@require_feature('apps.home.skills.get_temperature.allowed')
@apps_home_router.post("/v1/{team_slug}/apps/home/get_temperature", **apps_home_endpoints["get_temperature"])
@limiter.limit("20/minute")
async def skill_home_get_temperature(
    request: Request,
    parameters: HomeGetTemperatureInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> HomeGetTemperatureOutput:
    await validate_permissions(
        endpoint="/apps/home/get_temperature",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_home_get_temperature_processing(
        team_slug=team_slug,
        api_token=token,
        input=parameters
    )


# POST /apps/home/get_power_consumption (get the power consumption at home)
@require_feature('apps.home.skills.get_power_consumption.allowed')
@apps_home_router.post("/v1/{team_slug}/apps/home/get_power_consumption", **apps_home_endpoints["get_power_consumption"])
@limiter.limit("20/minute")
async def skill_home_get_power_consumption(
    request: Request,
    parameters: HomeGetPowerConsumptionInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> HomeGetPowerConsumptionOutput:
    await validate_permissions(
        endpoint="/apps/home/get_power_consumption",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_home_get_power_consumption_processing(
        team_slug=team_slug,
        api_token=token,
        input=parameters
    )


# Maps

# POST /apps/maps/search_places (search for places)
@require_feature('apps.maps.skills.search.allowed')
@apps_maps_router.post("/v1/{team_slug}/apps/maps/search", **apps_maps_endpoints["search"])
@limiter.limit("20/minute")
async def skill_maps_search_places(
    request: Request,
    parameters: MapsSearchInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> MapsSearchOutput:
    await validate_permissions(
        endpoint="/apps/maps/search",
        team_slug=team_slug,
        user_api_token=token
    )

    return await skill_maps_search_processing(
        team_slug=team_slug,
        api_token=token,
        input=parameters
    )


# Messages

# POST /apps/messages/send (send a message)
@require_feature('apps.messages.skills.send.allowed')
@apps_messages_router.post("/v1/{team_slug}/apps/messages/send", **apps_messages_endpoints["send"])
@limiter.limit("20/minute")
async def skill_messages_send(
    request: Request,
    parameters: MessagesSendInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> MessagesSendOutput:
    await validate_permissions(
        endpoint="/apps/messages/send",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_messages_send_processing(
        message=parameters.message,
        ai_mate_username=parameters.ai_mate_username,
        target=parameters.target,
        attachments=parameters.attachments
    )


# POST /apps/messages/connect (connect to a server)
@require_feature('apps.messages.skills.connect.allowed')
@apps_messages_router.post("/v1/{team_slug}/apps/messages/connect", **apps_messages_endpoints["connect"])
@limiter.limit("20/minute")
async def skill_messages_connect(
    request: Request,
    parameters: MessagesConnectInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> MessagesConnectOutput:
    await validate_permissions(
        endpoint="/apps/messages/connect",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_messages_connect_processing(
        team_name=parameters.team_name,
        include_all_bots=parameters.include_all_bots,
        bots=parameters.bots
    )


# PDF Editor
# will be placed here...


# Photos

# TODO add test
# POST /apps/photos/resize (resize an image)
@require_feature('apps.photos.skills.resize.allowed')
@apps_photos_router.post("/v1/{team_slug}/apps/photos/resize", **apps_photos_endpoints["resize_image"])
@limiter.limit("20/minute")
async def skill_photos_resize(
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
        endpoint="/apps/photos/resize",
        team_slug=team_slug,
        user_api_token=token
    )

    image_data = await file.read()
    if len(image_data) == 0:
        raise HTTPException(status_code=400, detail="No image provided")

    if len(image_data) > 10 * 1024 * 1024:  # Example size limit of 10MB
        raise HTTPException(status_code=413, detail="Image size exceeds 10MB limit")

    return await skill_photos_resize_image_processing(
        image_data=image_data,
        target_resolution_width=target_resolution_width,
        target_resolution_height=target_resolution_height,
        max_length=max_length,
        method=method,
        use_ai_upscaling_if_needed=use_ai_upscaling_if_needed,
        output_square=output_square
    )


# Travel

# POST /apps/travel/search_connections (search for connections)
@require_feature('apps.travel.skills.search_connections.allowed')
@apps_travel_router.post("/v1/{team_slug}/apps/travel/search_connections", **apps_travel_endpoints["search_connections"])
@limiter.limit("20/minute")
async def skill_travel_search_connections(
    request: Request,
    parameters: TravelSearchConnectionsInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> TravelSearchConnectionsOutput:
    await validate_permissions(
        endpoint="/apps/travel/search_connections",
        team_slug=team_slug,
        user_api_token=token
    )

    return await skill_travel_search_connections_processing(
        team_slug=team_slug,
        api_token=token,
        input=parameters
    )


# Videos

# POST /apps/videos/transcript (get the transcript of a video)
@require_feature('apps.videos.skills.get_transcript.allowed')
@apps_videos_router.post("/v1/{team_slug}/apps/videos/transcript", **apps_videos_endpoints["get_transcript"])
@limiter.limit("20/minute")
async def skill_videos_get_transcript(
    request: Request,
    parameters: VideosGetTranscriptInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> VideosGetTranscriptOutput:
    await validate_permissions(
        endpoint="/apps/videos/transcript",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_videos_get_transcript_processing(
        url=parameters.url,
        block_token_limit=parameters.block_token_limit
    )


# Web

# POST /apps/web/read (read a web page)
@require_feature('apps.web.skills.read.allowed')
@apps_web_router.post("/v1/{team_slug}/apps/web/read", **apps_web_endpoints["read"])
@limiter.limit("20/minute")
async def skill_web_read(
    request: Request,
    parameters: WebReadInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> WebReadOutput:
    await validate_permissions(
        endpoint="/apps/web/read",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_web_read_processing(
        url=parameters.url,
        include_images=parameters.include_images
    )


# POST /apps/web/view (view a web page)
@require_feature('apps.web.skills.view.allowed')
@apps_web_router.post("/v1/{team_slug}/apps/web/view", **apps_web_endpoints["view"])
@limiter.limit("20/minute")
async def skill_web_view(
    request: Request,
    parameters: WebViewInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> WebViewOutput:
    await validate_permissions(
        endpoint="/apps/web/view",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_web_view_processing(
        url=parameters.url
    )


# TODO fix script, so it excludes apps if they not allowed in env.
# also define app_routers based on apps.yml file, instead of hardcoding them

# Register base routers that are always enabled
CORE_ROUTERS = [
    (router, ["AI Call"]),
    (mates_router, ["Mates"]),
    (apps_router, ["Apps"]),
    (skills_router, ["Skills"]),
    (workflows_router, ["Workflows"]),
    (tasks_router, ["Tasks"]),
    (billing_router, ["Billing"]),
    (server_router, ["Server"]),
    (teams_router, ["Teams"]),
    (users_router, ["Users"])
]

# Register optional app routers
APP_ROUTERS = [
    (apps_ai_router, "AI", "apps.ai.allowed", ["Apps | AI"]),
    (apps_audio_router, "Audio", "apps.audio.allowed", ["Apps | Audio"]),
    (apps_books_router, "Books", "apps.books.allowed", ["Apps | Books"]),
    (apps_docs_router, "Docs", "apps.docs.allowed", ["Apps | Docs"]),
    (apps_files_router, "Files", "apps.files.allowed", ["Apps | Files"]),
    (apps_finance_router, "Finance", "apps.finance.allowed", ["Apps | Finance"]),
    (apps_health_router, "Health", "apps.health.allowed", ["Apps | Health"]),
    (apps_home_router, "Home", "apps.home.allowed", ["Apps | Home"]),
    (apps_maps_router, "Maps", "apps.maps.allowed", ["Apps | Maps"]),
    (apps_messages_router, "Messages", "apps.messages.allowed", ["Apps | Messages"]),
    (apps_pdf_editor_router, "PDF Editor", "apps.pdf_editor.allowed", ["Apps | PDF Editor"]),
    (apps_photos_router, "Photos", "apps.photos.allowed", ["Apps | Photos"]),
    (apps_travel_router, "Travel", "apps.travel.allowed", ["Apps | Travel"]),
    (apps_videos_router, "Videos", "apps.videos.allowed", ["Apps | Videos"]),
    (apps_web_router, "Web", "apps.web.allowed", ["Apps | Web"])
]

# Register all routers
def register_all_routers(app: FastAPI) -> None:
    """Register all routers with the FastAPI application."""
    logger.debug("Registering core routers...")
    for router, tags in CORE_ROUTERS:
        app.include_router(router, tags=tags)

    # Track connected and disconnected apps/skills
    connected_apps = []
    disconnected_apps = []
    connected_skills = []
    disconnected_skills = []

    # Check all skills first
    logger.debug("Checking skill endpoints...")
    for router, name, config_path, tags in APP_ROUTERS:
        # Check each skill endpoint for this app
        skill_endpoints = [route for route in router.routes]
        for endpoint in skill_endpoints:
            skill_name = endpoint.path.split('/')[-1]

            # Check if endpoint has a config path defined
            config_path = getattr(endpoint.endpoint, '_config_path', None)
            if config_path is None:
                # If no config path, automatically include it
                connected_skills.append(f"{name} | {skill_name}")
                continue

            # Check if the skill is enabled
            if get_server_config(config_path):
                connected_skills.append(f"{name} | {skill_name}")
            else:
                disconnected_skills.append(f"{name} | {skill_name}")

    logger.debug("Registering app routers...")
    for router, name, config_path, tags in APP_ROUTERS:
        if get_server_config(config_path):
            app.include_router(router, tags=tags)
            connected_apps.append(name)
        else:
            disconnected_apps.append(name)

    # Log summary
    if len(connected_apps) > 0:
        logger.info("=== Connected Apps ===")
        for app_name in sorted(connected_apps):
            logger.info(f"✓ {app_name}")

    if len(disconnected_apps) > 0:
        logger.info("\n=== Disconnected Apps ===")
        for app_name in sorted(disconnected_apps):
            logger.info(f"✗ {app_name}")

    if len(connected_skills) > 0:
        logger.info("\n=== Connected Skills ===")
        for skill in sorted(connected_skills):
            logger.info(f"✓ {skill}")

    if len(disconnected_skills) > 0:
        logger.info("\n=== Disconnected Skills ===")
        for skill in sorted(disconnected_skills):
            logger.info(f"✗ {skill}")

# Register all routers
register_all_routers(app)

# Add a cleanup function to remove expired tokens from blocklist
# This could be called periodically using a background task
async def cleanup_token_blocklist():
    """Remove expired tokens from the blocklist"""
    try:
        to_remove = set()
        for token in REFRESH_TOKEN_BLOCKLIST:
            try:
                # Try to decode the token
                payload = jwt.decode(
                    token,
                    os.getenv("JWT_SECRET_KEY"),
                    algorithms=[ALGORITHM]
                )
                # If token is expired, mark it for removal
                exp = payload.get("exp")
                if exp and datetime.utcfromtimestamp(exp) < datetime.utcnow():
                    to_remove.add(token)
            except JWTError:
                # If token is invalid/expired, mark it for removal
                to_remove.add(token)
        
        # Remove the expired tokens
        REFRESH_TOKEN_BLOCKLIST.difference_update(to_remove)
        logger.debug(f"Cleaned up {len(to_remove)} expired tokens from blocklist")
    except Exception as e:
        logger.error(f"Error during token blocklist cleanup: {str(e)}")
