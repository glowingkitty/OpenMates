# backend/apps/base_app.py
#
# This module defines the BaseApp class, which serves as a foundational
# class for all specialized applications (e.g., AIApp, WebApp).
# It handles common functionalities like loading and validating app.yml metadata.

import yaml
import os
import logging
from typing import Dict, Any, List, Optional, Union
from pydantic import Field # BaseModel, validator, constr are likely from the imported schemas now
from fastapi import FastAPI, HTTPException, Depends
import httpx # For making internal API calls
import importlib
from celery import Celery # For sending tasks

# Import Pydantic models from the shared location
from backend.shared.python_schemas.app_metadata_schemas import (
    AppYAML,
    IconColorGradient, # Ensure this and other necessary models are exported if used directly
    AppPricing,
    AppSkillDefinition,
    AppFocusDefinition,
    AppMemoryFieldDefinition
)

logger = logging.getLogger(__name__)

# Configuration for internal API calls
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000") # Assuming 'api' is the service name in Docker
INTERNAL_API_TIMEOUT = 10  # seconds
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN") # For authenticating calls to the main API


# --- BaseApp Class ---

class BaseApp:
    """
    Base class for all applications.
    Handles loading app.yml, validation, and provides access to app metadata.
    """
    def __init__(self, app_dir: str, app_yml_filename: str = "app.yml", app_port: int = 8001): # Added app_port with a default
        """
        Initializes the BaseApp.

        Args:
            app_dir (str): The root directory of the application.
            app_yml_filename (str): The name of the app's YAML configuration file.
            app_port (int): Port on which the app's FastAPI server will run.
        """
        self.app_dir = app_dir
        self.app_yml_path = os.path.join(self.app_dir, app_yml_filename)
        self.app_config: Optional[AppYAML] = None
        # Determine initial app_id from app_dir. This will be used for the Celery producer name.
        # It can be overridden by app.yml's 'id' field later for other metadata purposes.
        self.app_id: str = os.path.basename(self.app_dir.rstrip(os.sep))
        self.is_valid = False
        self.port = app_port # Store the port
        self.celery_producer = self._initialize_celery_producer()

        self._load_and_validate_app_yml() # This now includes _validate_skill_class_paths

        # Update app_id if specified in app.yml, and ensure app_config.id is set.
        if self.app_config:
            if self.app_config.id:
                self.app_id = self.app_config.id # Override with ID from app.yml if present
            else:
                self.app_config.id = self.app_id # Ensure app_config.id matches derived/default app_id
        # If app_config is None (load failed), self.app_id remains the directory-derived one.
        
        logger.info(f"BaseApp initialized. Effective App ID: {self.app_id}")

        self.fastapi_app = FastAPI(
            title=self.name or self.app_id or "BaseApp", # Use app_id in title if name is not available
            description=self.description or "A base application.",
            version="0.1.0" # TODO: Get version from backend.core.api.app.yml or environment
        )
        self._register_default_routes()
        self._register_skill_routes() # New method to register skill endpoints

    def _register_skill_routes(self):
        """Dynamically registers routes for all skills defined in app.yml."""
        if not self.is_valid or not self.app_config or not self.app_config.skills:
            return

        for skill_def in self.app_config.skills:
            try:
                module_path, class_name = skill_def.class_path.rsplit('.', 1)
                module = importlib.import_module(module_path)
                skill_class_attr = getattr(module, class_name)

                if not isinstance(skill_class_attr, type): # Check if it's a class
                    logger.error(f"Skill '{skill_def.name}' class_path '{skill_def.class_path}' does not point to a class. Skipping route registration.")
                    continue

                # Dynamically create an endpoint for this skill
                # Assuming skills will have a POST endpoint for execution for now
                # The request and response models would ideally be dynamically determined or standardized
                @self.fastapi_app.post(f"/skills/{skill_def.id}", tags=["Skills"], name=f"execute_skill_{skill_def.id}")
                async def _dynamic_skill_executor(skill_definition: AppSkillDefinition = skill_def, request_body: Dict[str, Any] = Depends(lambda: {})): # Simplified request_body for now
                    # Instantiate the skill, passing the celery_producer
                    try:
                        # Pass the BaseApp instance (self) as 'app' to the skill constructor
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
                            # Pass skill-specific operational defaults if defined in app.yml
                            skill_operational_defaults=skill_definition.default_config
                        )
                    except Exception as init_e:
                        logger.error(f"Failed to initialize skill '{skill_definition.name}': {init_e}", exc_info=True)
                        raise HTTPException(status_code=500, detail=f"Error initializing skill '{skill_definition.name}'.")

                    # Execute the skill
                    # The actual signature of 'execute' and how request_body is passed might vary.
                    # This is a generic placeholder. Skills might need to define their own Pydantic request models.
                    try:
                        # If skill's execute method expects a Pydantic model, we'd need to parse request_body into it.
                        # For now, passing as kwargs if it's a dict.
                        if hasattr(skill_instance, 'execute') and callable(skill_instance.execute):
                            if isinstance(request_body, dict):
                                # This is a simplification. Real implementation might need to inspect
                                # the 'execute' method's signature or expect a specific request model.
                                response = await skill_instance.execute(**request_body)
                            else: # Or handle cases where request_body is not a dict or skill expects specific model
                                response = await skill_instance.execute(request_body) # Fallback
                            return response
                        else:
                            logger.error(f"Skill '{skill_definition.name}' does not have a callable 'execute' method.")
                            raise HTTPException(status_code=500, detail=f"Skill '{skill_definition.name}' is not executable.")
                    except HTTPException: # Re-raise HTTPExceptions from skill
                        raise
                    except Exception as exec_e:
                        logger.error(f"Error executing skill '{skill_definition.name}': {exec_e}", exc_info=True)
                        raise HTTPException(status_code=500, detail=f"Error executing skill '{skill_definition.name}'.")

                logger.info(f"Registered skill endpoint: POST /skills/{skill_def.id} for {skill_def.class_path}")

            except ImportError:
                logger.error(f"Failed to import module for skill '{skill_def.name}' with class_path '{skill_def.class_path}'. Skipping route registration.")
            except AttributeError:
                logger.error(f"Class '{class_name}' not found in module '{module_path}' for skill '{skill_def.name}'. Skipping route registration.")
            except Exception as e:
                logger.error(f"Unexpected error registering skill route for '{skill_def.name}': {e}", exc_info=True)


    async def _make_internal_api_request(
        self,
        method: str,
        endpoint: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Helper function to make requests to other internal APIs (e.g., the main API service).
        Uses INTERNAL_API_SHARED_TOKEN environment variable for authentication.
        """
        headers = {
            "Content-Type": "application/json",
        }
        if INTERNAL_API_SHARED_TOKEN:
            headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
        else:
            logger.warning(
                "INTERNAL_API_SHARED_TOKEN environment variable is not set for this app. "
                "Internal API calls to the main API service will be unauthenticated. "
                "This is a security risk and should be configured."
            )
        
        url = f"{INTERNAL_API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"

        async with httpx.AsyncClient(timeout=INTERNAL_API_TIMEOUT) as client:
            try:
                logger.debug(f"Making internal API call: {method} {url} with payload: {payload} and params: {params}")
                response = await client.request(method, url, json=payload, params=params, headers=headers)
                response.raise_for_status()  # Raises HTTPStatusError for 4xx/5xx responses
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error during internal API call to {url}: {e.response.status_code} - {e.response.text}")
                raise HTTPException(status_code=e.response.status_code, detail=f"Internal API error: {e.response.text}")
            except httpx.RequestError as e:
                logger.error(f"Request error during internal API call to {url}: {e}")
                raise HTTPException(status_code=503, detail=f"Service unavailable: Could not connect to internal API at {url}. Error: {str(e)}")
            except Exception as e:
                logger.error(f"Unexpected error during internal API call to {url}: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Unexpected internal error: {str(e)}")

    def _initialize_celery_producer(self) -> Celery:
        """Initializes and returns a minimal Celery client for sending tasks."""
        # Configuration is from environment variables, consistent with docker-compose for app services.
        broker_url = os.getenv('CELERY_BROKER_URL', os.getenv('DRAGONFLY_URL', 'redis://default:password@cache:6379/0'))
        producer = Celery(
            f'{self.app_id or "base_app"}_producer', # Unique name for this app's producer instance
            broker=broker_url,
            # No backend needed for a simple producer, tasks are processed by a separate worker.
            # No include needed as this instance only sends tasks.
        )
        producer.conf.update(
            task_serializer='json',
            accept_content=['json'],
            timezone='UTC',
            enable_utc=True,
        )
        logger.info(f"Celery producer initialized for app '{self.app_id or 'unknown'}' with broker: {broker_url}")
        return producer

    def _register_default_routes(self):
        """Registers default FastAPI routes for the app."""

        @self.fastapi_app.get("/metadata", tags=["App Info"], response_model=AppYAML)
        async def get_app_metadata():
            """
            Provides metadata about the application, including its ID, name,
            description, defined skills, focuses, and memory fields.
            This endpoint is used for service discovery by the main API.
            """
            if not self.is_valid or not self.app_config:
                raise HTTPException(status_code=500, detail="App configuration is not loaded or invalid.")
            return self.app_config

        # Placeholder for health check
        @self.fastapi_app.get("/health", tags=["App Info"])
        async def health_check():
            return {"status": "ok", "app_id": self.id, "app_name": self.name}

    async def charge_user_credits(
        self,
        user_id_hash: str,
        credits_to_charge: int,
        skill_id: str,
        app_id: str,
        idempotency_key: Optional[str] = None,
        usage_details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Requests the main API service to charge credits from a user.
        This is a placeholder and needs to be connected to an actual internal endpoint
        on the main API service.

        Args:
            user_id_hash (str): The hashed ID of the user to charge.
            credits_to_charge (int): The number of credits to deduct.
            skill_id (str): The ID of the skill that incurred the charge.
            app_id (str): The ID of the app to which the skill belongs.
            idempotency_key (Optional[str]): An optional key to ensure the charge operation is idempotent.
            usage_details (Optional[Dict[str, Any]]): Additional details about the usage for logging/auditing.

        Returns:
            Dict[str, Any]: The response from the main API's credit charging endpoint.
        """
        if not self.is_valid:
            raise HTTPException(status_code=500, detail="App is not properly configured to charge credits.")

        if credits_to_charge <= 0:
            # Or handle as a no-op, depending on desired behavior
            logger.warning(f"Attempted to charge non-positive credits ({credits_to_charge}) for user {user_id_hash}. Skipping.")
            return {"status": "skipped", "reason": "Non-positive credits"}

        charge_payload = {
            "user_id_hash": user_id_hash,
            "credits": credits_to_charge,
            "skill_id": skill_id,
            "app_id": app_id, # self.id could also be used if app_id is always self
            "idempotency_key": idempotency_key or f"{user_id_hash}-{app_id}-{skill_id}-{os.urandom(8).hex()}", # Generate one if not provided
            "usage_details": usage_details or {}
        }
        
        # This endpoint "/internal/billing/charge" needs to be defined in the main API service
        logger.info(f"Requesting credit charge for user {user_id_hash}: {credits_to_charge} credits for skill {skill_id} in app {app_id}.")
        try:
            # Make the actual internal API call
            logger.info(f"Requesting credit charge for user {user_id_hash} via internal API: {credits_to_charge} credits for skill {skill_id} in app {app_id}.")
            response = await self._make_internal_api_request(
                "POST",
                "/internal/billing/charge", # Ensure this endpoint is implemented in the main API
                payload=charge_payload
            )
            logger.info(f"Credit charge response from internal API: {response}")
            return response # Return the actual response from the API
        except HTTPException as e:
            # Re-raise the exception if it's from _make_internal_api_request
            logger.error(f"Failed to charge credits for user {user_id_hash} via internal API: {e.detail}", exc_info=True)
            raise e
        except Exception as e:
            logger.error(f"Unexpected error during credit charge request for user {user_id_hash}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Unexpected error during credit charge: {str(e)}")


    def _load_and_validate_app_yml(self):
        """Loads and validates the app.yml file."""
        if not os.path.exists(self.app_yml_path):
            logger.error(f"App configuration file not found: {self.app_yml_path}")
            return

        try:
            with open(self.app_yml_path, 'r') as f:
                raw_config = yaml.safe_load(f)
            
            if not raw_config:
                logger.error(f"App configuration file is empty: {self.app_yml_path}")
                return

            # Helper function to recursively strip trailing whitespace from string values
            def _strip_trailing_whitespace(data: Any) -> Any:
                if isinstance(data, dict):
                    return {k: _strip_trailing_whitespace(v) for k, v in data.items()}
                elif isinstance(data, list):
                    return [_strip_trailing_whitespace(item) for item in data]
                elif isinstance(data, str):
                    return data.rstrip() # Strips all trailing whitespace, including newlines
                return data

            processed_config = _strip_trailing_whitespace(raw_config)

            self.app_config = AppYAML(**processed_config)
            self.is_valid = True
            logger.info(f"Successfully loaded and validated app configuration for '{self.app_config.name}' from {self.app_yml_path}")

            # Further validation (e.g., skill class_path existence) can be added here or in subclasses.
            self._validate_skill_class_paths()

        except yaml.YAMLError as e:
            logger.error(f"Error parsing app YAML file {self.app_yml_path}: {e}")
        except Exception as e: # Catches Pydantic ValidationError and others
            logger.error(f"Error validating app configuration from {self.app_yml_path}: {e}", exc_info=True)
            self.app_config = None # Ensure config is None if validation fails
            self.is_valid = False # Explicitly set to false on validation error

    def _validate_skill_class_paths(self):
        """
        Validates if the skill class_paths defined in app.yml actually exist
        and can be imported. Sets self.is_valid to False if any path is invalid.
        This method is called by _load_and_validate_app_yml.
        """
        if not self.app_config or not self.is_valid: # self.is_valid might be False from Pydantic validation
            return

        all_paths_valid = True
        for skill_def in self.app_config.skills:
            if not skill_def.class_path:
                logger.error(f"Skill '{skill_def.name}' in app '{self.app_config.id}' is missing a class_path.")
                all_paths_valid = False
                continue

            try:
                module_path, class_name = skill_def.class_path.rsplit('.', 1)
                module = importlib.import_module(module_path)
                if not hasattr(module, class_name):
                    logger.error(
                        f"Skill class '{class_name}' not found in module '{module_path}' "
                        f"for skill '{skill_def.name}' in app '{self.app_config.id}'. "
                        f"Class path: {skill_def.class_path}"
                    )
                    all_paths_valid = False
                else:
                    # Further check: ensure the attribute is a class (and optionally, a subclass of BaseSkill)
                    skill_class_attr = getattr(module, class_name)
                    if not isinstance(skill_class_attr, type): # Check if it's a class
                        logger.error(
                            f"Attribute '{class_name}' in module '{module_path}' is not a class "
                            f"for skill '{skill_def.name}' in app '{self.app_config.id}'. "
                            f"Class path: {skill_def.class_path}"
                        )
                        all_paths_valid = False
                    else:
                        # from .base_skill import BaseSkill # Dynamic import to avoid circular dependency at module level
                        # if not issubclass(skill_class_attr, BaseSkill):
                        #     logger.error(
                        #         f"Skill class {skill_def.class_path} does not inherit from BaseSkill "
                        #         f"for skill '{skill_def.name}' in app '{self.app_config.id}'."
                        #     )
                        #     all_paths_valid = False
                        # else:
                        logger.debug(f"Successfully validated skill class path: {skill_def.class_path}")


            except ImportError as e:
                problematic_module_name = e.name if hasattr(e, 'name') else "Unknown"
                logger.error(
                    f"Failed to import module for skill '{skill_def.name}' in app '{self.app_config.id if self.app_config else self.app_id}'. "
                    f"Class path: {skill_def.class_path}. "
                    f"Error: {e}. Problematic module trying to be imported: '{problematic_module_name}'.\n"
                    f"This error often occurs if the skill's code (file: {module_path if 'module_path' in locals() else 'unknown'}.py) "
                    f"or one of its imported modules attempts to directly import a module like 'backend.*' (e.g., 'from backend.core.api...').\n"
                    f"Such imports are against the new architecture where apps are isolated.\n"
                    f"FIX: The skill '{skill_def.name}' (or its dependencies) needs to be refactored:\n"
                    f"1. For shared utilities, use 'from backend_shared.... import ...'.\n"
                    f"2. For core API functionalities (like accessing Directus, config, encryption), "
                    f"the skill should make internal API calls to the main 'api' service via 'self.app._make_internal_api_request(...)'.\n"
                    f"Please review the imports in '{skill_def.class_path}' and its dependencies.",
                    exc_info=True # exc_info=True will provide the full traceback for debugging where the import was attempted.
                )
                all_paths_valid = False
            except ValueError: # Handles cases where rsplit fails (e.g. class_path is not a dot-separated path)
                logger.error(
                    f"Invalid class_path format for skill '{skill_def.name}' in app '{self.app_config.id}': {skill_def.class_path}. "
                    "Expected format 'module.submodule.ClassName'."
                )
                all_paths_valid = False
            except Exception as e:
                logger.error(
                    f"Unexpected error validating skill class path '{skill_def.class_path}' for skill '{skill_def.name}' "
                    f"in app '{self.app_config.id}': {e}", exc_info=True
                )
                all_paths_valid = False
        
        if not all_paths_valid:
            self.is_valid = False # Mark app as invalid if any skill path fails

    @property
    def id(self) -> Optional[str]:
        # Return the centrally managed app_id
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
    def focus_modes(self) -> List[AppFocusDefinition]: # Alias for focuses
        return self.focuses

    @property
    def memory_fields(self) -> List[AppMemoryFieldDefinition]:
        return self.app_config.memory_fields if self.app_config else []
    
    @property
    def memory(self) -> List[AppMemoryFieldDefinition]: # Alias for memory_fields
        return self.memory_fields

    def get_skill_by_id(self, skill_id: str) -> Optional[AppSkillDefinition]:
        """Retrieves a skill definition by its ID."""
        for skill in self.skills:
            if skill.id == skill_id:
                return skill
        return None

    def get_focus_by_id(self, focus_id: str) -> Optional[AppFocusDefinition]:
        """Retrieves a focus definition by its ID."""
        for focus in self.focuses:
            if focus.id == focus_id:
                return focus
        return None
    
    def get_memory_field_by_id(self, memory_field_id: str) -> Optional[AppMemoryFieldDefinition]:
        """Retrieves a memory field definition by its ID."""
        for mem_field in self.memory_fields:
            if mem_field.id == memory_field_id:
                return mem_field
        return None


if __name__ == '__main__':
    import uvicorn
    import asyncio

    async def run_test_app():
        # Create dummy app directory and app.yml for testing
        current_script_dir = os.path.dirname(os.path.abspath(__file__))
        dummy_app_path = os.path.join(current_script_dir, "dummy_test_app")
        dummy_app_yml_path = os.path.join(dummy_app_path, "app.yml")

        if not os.path.exists(dummy_app_path):
            os.makedirs(dummy_app_path)

        dummy_yml_content = {
            "id": "test-app",
            "name": "Test Application",
            "description": "A sample application for testing BaseApp.",
            "skills": [
                {
                    "id": "greet",
                    "name": "Greeting Skill",
                    "description": "Returns a greeting.",
                    "class_path": "dummy_app.skills.greeting.GreetingSkill",
                    "stage": "production"
                }
            ],
            "focus_modes": [
                {
                    "id": "creative",
                    "name": "Creative Writing Focus",
                    "description": "Focuses on creative writing.",
                    "systemprompt": "You are a creative assistant."
                }
            ],
            "memory": [
                {
                    "id": "user_prefs",
                    "name": "User Preferences",
                    "description": "Stores user preferences.",
                    "type": "json_object",
                    "schema": {"type": "object", "properties": {"theme": {"type": "string"}}}
                }
            ]
        }

        with open(dummy_app_yml_path, 'w') as f:
            yaml.dump(dummy_yml_content, f)

        logger.info(f"Dummy app.yml created at: {dummy_app_yml_path}")

        # Test BaseApp
        # Each app will run on its own port, e.g., AI app on 8001, Web app on 8002
        test_app_instance = BaseApp(app_dir=dummy_app_path, app_port=8001) # app_port is passed here

        if test_app_instance.is_valid:
            print(f"\nApp ID (from instance.id property): {test_app_instance.id}")
            print(f"App Name: {test_app_instance.name}")
            print(f"App Description: {test_app_instance.description}")
            
            print("\nSkills:")
            for skill_def in test_app_instance.skills:
                print(f"  - ID: {skill_def.id}, Name: {skill_def.name}, Stage: {skill_def.stage}, Path: {skill_def.class_path}")

            print("\nFocuses (Focus Modes):")
            for focus_def in test_app_instance.focuses:
                print(f"  - ID: {focus_def.id}, Name: {focus_def.name}, System Prompt: '{focus_def.system_prompt[:30]}...'")

            print("\nMemory Fields (Memory):")
            for mem_field_def in test_app_instance.memory_fields:
                print(f"  - ID: {mem_field_def.id}, Name: {mem_field_def.name}, Type: {mem_field_def.type}")

            # Simulate a call to charge credits
            try:
                print("\nSimulating credit charge...")
                charge_response = await test_app_instance.charge_user_credits(
                    user_id_hash="test_user_hashed_id",
                    credits_to_charge=10,
                    skill_id="greet",
                    app_id=test_app_instance.id,
                    usage_details={"input_tokens": 100, "output_tokens": 50}
                )
                print(f"Credit charge simulation response: {charge_response}")
            except HTTPException as e:
                print(f"Credit charge simulation failed: {e.detail}")
            except Exception as e:
                print(f"Unexpected error during credit charge simulation: {e}")

            # To run the FastAPI app for testing the /metadata endpoint:
            # config = uvicorn.Config(test_app_instance.fastapi_app, host="0.0.0.0", port=test_app_instance.port, log_level="info")
            # server = uvicorn.Server(config)
            # print(f"\nTo test the /metadata endpoint, run this BaseApp instance with Uvicorn (e.g., in its own Docker container).")
            # print(f"Example: uvicorn your_app_module:test_app_instance.fastapi_app --host 0.0.0.0 --port {test_app_instance.port}")
            # # await server.serve() # Uncomment to run server directly (blocks here)

        else:
            print(f"\nFailed to load or validate app from {dummy_app_path}")

        # Clean up dummy files (optional, for repeated testing)
        # os.remove(dummy_app_yml_path)
        # os.rmdir(dummy_app_path)
        # logger.info("Cleaned up dummy app files.")

    if __name__ == '__main__':
        logging.basicConfig(level=logging.INFO)
        asyncio.run(run_test_app())