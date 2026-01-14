# backend/apps/base_app.py
#
# This module defines the BaseApp class, which serves as a foundational
# class for all specialized applications (e.g., AIApp, WebApp).
# It handles common functionalities like loading and validating app.yml metadata.

import yaml
import os
import logging
from typing import Dict, Any, List, Optional, Union, get_origin, get_args
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request
import httpx
import importlib
import json
from celery import Celery
from kombu import Queue
from urllib.parse import quote

from backend.shared.python_schemas.app_metadata_schemas import (
    AppYAML,
    AppSkillDefinition,
    AppFocusDefinition,
    AppMemoryFieldDefinition
)
from backend.core.api.app.services.translations import TranslationService
from backend.apps.ai.processing.rate_limiting import RateLimitScheduledException

logger = logging.getLogger(__name__)

INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_TIMEOUT = 10
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")

class CreditChargePayload(BaseModel):
    user_id: str
    user_id_hash: str
    credits: int
    skill_id: str
    app_id: str
    idempotency_key: Optional[str] = None
    usage_details: Optional[Dict[str, Any]] = None

class BaseApp:
    def __init__(self, app_dir: str, app_yml_filename: str = "app.yml", app_port: int = 8001):
        self.app_dir = app_dir
        self.app_yml_path = os.path.join(self.app_dir, app_yml_filename)
        self.app_config: Optional[AppYAML] = None
        self.app_id: str = os.path.basename(self.app_dir.rstrip(os.sep))
        self.is_valid = False
        self.port = app_port
        self.celery_producer = self._initialize_celery_producer()
        
        # Initialize translation service to load translations from YAML files
        # This ensures translations are ready for skill initialization and metadata endpoint
        try:
            self.translation_service = TranslationService()
            logger.info(f"Translation service initialized for app '{self.app_id}'")
        except Exception as e:
            logger.warning(f"Failed to initialize translation service for app '{self.app_id}': {e}. Translations may not be available.")
            self.translation_service = None

        self._load_and_validate_app_yml()

        if self.app_config:
            if self.app_config.id:
                self.app_id = self.app_config.id
            else:
                self.app_config.id = self.app_id
        
        logger.info(f"BaseApp initialized. Effective App ID: {self.app_id}")

        self.fastapi_app = FastAPI(
            title=self.name_translation_key or self.app_id or "BaseApp",
            description=self.description or "A base application.",
            version="0.1.0"
        )
        self._register_default_routes()
        self._register_skill_routes()

    def _register_skill_routes(self):
        if not self.is_valid or not self.app_config or not self.app_config.skills:
            return

        for skill_def in self.app_config.skills:
            try:
                # Skip skills without a class_path (e.g., planning-stage skills)
                if not skill_def.class_path:
                    logger.debug(f"Skill '{skill_def.id}' has no class_path, skipping route registration (likely a planning-stage skill)")
                    continue
                
                module_path, class_name = skill_def.class_path.rsplit('.', 1)
                module = importlib.import_module(module_path)
                skill_class_attr = getattr(module, class_name)

                if not isinstance(skill_class_attr, type):
                    logger.error(f"Skill '{skill_def.id}' class_path '{skill_def.class_path}' does not point to a class. Skipping.")
                    continue

                # CRITICAL: Capture all values as default parameters to avoid Python closure late-binding issues
                # Python closures capture variables by reference, not by value. Using default parameters
                # forces evaluation at function definition time, ensuring each route uses the correct skill.
                skill_id_for_route = skill_def.id
                captured_skill_def = skill_def
                captured_skill_class = skill_class_attr

                @self.fastapi_app.post(f"/skills/{skill_id_for_route}", tags=["Skills"], name=f"execute_skill_{skill_id_for_route}")
                async def _dynamic_skill_executor(
                    request: Request,
                    skill_definition=captured_skill_def,
                    captured_class=captured_skill_class
                ):
                    """
                    Dynamic skill executor endpoint.
                    Supports both internal format and OpenAI-compatible format.
                    Automatically detects the request format based on the skill's execute method signature.
                    """
                    return await self._execute_skill_route(request, skill_definition, captured_class)

            except Exception as e:
                logger.error(f"Unexpected error registering skill route for '{skill_def.id}': {e}", exc_info=True)

    async def _execute_skill_route(self, request: Request, skill_definition, captured_class):
        """
        Dynamic skill executor endpoint.
        Manually parses request body as JSON to bypass FastAPI validation.
        This allows us to dynamically validate against the skill's request model.
        """
        # Use the captured values from default parameters (evaluated at function definition time)

        logger.info(f"[SKILL_ROUTE] Received request for skill '{skill_definition.id}' at /skills/{skill_definition.id}")

        try:
            # Manually read and parse the request body to bypass FastAPI validation
            try:
                body_bytes = await request.body()
                if not body_bytes:
                    raise HTTPException(status_code=400, detail="Request body is required")

                request_body = json.loads(body_bytes.decode('utf-8'))
                if not isinstance(request_body, dict):
                    raise HTTPException(status_code=400, detail="Request body must be a JSON object")

                logger.debug(f"[SKILL_ROUTE] Parsed request body with keys: {list(request_body.keys())}")
            except json.JSONDecodeError as e:
                logger.error(f"[SKILL_ROUTE] Invalid JSON in request body: {e}")
                raise HTTPException(status_code=400, detail=f"Invalid JSON in request body: {str(e)}")
            except UnicodeDecodeError as e:
                logger.error(f"[SKILL_ROUTE] Invalid encoding in request body: {e}")
                raise HTTPException(status_code=400, detail="Invalid encoding in request body")

            logger.debug(f"Executing skill '{skill_definition.id}' with request body: {list(request_body.keys())}")

            # Extract metadata fields (_chat_id, _message_id) from request body if present
            # These are used for linking usage entries to chat sessions
            # We'll remove them from request_body before passing to skill to avoid validation errors
            chat_id = request_body.get("_chat_id")
            message_id = request_body.get("_message_id")

            # Initialize skill instance
            # Extract full_model_reference from default_config if present, otherwise use None
            # Note: AppSkillDefinition doesn't have full_model_reference field,
            # but BaseSkill.__init__ accepts it as an optional parameter
            full_model_ref = None
            if skill_definition.default_config and isinstance(skill_definition.default_config, dict):
                full_model_ref = skill_definition.default_config.get('full_model_reference')

            # Resolve translation keys to actual translated strings for BaseSkill initialization
            # BaseSkill expects skill_name and skill_description as strings, not translation keys
            skill_name = self._resolve_translation_key(skill_definition.name_translation_key)
            skill_description = self._resolve_translation_key(skill_definition.description_translation_key)

            skill_instance = captured_class(
                app=self,
                app_id=self.id,
                skill_id=skill_definition.id,
                skill_name=skill_name,
                skill_description=skill_description,
                stage=skill_definition.stage,
                full_model_reference=full_model_ref,
                pricing_config=skill_definition.pricing.model_dump(exclude_none=True) if skill_definition.pricing else None,
                celery_producer=self.celery_producer,
                skill_operational_defaults=skill_definition.default_config
            )

            # Set execution context (chat_id, message_id) on skill instance
            # This allows skills to use these values when recording usage via record_skill_usage
            if chat_id:
                skill_instance._current_chat_id = chat_id
            if message_id:
                skill_instance._current_message_id = message_id
        except HTTPException:
            raise
        except Exception as init_e:
            logger.error(f"Error initializing skill '{skill_definition.id}': {init_e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error initializing skill '{skill_definition.id}': {str(init_e)}")

        try:
            # Execute the skill - check if execute method expects a Pydantic model or keyword arguments
            if hasattr(skill_instance, 'execute') and callable(skill_instance.execute):
                import inspect
                from pydantic import BaseModel as PydanticBaseModel

                sig = inspect.signature(skill_instance.execute)
                params = sig.parameters

                # Look for a Pydantic BaseModel parameter (excluding self and params with defaults)
                # Also handle Union types that may contain Pydantic models
                # 
                # IMPORTANT: Skip parameters with default values (e.g., secrets_manager: Optional[SecretsManager] = None)
                # These are optional dependency-injected parameters, not request body fields.
                # Without this check, Optional[SecretsManager] would be detected as Union[SecretsManager, None]
                # and the code would incorrectly try to validate the request body against SecretsManager.
                request_model = None
                union_types = None
                for param_name, param in params.items():
                    if param_name == 'self':
                        continue
                    
                    # Skip parameters with default values - these are not request body fields
                    # They are typically dependency-injected (e.g., secrets_manager, cache_service)
                    if param.default is not inspect.Parameter.empty:
                        logger.debug(f"Skipping parameter '{param_name}' with default value for skill '{skill_definition.id}'")
                        continue

                    param_type = param.annotation

                    # Handle string annotations (forward references) by resolving them
                    if isinstance(param_type, str):
                        # Try to resolve the annotation from the module
                        try:
                            module = inspect.getmodule(skill_instance)
                            if module:
                                param_type = getattr(module, param_type, None)
                        except Exception:
                            pass

                    # Check if it's a Union type (e.g., Union[AskSkillRequest, OpenAICompletionRequest])
                    if param_type is not None:
                        origin = get_origin(param_type)
                        if origin is Union:
                            # Extract the types from the Union
                            union_types = get_args(param_type)
                            logger.debug(f"Found Union type for skill '{skill_definition.id}' with types: {[t.__name__ if hasattr(t, '__name__') else str(t) for t in union_types]}")
                            # Check if any of the Union types are Pydantic models
                            pydantic_types = [t for t in union_types if inspect.isclass(t) and issubclass(t, PydanticBaseModel)]
                            if pydantic_types:
                                union_types = pydantic_types
                                break

                    # Check if it's a Pydantic BaseModel
                    if (inspect.isclass(param_type) and
                        issubclass(param_type, PydanticBaseModel)):
                        request_model = param_type
                        logger.debug(f"Found Pydantic request model '{param_type.__name__}' for skill '{skill_definition.id}'")
                        break

                if request_model or union_types:
                    # Remove internal metadata fields before instantiating Pydantic model
                    # EXCEPT for context fields (_user_id, _api_key_name, _external_request) which are
                    # used by skills like AI ask to identify the authenticated user from external API requests
                    # These context fields are injected by the external API handler and need to be preserved
                    context_fields = {'_user_id', '_api_key_name', '_external_request'}
                    clean_request_body = {
                        k: v for k, v in request_body.items() 
                        if not k.startswith("_") or k in context_fields
                    }

                    # Instantiate the Pydantic model from request body
                    try:
                        request_obj = None
                        validation_errors = []
                        
                        if union_types:
                            # Try each type in the Union until one succeeds
                            # Order matters: try types in the order they appear in the Union
                            for model_type in union_types:
                                try:
                                    logger.debug(f"Trying to instantiate {model_type.__name__} from request body for skill '{skill_definition.id}'")
                                    request_obj = model_type(**clean_request_body)
                                    logger.debug(f"Successfully instantiated {model_type.__name__} for skill '{skill_definition.id}'")
                                    break
                                except Exception as e:
                                    # Store the error but continue trying other types
                                    validation_errors.append(f"{model_type.__name__}: {str(e)}")
                                    logger.debug(f"Failed to instantiate {model_type.__name__}: {e}")
                                    continue
                            
                            if request_obj is None:
                                # None of the Union types matched
                                error_msg = f"Request body does not match any expected format. Tried: {', '.join([t.__name__ for t in union_types])}"
                                logger.error(f"{error_msg}. Errors: {'; '.join(validation_errors)}")
                                raise HTTPException(
                                    status_code=422,
                                    detail=error_msg
                                )
                        else:
                            # Single Pydantic model
                            logger.debug(f"Instantiating {request_model.__name__} from request body for skill '{skill_definition.id}'")
                            request_obj = request_model(**clean_request_body)

                        # Check if the execute method expects the Pydantic model or just the requests list
                        # Most skills expect requests: List[Dict[str, Any]] directly, not the Pydantic wrapper
                        # Reuse the signature we already have
                        first_param = None
                        for param_name, param in params.items():
                            if param_name != 'self' and param_name != 'secrets_manager':
                                first_param = param
                                break

                        # If execute() expects a list (requests), extract it from the Pydantic model
                        # Otherwise pass the Pydantic model directly
                        if first_param and 'List' in str(first_param.annotation):
                            # Execute method expects a list - extract requests from Pydantic model
                            if hasattr(request_obj, 'requests'):
                                response = await skill_instance.execute(request_obj.requests, secrets_manager=None)
                            else:
                                # Fallback: try to pass the model and let the skill handle it
                                response = await skill_instance.execute(request_obj)
                        else:
                            # Execute method expects the Pydantic model directly (or Union type)
                            response = await skill_instance.execute(request_obj)
                    except HTTPException:
                        raise
                    except Exception as validation_error:
                        logger.error(f"Validation error for skill '{skill_definition.id}': {validation_error}", exc_info=True)
                        # Format Pydantic validation errors properly
                        if hasattr(validation_error, 'errors'):
                            # Pydantic ValidationError
                            error_details = validation_error.errors()
                        else:
                            error_details = [{"msg": str(validation_error)}]
                        raise HTTPException(
                            status_code=422,
                            detail=error_details
                        )
                else:
                    # No Pydantic model found - try unpacking as keyword arguments
                    # Remove internal metadata fields but preserve context fields for API authentication
                    context_fields = {'_user_id', '_api_key_name', '_external_request'}
                    clean_request_body = {
                        k: v for k, v in request_body.items() 
                        if not k.startswith("_") or k in context_fields
                    }
                    logger.debug(f"No Pydantic model found for skill '{skill_definition.id}', using kwargs")
                    response = await skill_instance.execute(**clean_request_body)

                # Ensure response is properly serialized before returning
                # If it's a Pydantic model, convert to dict to ensure proper JSON serialization
                # This fixes issues where FastAPI might not serialize the model correctly
                # CRITICAL: FastAPI's automatic Pydantic serialization can sometimes fail for complex models
                # Explicitly converting to dict ensures the response is properly serialized to JSON
                if isinstance(response, BaseModel):
                    response_dict = response.model_dump(exclude_none=False)
                    logger.debug(
                        f"Converting Pydantic response to dict for skill '{skill_definition.id}': "
                        f"keys={list(response_dict.keys())}, "
                        f"documentation_length={len(response_dict.get('documentation', '')) if isinstance(response_dict.get('documentation'), str) else 0}, "
                        f"documentation_type={type(response_dict.get('documentation')).__name__}"
                    )
                    return response_dict
                
                return response
            else:
                raise HTTPException(status_code=500, detail=f"Skill '{skill_definition.id}' is not executable.")
        except RateLimitScheduledException as rate_limit_e:
            # Rate limit hit - task was scheduled via Celery
            # Return task_id response so client knows to wait for followup
            logger.info(
                f"Skill '{skill_definition.id}' execution scheduled via Celery due to rate limit. "
                f"Task ID: {rate_limit_e.task_id}, Wait time: {rate_limit_e.wait_time:.2f}s"
            )
            return {
                "task_id": rate_limit_e.task_id,
                "status": "scheduled",
                "message": "Request scheduled due to rate limit. I'll let you know once completed.",
                "wait_time_seconds": rate_limit_e.wait_time
            }
        except HTTPException:
            raise
        except Exception as exec_e:
            logger.error(f"Error executing skill '{skill_definition.id}': {exec_e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error executing skill '{skill_definition.id}': {str(exec_e)}")

    async def _make_internal_api_request(
        self,
        method: str,
        endpoint: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if INTERNAL_API_SHARED_TOKEN:
            headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
        else:
            logger.warning("INTERNAL_API_SHARED_TOKEN not set. Internal API calls will be unauthenticated.")
        
        url = f"{INTERNAL_API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"

        async with httpx.AsyncClient(timeout=INTERNAL_API_TIMEOUT) as client:
            try:
                response = await client.request(method, url, json=payload, params=params, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                raise HTTPException(status_code=e.response.status_code, detail=f"Internal API error: {e.response.text}")
            except httpx.RequestError as e:
                raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Unexpected internal error: {str(e)}")

    def _initialize_celery_producer(self) -> Celery:
        """
        Initialize Celery producer for dispatching tasks.
        Uses DRAGONFLY_PASSWORD from environment, matching celery_config.py pattern.
        Declares queues to match worker configuration so tasks can be routed correctly.
        """
        # Get Redis password from environment variable and ensure it's URL-encoded
        raw_password = os.getenv('DRAGONFLY_PASSWORD')
        encoded_password = quote(raw_password) if raw_password else ''
        
        # Build broker URL with proper authentication, matching celery_config.py
        broker_url = os.getenv('CELERY_BROKER_URL', f'redis://default:{encoded_password}@cache:6379/0')
        
        logger.debug(f"Initializing Celery producer for app '{self.app_id}' with broker URL: redis://default:***@cache:6379/0")
        
        producer = Celery(f'{self.app_id}_producer', broker=broker_url)
        
        # Declare queues that match the worker configuration
        # This ensures tasks sent with explicit queue names can be routed correctly
        # Queues must match those declared in celery_config.py
        app_queues = (
            Queue('app_ai', exchange='app_ai', routing_key='app_ai'),
            Queue('app_web', exchange='app_web', routing_key='app_web'),
        )
        
        producer.conf.update(
            task_serializer='json',
            accept_content=['json'],
            timezone='UTC',
            enable_utc=True,
            task_queues=app_queues,  # Declare queues so send_task with queue parameter works
        )
        
        return producer

    def _register_default_routes(self):
        @self.fastapi_app.get("/metadata", tags=["App Info"], response_model=AppYAML)
        async def get_app_metadata():
            # Debug logging to help diagnose metadata endpoint issues
            logger.info(f"Metadata endpoint called for app '{self.app_id}'. is_valid={self.is_valid}, app_config={'exists' if self.app_config else 'None'}")
            if not self.is_valid:
                logger.error(f"Metadata endpoint failed: is_valid is False for app '{self.app_id}'")
                raise HTTPException(status_code=500, detail="App configuration is not loaded or invalid.")
            if not self.app_config:
                logger.error(f"Metadata endpoint failed: app_config is None for app '{self.app_id}'")
                raise HTTPException(status_code=500, detail="App configuration is not loaded or invalid.")
            try:
                # Try to return the config - if serialization fails, we'll catch it
                return self.app_config
            except Exception as e:
                logger.error(f"Metadata endpoint serialization error for app '{self.app_id}': {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Error serializing app configuration: {str(e)}")

        @self.fastapi_app.get("/health", tags=["App Info"])
        async def health_check():
            return {"status": "ok", "app_id": self.id, "name_translation_key": self.name_translation_key}

    async def charge_user_credits(
        self,
        user_id: str,
        user_id_hash: str,
        credits_to_charge: int,
        skill_id: str,
        app_id: str,
        idempotency_key: Optional[str] = None,
        usage_details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not self.is_valid:
            raise HTTPException(status_code=500, detail="App is not properly configured to charge credits.")

        if credits_to_charge <= 0:
            return {"status": "skipped", "reason": "Non-positive credits"}

        charge_payload = {
            "user_id": user_id,
            "user_id_hash": user_id_hash,
            "credits": credits_to_charge,
            "skill_id": skill_id,
            "app_id": app_id,
            "idempotency_key": idempotency_key or f"{user_id_hash}-{app_id}-{skill_id}-{os.urandom(8).hex()}",
            "usage_details": usage_details or {}
        }
        
        logger.info(f"Requesting credit charge for user {user_id}: {credits_to_charge} credits for skill {skill_id} in app {app_id}.")
        try:
            response = await self._make_internal_api_request(
                "POST",
                "/internal/billing/charge",
                payload=charge_payload
            )
            return response
        except HTTPException as e:
            logger.error(f"Failed to charge credits for user {user_id} via internal API: {e.detail}", exc_info=True)
            raise e
        except Exception as e:
            logger.error(f"Unexpected error during credit charge request for user {user_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Unexpected error during credit charge: {str(e)}")

    def _load_and_validate_app_yml(self):
        if not os.path.exists(self.app_yml_path):
            logger.error(f"App configuration file not found: {self.app_yml_path}")
            return

        try:
            with open(self.app_yml_path, 'r') as f:
                raw_config = yaml.safe_load(f)
            
            if not raw_config:
                logger.error(f"App configuration file is empty: {self.app_yml_path}")
                return

            def _strip_trailing_whitespace(data: Any) -> Any:
                if isinstance(data, dict):
                    return {k: _strip_trailing_whitespace(v) for k, v in data.items()}
                elif isinstance(data, list):
                    return [_strip_trailing_whitespace(item) for item in data]
                elif isinstance(data, str):
                    return data.rstrip()
                return data

            processed_config = _strip_trailing_whitespace(raw_config)
            self.app_config = AppYAML(**processed_config)
            self.is_valid = True
            self._validate_skill_class_paths()

        except Exception as e:
            logger.error(f"Error validating app configuration from {self.app_yml_path}: {e}", exc_info=True)
            self.is_valid = False

    def _validate_skill_class_paths(self):
        if not self.app_config or not self.is_valid:
            return

        all_paths_valid = True
        for skill_def in self.app_config.skills:
            # Skip planning stage skills - they don't need class_path yet
            if skill_def.stage == "planning":
                continue
            # For development/production skills, class_path is required
            if not skill_def.class_path:
                logger.warning(f"Skill '{skill_def.id}' has stage '{skill_def.stage}' but no class_path defined")
                all_paths_valid = False
                continue
            try:
                module_path, class_name = skill_def.class_path.strip().rsplit('.', 1)
                module = importlib.import_module(module_path)
                if not hasattr(module, class_name):
                    logger.warning(f"Skill '{skill_def.id}' class_path '{skill_def.class_path}' - class '{class_name}' not found in module")
                    all_paths_valid = False
            except Exception as e:
                logger.warning(f"Skill '{skill_def.id}' class_path '{skill_def.class_path}' failed to import: {e}")
                all_paths_valid = False
        
        if not all_paths_valid:
            self.is_valid = False

    @property
    def id(self) -> Optional[str]:
        return self.app_id

    @property
    def name_translation_key(self) -> Optional[str]:
        return self.app_config.name_translation_key if self.app_config else None

    @property
    def description(self) -> Optional[str]:
        """Resolve description from description_translation_key.
        
        Since we removed backwards compatibility, description_translation_key is required.
        This property resolves the translation key to the actual translated string.
        """
        if not self.app_config or not self.app_config.description_translation_key:
            return None
        
        # Resolve the translation key to get the actual description string
        translation_key = self.app_config.description_translation_key
        # Normalize translation key: ensure it has "apps." prefix if needed
        if not translation_key.startswith("apps."):
            translation_key = f"apps.{translation_key}"
        
        return self._resolve_translation_key(translation_key)

    @property
    def skills(self) -> List[AppSkillDefinition]:
        return self.app_config.skills if self.app_config else []

    @property
    def focuses(self) -> List[AppFocusDefinition]:
        return self.app_config.focuses if self.app_config else []
    
    @property
    def focus_modes(self) -> List[AppFocusDefinition]:
        return self.focuses

    @property
    def memory_fields(self) -> List[AppMemoryFieldDefinition]:
        return self.app_config.memory_fields if self.app_config else []
    
    @property
    def memory(self) -> List[AppMemoryFieldDefinition]:
        return self.memory_fields

    def get_skill_by_id(self, skill_id: str) -> Optional[AppSkillDefinition]:
        for skill in self.skills:
            if skill.id == skill_id:
                return skill
        return None

    def get_focus_by_id(self, focus_id: str) -> Optional[AppFocusDefinition]:
        for focus in self.focuses:
            if focus.id == focus_id:
                return focus
        return None
    
    def get_memory_field_by_id(self, memory_field_id: str) -> Optional[AppMemoryFieldDefinition]:
        for mem_field in self.memory_fields:
            if mem_field.id == memory_field_id:
                return mem_field
        return None
    
    def _resolve_translation_key(self, translation_key: str, lang: str = "en") -> str:
        """
        Resolve a translation key to its translated string value.
        
        Args:
            translation_key: The translation key (e.g., "app_translations.web.skills.search.name")
            lang: Language code (default: "en")
            
        Returns:
            Translated string, or the translation key itself if translation service is unavailable or key not found
        """
        if not self.translation_service:
            logger.warning(f"Translation service not available, returning key as-is: {translation_key}")
            return translation_key
        
        try:
            translated = self.translation_service.get_nested_translation(translation_key, lang=lang)
            return translated
        except Exception as e:
            logger.warning(f"Failed to resolve translation key '{translation_key}': {e}. Returning key as-is.")
            return translation_key

if __name__ == '__main__':
    import asyncio

    async def run_test_app():
        # Dummy app setup for testing
        pass

    if __name__ == '__main__':
        logging.basicConfig(level=logging.INFO)
        asyncio.run(run_test_app())
