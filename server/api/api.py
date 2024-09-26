from server.api import *
from server.api.docs.docs import setup_docs, bearer_scheme

logger = logging.getLogger(__name__)


##################################
######### Setup FastAPI ##########
##################################

# TODO dynamically load skill API endpoints, depending on which are in strapi database


# Create new routers
files_router = APIRouter()
mates_router = APIRouter()
skills_router = APIRouter()
skills_ai_router = APIRouter()
skills_messages_router = APIRouter()
skills_code_router = APIRouter()
skills_finance_router = APIRouter()
skills_docs_router = APIRouter()
skills_files_router = APIRouter()
skills_books_router = APIRouter()
skills_videos_router = APIRouter()
skills_photos_router = APIRouter()
skills_web_router = APIRouter()
skills_business_router = APIRouter()
software_router = APIRouter()
workflows_router = APIRouter()
tasks_router = APIRouter()
billing_router = APIRouter()
server_router = APIRouter()
teams_router = APIRouter()
users_router = APIRouter()


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


# Add CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


# Add rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

@app.exception_handler(RateLimitExceeded)
async def ratelimit_handler(request, exc):
    raise HTTPException(
        status_code=HTTP_429_TOO_MANY_REQUESTS,
        detail="Too Many Requests"
    )


# Setup custom documentation
setup_docs(app)

##################################
######### Web interface ##########
##################################

# GET / (get the index.html file)
@app.get("/",include_in_schema=False)
@limiter.limit("20/minute")
def read_root(request: Request):
    return FileResponse(os.path.join(os.path.dirname(__file__), 'endpoints/index.html'))


##################################
######### Mates ##################
##################################

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


# POST /skills/ai/ask (ask a question to an AI)
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


# POST /skills/ai/estimate_cost (estimate the cost of an AI call)
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


