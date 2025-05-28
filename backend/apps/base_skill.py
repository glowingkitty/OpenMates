# backend/apps/base_skill.py
# This file defines the BaseSkill class, which serves as a foundational
# component for all skills within the application framework. It will encapsulate
# common logic, configuration handling, and integration points for skills.

from typing import Optional, Dict, Any, Union, TYPE_CHECKING
from pydantic import BaseModel, Field, validator
import asyncio # For potential async operations
import time # For generating timestamps

# Import shared utilities
from backend.shared.python_utils.billing_utils import calculate_total_credits, BillingError, MINIMUM_CREDITS_CHARGED

if TYPE_CHECKING:
    from apps.base_app import BaseApp # For type hinting self.app

# Core services like ConfigManager, DirectusService, EncryptionService will be accessed via internal API calls
# made through the BaseApp instance. No direct top-level imports from backend.core.api...
from celery import Celery # For Celery type hinting

# Forward declaration for Celery task if needed, or import specific types
# from celery import Task # Example

# --- Updated SkillPricing model to match billing_utils expectations ---
class TokenPricingDetail(BaseModel):
    per_credit_unit: int

class TokenPricingConfig(BaseModel):
    input: Optional[TokenPricingDetail] = None
    output: Optional[TokenPricingDetail] = None

class UnitPricingConfig(BaseModel):
    credits: float
    unit_name: Optional[str] = None # e.g., "image", "api_call"

class MinutePricingConfig(BaseModel):
    credits: float # Credits per minute

class FixedPricingConfig(BaseModel):
    credits: float

class SkillPricing(BaseModel):
    """
    Defines the pricing structure for a skill, compatible with billing_utils.
    This structure should be mirrored in the skill's app.yml if it has custom pricing.
    """
    tokens: Optional[TokenPricingConfig] = None
    per_unit: Optional[UnitPricingConfig] = None
    per_minute: Optional[MinutePricingConfig] = None
    fixed: Optional[FixedPricingConfig] = None

    @validator('*', pre=True, always=True)
    def ensure_at_least_one_pricing_method(cls, v, values):
        # This validator is tricky because it runs for each field.
        # A root_validator would be better if we need to ensure at least one is set.
        # For now, we'll assume the config is valid if provided.
        return v

