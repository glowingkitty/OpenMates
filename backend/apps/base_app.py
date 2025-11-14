# backend/apps/base_app.py
#
# This module defines the BaseApp class, which serves as a foundational
# class for all specialized applications (e.g., AIApp, WebApp).
# It handles common functionalities like loading and validating app.yml metadata.

import yaml
import os
import logging
from typing import Dict, Any, List, Optional, Union
from pydantic import Field, BaseModel
from fastapi import FastAPI, HTTPException, Depends, Request, Body
from fastapi.requests import Request
import httpx
import importlib
import json
from celery import Celery
from kombu import Queue
from urllib.parse import quote

from backend.shared.python_schemas.app_metadata_schemas import (
    AppYAML,
    IconColorGradient,
    AppPricing,
    AppSkillDefinition,
    AppFocusDefinition,
    AppMemoryFieldDefinition
)
from backend.core.api.app.utils.internal_auth import verify_internal_token
from backend.core.api.app.services.translations import TranslationService

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
                module_path, class_name = skill_def.class_path.rsplit('.', 1)
                module = importlib.import_module(module_path)
                skill_class_attr = getattr(module, class_name)

                if not isinstance(skill_class_attr, type):
                    logger.error(f"Skill '{skill_def.id}' class_path '{skill_def.class_path}' does not point to a class. Skipping.")
                    continue

                @self.fastapi_app.post(f"/skills/{skill_def.id}", tags=["Skills"], name=f"execute_skill_{skill_def.id}")
                async def _dynamic_skill_executor(request: Request):
                    """
                    Dynamic skill executor endpoint.
                    Manually parses request body as JSON to bypass FastAPI validation.
                    This allows us to dynamically validate against the skill's request model.
                    """
                    # Capture skill_def in closure to avoid late binding issues
                    skill_definition = skill_def
                    
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
                        
                        skill_instance = skill_class_attr(
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
                            
                            # Look for a Pydantic BaseModel parameter (excluding self)
                            request_model = None
                            for param_name, param in params.items():
                                if param_name == 'self':
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
                                
                                # Check if it's a Pydantic BaseModel
                                if (inspect.isclass(param_type) and 
                                    issubclass(param_type, PydanticBaseModel)):
                                    request_model = param_type
                                    logger.debug(f"Found Pydantic request model '{param_type.__name__}' for skill '{skill_definition.id}'")
                                    break
                            
                            if request_model:
                                # Instantiate the Pydantic model from request body
                                try:
                                    logger.debug(f"Instantiating {request_model.__name__} from request body for skill '{skill_definition.id}'")
                                    request_obj = request_model(**request_body)
                                    response = await skill_instance.execute(request_obj)
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
                                logger.debug(f"No Pydantic model found for skill '{skill_definition.id}', using kwargs")
                                response = await skill_instance.execute(**request_body)
                            
                            return response
                        else:
                            raise HTTPException(status_code=500, detail=f"Skill '{skill_definition.id}' is not executable.")
                    except HTTPException:
                        raise
                    except Exception as exec_e:
                        logger.error(f"Error executing skill '{skill_definition.id}': {exec_e}", exc_info=True)
                        raise HTTPException(status_code=500, detail=f"Error executing skill '{skill_definition.id}': {str(exec_e)}")

            except Exception as e:
                logger.error(f"Unexpected error registering skill route for '{skill_def.id}': {e}", exc_info=True)

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
            if not self.is_valid or not self.app_config:
                raise HTTPException(status_code=500, detail="App configuration is not loaded or invalid.")
            return self.app_config

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
            if not skill_def.class_path:
                all_paths_valid = False
                continue
            try:
                module_path, class_name = skill_def.class_path.rsplit('.', 1)
                module = importlib.import_module(module_path)
                if not hasattr(module, class_name):
                    all_paths_valid = False
            except Exception:
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
    import uvicorn
    import asyncio

    async def run_test_app():
        # Dummy app setup for testing
        pass

    if __name__ == '__main__':
        logging.basicConfig(level=logging.INFO)
        asyncio.run(run_test_app())