# POST /skills/messages/send (send a message)
@skills_messages_router.post("/v1/{team_slug}/skills/messages/send", **skills_messages_endpoints["send"])
@limiter.limit("20/minute")
async def skill_messages_send(
    request: Request,
    parameters: MessagesSendInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> MessagesSendOutput:
    await validate_permissions(
        endpoint="/skills/messages/send",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_messages_send_processing(
        message=parameters.message,
        ai_mate_username=parameters.ai_mate_username,
        target=parameters.target,
        attachments=parameters.attachments
    )


# POST /skills/messages/connect (connect to a server)
@skills_messages_router.post("/v1/{team_slug}/skills/messages/connect", **skills_messages_endpoints["connect"])
@limiter.limit("20/minute")
async def skill_messages_connect(
    request: Request,
    parameters: MessagesConnectInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> MessagesConnectOutput:
    await validate_permissions(
        endpoint="/skills/messages/connect",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_messages_connect_processing(
        team_name=parameters.team_name,
        include_all_bots=parameters.include_all_bots,
        bots=parameters.bots
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


# POST /skills/finance/get_report (get a finance report)
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


# POST /skills/finance/get_transactions (get transactions)
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


# POST /skills/docs/create (create a new document)
@skills_docs_router.post("/v1/{team_slug}/skills/docs/create", **skills_docs_endpoints["create"])
@limiter.limit("20/minute")
async def skill_docs_create(
    request: Request,
    parameters: DocsCreateInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> FilesUploadOutput:
    await validate_permissions(
        endpoint="/skills/docs/create",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_docs_create_processing(
        team_slug=team_slug,
        api_token=token,
        title=parameters.title,
        elements=parameters.elements
    )


# POST /skills/files/upload (upload a file)
@skills_files_router.post("/v1/{team_slug}/skills/files/upload", **skills_files_endpoints["upload"])
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
        endpoint="/skills/files/upload",
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
# # GET /skills/files/{provider}/shared/{file_path} (download a shared file)
# @skills_files_router.get("/v1/{team_slug}/skills/files/{provider}/shared/{file_path:path}", **skills_files_endpoints["download_shared"])
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


# GET /skills/files/{provider}/{file_path} (download a file)
@skills_files_router.get("/v1/{team_slug}/skills/files/{provider}/{file_path:path}", **skills_files_endpoints["download"])
@limiter.limit("20/minute")
async def skill_files_download(
    request: Request,
    provider: str = Path(..., **input_parameter_descriptions["provider"]),
    file_path: str = Path(..., **input_parameter_descriptions["file_path"]),
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> StreamingResponse:
    await validate_permissions(
        endpoint=f"/skills/files/{provider}/{file_path}",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_files_download_processing(
        provider=provider,
        api_token=token,
        file_path=file_path
    )


# DELETE /skills/files/{provider}/{file_path} (delete a file)
@skills_files_router.delete("/v1/{team_slug}/skills/files/{provider}/{file_path:path}", **skills_files_endpoints["delete"])
@limiter.limit("20/minute")
async def skill_files_delete(
    request: Request,
    provider: str = Path(..., **input_parameter_descriptions["provider"]),
    file_path: str = Path(..., **input_parameter_descriptions["file_path"]),
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> FilesDeleteOutput:
    await validate_permissions(
        endpoint=f"/skills/files/{provider}/{file_path}",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_files_delete_processing(
        provider=provider,
        file_path=file_path
    )


# POST /skills/videos/transcript (get the transcript of a video)
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


# POST /skills/web/read (read a web page)
@skills_web_router.post("/v1/{team_slug}/skills/web/read", **skills_web_endpoints["read"])
@limiter.limit("20/minute")
async def skill_web_read(
    request: Request,
    parameters: WebReadInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> WebReadOutput:
    await validate_permissions(
        endpoint="/skills/web/read",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_web_read_processing(
        url=parameters.url,
        include_images=parameters.include_images
    )


# POST /skills/web/view (view a web page)
@skills_web_router.post("/v1/{team_slug}/skills/web/view", **skills_web_endpoints["view"])
@limiter.limit("20/minute")
async def skill_web_view(
    request: Request,
    parameters: WebViewInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> WebViewOutput:
    await validate_permissions(
        endpoint="/skills/web/view",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_web_view_processing(
        url=parameters.url
    )


# TODO add test
# POST /skills/photos/resize (resize an image)
@skills_photos_router.post("/v1/{team_slug}/skills/photos/resize", **skills_photos_endpoints["resize_image"])
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
        endpoint="/skills/photos/resize",
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


# POST /skills/books/translate
@skills_books_router.post("/v1/{team_slug}/skills/books/translate", **skills_books_endpoints["translate"])
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
        endpoint="/skills/books/translate",
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
        title="Skills/Books/Translate",
        api_endpoint="/skills/books/translate"
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


# POST /skills/business/create_pitch
@skills_business_router.post("/v1/{team_slug}/skills/business/create_pitch", **skills_business_endpoints["create_pitch"])
@limiter.limit("20/minute")
async def skill_business_create_pitch(
    request: Request,
    parameters: BusinessCreatePitchInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> BusinessCreatePitchOutput:
    await validate_permissions(
        endpoint="/skills/business/create_pitch",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_business_create_pitch_processing(
        what=parameters.what,
        name=parameters.name,
        existing_pitch=parameters.existing_pitch,
        short_description=parameters.short_description,
        in_depth_description=parameters.in_depth_description,
        highlights=parameters.highlights,
        impact=parameters.impact,
        potential_future=parameters.potential_future,
        target_audience=parameters.target_audience,
        unique_selling_proposition=parameters.unique_selling_proposition,
        goals=parameters.goals,
        market_analysis=parameters.market_analysis,
        users=parameters.users,
        problems=parameters.problems,
        solutions=parameters.solutions,
        team_information=parameters.team_information,
        financial_projections=parameters.financial_projections,
        customer_testimonials=parameters.customer_testimonials,
        pitch_type=parameters.pitch_type,
        pitch_type_other_use_case=parameters.pitch_type_other_use_case
    )


# POST /skills/business/plan_application
@skills_business_router.post("/v1/{team_slug}/skills/business/plan_application", **skills_business_endpoints["plan_application"])
@limiter.limit("20/minute")
async def skill_business_plan_application(
    request: Request,
    parameters: BusinessPlanApplicationInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> BusinessPlanApplicationOutput:
    await validate_permissions(
        endpoint="/skills/business/plan_application",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_business_plan_application_processing(
        name=parameters.name
    )


# POST /skills/business/create_application
@skills_business_router.post("/v1/{team_slug}/skills/business/create_application", **skills_business_endpoints["create_application"])
@limiter.limit("20/minute")
async def skill_business_create_application(
    request: Request,
    parameters: BusinessCreateApplicationInput,
    team_slug: str = Path(..., **input_parameter_descriptions["team_slug"]),
    token: str = Depends(get_credentials)
) -> BusinessCreateApplicationOutput:
    await validate_permissions(
        endpoint="/skills/business/create_application",
        team_slug=team_slug,
        user_api_token=token
    )
    return await skill_business_create_application_processing(
        requirements=parameters.requirements,
        recommendations=parameters.recommendations
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


##################################
######### Billing ################
##################################

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



##################################
######### Server #################
##################################

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
    user: User = await get_user_processing(
        team_slug=team_slug,
        api_token=token,
        username=username,
        user_access=user_access,
        fields=fields
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



# Include the routers in your FastAPI application
app.include_router(files_router,                    tags=["Files"])
app.include_router(mates_router,                    tags=["Mates"])
app.include_router(skills_router,                   tags=["Skills"])
app.include_router(skills_ai_router,                tags=["Skills | AI"])
app.include_router(skills_messages_router,          tags=["Skills | Messages"])
app.include_router(skills_code_router,              tags=["Skills | Code"])
app.include_router(skills_finance_router,           tags=["Skills | Finance"])
app.include_router(skills_docs_router,              tags=["Skills | Docs"])
app.include_router(skills_files_router,             tags=["Skills | Files"])
app.include_router(skills_books_router,             tags=["Skills | Books"])
app.include_router(skills_videos_router,            tags=["Skills | Videos"])
app.include_router(skills_photos_router,            tags=["Skills | Photos"])
app.include_router(skills_web_router,               tags=["Skills | Web"])
app.include_router(skills_business_router,          tags=["Skills | Business"])
app.include_router(software_router,                 tags=["software"])
app.include_router(workflows_router,                tags=["Workflows"])
app.include_router(tasks_router,                    tags=["Tasks"])
app.include_router(billing_router,                  tags=["Billing"])
app.include_router(server_router,                   tags=["Server"])
app.include_router(teams_router,                    tags=["Teams"])
app.include_router(users_router,                    tags=["Users"])