class BaseSkill:
    """
    Base class for all skills.
    Skills are discrete units of functionality that an app can expose.
    """
    skill_id: str
    app_id: str # Added app_id
    skill_name: str
    skill_description: str
    stage: str = Field(default="development", description="The deployment stage of the skill (e.g., 'development', 'production').")
    full_model_reference: Optional[str] = Field(None, description="Full reference to the model used by the skill, if applicable (e.g., 'google/gemini-2.5-pro').")
    pricing: Optional[SkillPricing] = Field(None, description="Specific pricing for this skill (from backend.core.api.app.yml), overrides provider model pricing if set.")

    # Dependencies like ConfigManager and DirectusService will be accessed via internal API calls.
    app: 'BaseApp' # Type hint for the parent BaseApp instance, resolved by TYPE_CHECKING import

    # TODO: Ensure Celery tasks spawned from skills are cancellable.
    # This might involve:
    # - Storing task IDs.
    # - Providing methods to request task cancellation.
    # - Handling Celery's mechanisms for task revocation.

    def __init__(
        self,
        app: 'BaseApp', # Pass the BaseApp instance
        app_id: str,
        skill_id: str,
        skill_name: str,
        skill_description: str,
        stage: str = "development",
        full_model_reference: Optional[str] = None,
        pricing_config: Optional[Dict[str, Any]] = None, # This dict should match SkillPricing structure
        celery_producer: Optional[Celery] = None
    ):
        self.app = app # Store reference to the parent BaseApp instance
        self.app_id = app_id
        self.skill_id = skill_id
        self.skill_name = skill_name
        self.skill_description = skill_description
        self.stage = stage
        self.full_model_reference = full_model_reference
        self.celery_producer = celery_producer
        if pricing_config:
            self.pricing = SkillPricing(**pricing_config)
        else:
            self.pricing = None

    async def execute(self, *args, **kwargs) -> Any:
        """
        Main execution method for the skill.
        Subclasses must implement this method.
        Should handle the core logic of the skill.
        """
        raise NotImplementedError("Each skill must implement the 'execute' method.")

    async def _get_effective_pricing_config(self) -> Optional[Dict[str, Any]]:
        """
        Determines the effective pricing configuration.
        Uses skill-specific pricing if available.
        Otherwise, falls back to provider model pricing by calling an internal API endpoint
        on the main 'api' service.
        """
        if self.pricing:
            return self.pricing.model_dump(exclude_none=True)
        
        if self.full_model_reference:
            if not self.app: # Should not happen if BaseApp passes itself correctly
                print(f"CRITICAL: BaseApp instance not available in skill '{self.skill_id}' for API call to get pricing.")
                return None
            try:
                provider_id, model_id_suffix = self.full_model_reference.split('/', 1)
                endpoint = f"internal/config/provider_model_pricing/{provider_id}/{model_id_suffix}"
                
                # This call will be made to the main API service.
                # The main API service will use its ConfigManager.
                model_pricing = await self.app._make_internal_api_request("GET", endpoint)
                
                if model_pricing and isinstance(model_pricing, dict):
                    return model_pricing
                else:
                    print(f"Warning: Could not retrieve valid pricing for model '{self.full_model_reference}' via internal API. Response: {model_pricing}")
                    return None
            except ValueError:
                print(f"Warning: Invalid format for full_model_reference: '{self.full_model_reference}'. Expected 'provider/model'.")
                return None
            except Exception as e:
                # Log the full exception for better debugging if the API call fails
                print(f"Error fetching model pricing for '{self.full_model_reference}' via internal API: {e}", exc_info=True)
                return None
        return None

    async def calculate_skill_credits( # Renamed from calculate_skill_credits to be async as it calls async _get_effective_pricing_config
        self,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        units_processed: Optional[int] = None,
        duration_minutes: Optional[float] = None,
    ) -> int:
        """
        Calculates credits for this skill execution.
        """
        effective_pricing_config = await self._get_effective_pricing_config()
        
        if not effective_pricing_config:
            print(f"Warning: No effective pricing configuration found for skill '{self.skill_id}'. Defaulting to {MINIMUM_CREDITS_CHARGED} credit.")
            return MINIMUM_CREDITS_CHARGED

        calculated_credits = calculate_total_credits(
            pricing_config=effective_pricing_config,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            units_processed=units_processed,
            duration_minutes=duration_minutes
        )
        # Ensure that even if calculation results in 0 for a priced skill, it's at least 1.
        # The calculate_total_credits function itself should handle this with its MINIMUM_CREDITS_CHARGED.
        return calculated_credits

    async def record_skill_usage(
        self,
        user_id_hash: str,
        credits_charged: int,
        cost_system_prompt_credits: Optional[float] = None,
        cost_history_credits: Optional[float] = None,
        cost_response_credits: Optional[float] = None,
        actual_input_tokens: Optional[int] = None,
        actual_output_tokens: Optional[int] = None,
        usage_type: str = "skill_execution",
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
        # Other relevant metrics can be added here
    ):
        """
        Sends skill usage data to the main API service for recording.
        The main API will handle encryption and persistence using its own DirectusService and EncryptionService.
        """
        if not self.app: # Should not happen if BaseApp passes itself correctly
            print(f"CRITICAL: BaseApp instance not available in skill '{self.skill_id}' for API call to record usage.")
            return

        current_ts = int(time.time())
        
        usage_payload = {
            "user_id_hash": user_id_hash,
            "app_id": self.app_id,
            "skill_id": self.skill_id,
            "type": usage_type,
            "timestamp": current_ts,
            "credits_charged": credits_charged,
            "model_used": self.full_model_reference,
            "chat_id": chat_id,
            "message_id": message_id,
            "cost_details": { # Raw, unencrypted data for the main API to process and encrypt
                "system_prompt_credits": cost_system_prompt_credits,
                "history_credits": cost_history_credits,
                "response_credits": cost_response_credits,
                "input_tokens": actual_input_tokens,
                "output_tokens": actual_output_tokens,
            }
        }
        
        # Clean up None values in cost_details
        usage_payload["cost_details"] = {k: v for k, v in usage_payload["cost_details"].items() if v is not None}
        if not usage_payload["cost_details"]: # If cost_details becomes empty, remove it
            del usage_payload["cost_details"]

        try:
            endpoint = "internal/usage/record" # This internal endpoint needs to be implemented in the main API service
            response = await self.app._make_internal_api_request("POST", endpoint, payload=usage_payload)
            print(f"Successfully sent usage data for skill '{self.skill_id}' by user '{user_id_hash}'. Main API response: {response}")
        except Exception as e:
            print(f"Error sending usage data for skill '{self.skill_id}': {e}", exc_info=True)
            # Potentially raise or handle more gracefully


    def get_metadata(self) -> Dict[str, Any]:
        """
        Returns metadata about the skill.
        """
        return {
            "id": self.skill_id,
            "app_id": self.app_id, # Added app_id
            "name": self.skill_name,
            "description": self.skill_description,
            "stage": self.stage,
            "full_model_reference": self.full_model_reference,
            "pricing": self.pricing.model_dump(exclude_none=True) if self.pricing else None,
            # Add other relevant metadata
        }

    # Placeholder for Celery task management
    # async def run_as_task(self, *args, **kwargs) -> Optional[str]:
    #     """
    #     Example of how a skill might spawn a Celery task.
    #     Returns the task ID.
    #     """
    #     # from your_celery_app import your_task_function # Specific task
    #     # task = your_task_function.delay(*args, **kwargs)
    #     # return task.id
    #     print(f"Placeholder: Skill {self.skill_id} would run as a Celery task with args: {args}, kwargs: {kwargs}")
    #     return None

    # async def cancel_task(self, task_id: str) -> bool:
    #     """
    #     Example of how a skill might request cancellation of a Celery task.
    #     """
    #     # from your_celery_app import app as celery_app
    #     # celery_app.control.revoke(task_id, terminate=True)
    #     # return True
    #     print(f"Placeholder: Skill {self.skill_id} would cancel Celery task: {task_id}")
    #     return False

    def __repr__(self) -> str:
        return f"<BaseSkill(skill_id='{self.skill_id}', name='{self.skill_name}', stage='{self.stage}')>"

if __name__ == '__main__':
    # Example Usage (for testing purposes)
    class MySampleSkill(BaseSkill):
        async def execute(self, user_input: str) -> str:
            print(f"Executing MySampleSkill with input: {user_input}")
            # Simulate some work
            await asyncio.sleep(0.1)
            return f"Processed: {user_input}"

    async def main():
        sample_skill_pricing = {
            "per_call": 0.01
        }
        sample_skill = MySampleSkill(
            skill_id="sample.greet",
            skill_name="Sample Greeting Skill",
            skill_description="A simple skill that greets the user.",
            stage="production",
            full_model_reference="custom/local-model-v1",
            pricing_config=sample_skill_pricing
        )

        print(sample_skill.get_metadata())
        response = await sample_skill.execute(user_input="Hello Roo!")
        print(f"Response from skill: {response}")

        # Example of task placeholders
        # task_id = await sample_skill.run_as_task(user_input="Run this as a task")
        # if task_id:
        #     print(f"Task started with ID: {task_id}")
        #     # await sample_skill.cancel_task(task_id) # Example cancellation

    asyncio.run(main())