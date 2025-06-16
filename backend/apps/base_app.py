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
from fastapi import FastAPI, HTTPException, Depends, Request
import httpx
import importlib
from celery import Celery

from backend.shared.python_schemas.app_metadata_schemas import (
    AppYAML,
    IconColorGradient,
    AppPricing,
    AppSkillDefinition,
    AppFocusDefinition,
    AppMemoryFieldDefinition
)
from backend.core.api.app.utils.internal_auth import verify_internal_token

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

        self._load_and_validate_app_yml()

        if self.app_config:
            if self.app_config.id:
                self.app_id = self.app_config.id
            else:
                self.app_config.id = self.app_id
        
        logger.info(f"BaseApp initialized. Effective App ID: {self.app_id}")

        self.fastapi_app = FastAPI(
            title=self.name or self.app_id or "BaseApp",
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
                    logger.error(f"Skill '{skill_def.name}' class_path '{skill_def.class_path}' does not point to a class. Skipping.")
                    continue

                @self.fastapi_app.post(f"/skills/{skill_def.id}", tags=["Skills"], name=f"execute_skill_{skill_def.id}")
                async def _dynamic_skill_executor(skill_definition: AppSkillDefinition = skill_def, request_body: Dict[str, Any] = Depends(lambda: {})):
                    try:
                        skill_instance = skill_class_attr(
                            app=self,
                            app_id=self.id,
                            skill_id=skill_definition.id,
                            skill_name=skill_definition.name,
                            skill_description=skill_definition.description,
                            stage=skill_definition.stage,
                            full_model_reference=skill_definition.full_model_reference,
                            pricing_config=skill_definition.pricing.model_dump(exclude_none=True) if skill_definition.pricing else None,
                            celery_producer=self.celery_producer,
                            skill_operational_defaults=skill_definition.default_config
                        )
                    except Exception as init_e:
                        raise HTTPException(status_code=500, detail=f"Error initializing skill '{skill_definition.name}'.")

                    try:
                        if hasattr(skill_instance, 'execute') and callable(skill_instance.execute):
                            if isinstance(request_body, dict):
                                response = await skill_instance.execute(**request_body)
                            else:
                                response = await skill_instance.execute(request_body)
                            return response
                        else:
                            raise HTTPException(status_code=500, detail=f"Skill '{skill_definition.name}' is not executable.")
                    except HTTPException:
                        raise
                    except Exception as exec_e:
                        raise HTTPException(status_code=500, detail=f"Error executing skill '{skill_definition.name}'.")

            except Exception as e:
                logger.error(f"Unexpected error registering skill route for '{skill_def.name}': {e}", exc_info=True)

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
        broker_url = os.getenv('CELERY_BROKER_URL', 'redis://default:password@cache:6379/0')
        producer = Celery(f'{self.app_id}_producer', broker=broker_url)
        producer.conf.update(task_serializer='json', accept_content=['json'], timezone='UTC', enable_utc=True)
        return producer

    def _register_default_routes(self):
        @self.fastapi_app.get("/metadata", tags=["App Info"], response_model=AppYAML)
        async def get_app_metadata():
            if not self.is_valid or not self.app_config:
                raise HTTPException(status_code=500, detail="App configuration is not loaded or invalid.")
            return self.app_config

        @self.fastapi_app.get("/health", tags=["App Info"])
        async def health_check():
            return {"status": "ok", "app_id": self.id, "app_name": self.name}

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
    def name(self) -> Optional[str]:
        return self.app_config.name if self.app_config else None

    @property
    def description(self) -> Optional[str]:
        return self.app_config.description if self.app_config else None

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

if __name__ == '__main__':
    import uvicorn
    import asyncio

    async def run_test_app():
        # Dummy app setup for testing
        pass

    if __name__ == '__main__':
        logging.basicConfig(level=logging.INFO)
        asyncio.run(run_test_app())
