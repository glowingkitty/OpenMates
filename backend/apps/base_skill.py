# backend/apps/base_skill.py
# This file defines the BaseSkill class, which serves as a foundational
# component for all skills within the application framework. It will encapsulate
# common logic, configuration handling, and integration points for skills.

from typing import Optional, Dict, Any, Union
from pydantic import BaseModel, Field, validator
import asyncio # For potential async operations and Celery task management
import time # For generating timestamps

# Import billing utilities and ConfigManager (adjust path if necessary)
from backend.core.api.app.utils.billing_utils import calculate_total_credits, get_model_pricing_details, BillingError
from backend.core.api.app.utils.config_manager import ConfigManager # Assuming this is the correct path
from backend.core.api.app.services.directus import DirectusService # For recording usage
from backend.core.api.app.utils.encryption import EncryptionService # For encrypting usage data

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

    # Dependencies like ConfigManager and DirectusService will be passed to methods needing them.

    # TODO: Ensure Celery tasks spawned from skills are cancellable.
    # This might involve:
    # - Storing task IDs.
    # - Providing methods to request task cancellation.
    # - Handling Celery's mechanisms for task revocation.

    def __init__(
        self,
        app_id: str, # Added app_id
        skill_id: str,
        skill_name: str,
        skill_description: str,
        stage: str = "development",
        full_model_reference: Optional[str] = None,
        pricing_config: Optional[Dict[str, Any]] = None, # This dict should match SkillPricing structure
        # Potentially other common configurations like logger
    ):
        self.app_id = app_id
        self.skill_id = skill_id
        self.skill_name = skill_name
        self.skill_description = skill_description
        self.stage = stage
        self.full_model_reference = full_model_reference
        if pricing_config:
            self.pricing = SkillPricing(**pricing_config)
        else:
            self.pricing = None

        # TODO: Initialize common utilities like logger, access to config/secrets

    async def execute(self, *args, **kwargs) -> Any:
        """
        Main execution method for the skill.
        Subclasses must implement this method.
        Should handle the core logic of the skill.
        """
        raise NotImplementedError("Each skill must implement the 'execute' method.")

    def _get_effective_pricing_config(
        self,
        config_manager: ConfigManager
    ) -> Optional[Dict[str, Any]]:
        """
        Determines the effective pricing configuration.
        Uses skill-specific pricing if available, otherwise falls back to provider model pricing.
        """
        if self.pricing:
            return self.pricing.model_dump(exclude_none=True)
        
        if self.full_model_reference:
            model_pricing = get_model_pricing_details(self.full_model_reference, config_manager)
            if model_pricing:
                return model_pricing # This is already a dict
            else:
                # Log warning: model reference provided but no pricing found
                print(f"Warning: Model reference '{self.full_model_reference}' provided for skill '{self.skill_id}' but no pricing found in provider configs.")
                return None
        return None

    def calculate_skill_credits(
        self,
        config_manager: ConfigManager,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        units_processed: Optional[int] = None,
        duration_minutes: Optional[float] = None,
    ) -> int:
        """
        Calculates credits for this skill execution.
        """
        effective_pricing_config = self._get_effective_pricing_config(config_manager)
        
        if not effective_pricing_config:
            # If no pricing config could be determined (neither skill-specific nor provider-based),
            # and the skill is intended to be billable, default to MINIMUM_CREDITS_CHARGED.
            print(f"Warning: No effective pricing configuration found for skill '{self.skill_id}'. Defaulting to {BillingError.MINIMUM_CREDITS_CHARGED if hasattr(BillingError, 'MINIMUM_CREDITS_CHARGED') else 1} credit.")
            # Access MINIMUM_CREDITS_CHARGED from billing_utils if it's defined there, otherwise default to 1.
            # For now, directly using the constant from billing_utils.
            try:
                from backend.core.api.app.utils.billing_utils import MINIMUM_CREDITS_CHARGED
                return MINIMUM_CREDITS_CHARGED
            except ImportError:
                return 1 # Fallback if import fails, though it shouldn't

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
        directus_service: DirectusService,
        encryption_service: EncryptionService, # Added
        user_id_hash: str, # This will also serve as the user_vault_key_id for encrypting usage details
        credits_charged: int, # This is the final, clear value after calculation and rounding
        # Detailed cost components (optional, if available from LLM response or calculation)
        cost_system_prompt_credits: Optional[float] = None,
        cost_history_credits: Optional[float] = None,
        cost_response_credits: Optional[float] = None,
        # Token counts
        actual_input_tokens: Optional[int] = None, # Renamed for clarity vs. pricing input_tokens
        actual_output_tokens: Optional[int] = None, # Renamed for clarity
        # Other optional fields from usage.yml
        usage_type: str = "skill_execution", # Default usage type
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
        # units_processed: Optional[int] = None, # Add if needed by usage schema
        # duration_seconds: Optional[float] = None, # Add if needed by usage schema
    ):
        """
        Records the usage of this skill to the Directus 'usage' collection.
        Encrypts sensitive fields before storing.
        """
        current_ts = int(time.time())
        user_vault_key_id = user_id_hash # Use user_id_hash as the key for their usage data encryption

        # Prepare data for encryption
        data_to_encrypt = {
            "credits_costs_system_prompt": str(cost_system_prompt_credits) if cost_system_prompt_credits is not None else None,
            "credits_costs_history": str(cost_history_credits) if cost_history_credits is not None else None,
            "credits_cost_response": str(cost_response_credits) if cost_response_credits is not None else None,
            "credits_cost_total": str(credits_charged), # Encrypt the final charged amount
            "input_tokens": str(actual_input_tokens) if actual_input_tokens is not None else None,
            "output_tokens": str(actual_output_tokens) if actual_output_tokens is not None else None,
        }

        encrypted_usage_details: Dict[str, Optional[str]] = {}
        for key, value in data_to_encrypt.items():
            if value is not None:
                encrypted_value = await encryption_service.encrypt_with_user_key(
                    key_id=user_vault_key_id,
                    plaintext=value
                )
                encrypted_usage_details[f"encrypted_{key}"] = encrypted_value
            else:
                encrypted_usage_details[f"encrypted_{key}"] = None
        
        usage_data = {
            "user_id_hash": user_id_hash,
            "app_id": self.app_id,
            "skill_id": self.skill_id,
            "type": usage_type,
            "timestamp": current_ts, # When the event occurred
            # "credits_charged" is not stored directly; its encrypted form is in encrypted_credits_cost_total
            "model_used": self.full_model_reference,
            "chat_id": chat_id,
            "message_id": message_id,
            "created_at": current_ts, # Record creation time
            "updated_at": current_ts, # Record update time (same as creation for new entry)
            **encrypted_usage_details # Add all encrypted fields
        }
        
        # Filter out None values before sending to Directus
        usage_data_cleaned = {k: v for k, v in usage_data.items() if v is not None}

        try:
            # This method needs to be created in DirectusService
            await directus_service.usage.create_usage_entry(usage_data_cleaned)
            print(f"Successfully recorded usage for skill '{self.skill_id}' by user '{user_id_hash}'. Credits: {credits_charged}")
        except Exception as e:
            # Log error: failed to record usage
            print(f"Error recording usage for skill '{self.skill_id}': {e}")
            # Potentially raise or handle more gracefully (e.g., retry queue)


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