# backend/apps/base_skill.py
# This file defines the BaseSkill class, which serves as a foundational
# component for all skills within the application framework. It will encapsulate
# common logic, configuration handling, and integration points for skills.

from typing import Optional, Dict, Any, Union, Tuple, Set, List, Callable, Type, TYPE_CHECKING
from pydantic import BaseModel, Field, validator
import asyncio # For potential async operations
import time # For generating timestamps
import logging
import hashlib

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
    
    # Context information for usage tracking (set by BaseApp when skill is executed)
    _current_chat_id: Optional[str] = None  # Chat ID for current execution context
    _current_message_id: Optional[str] = None  # Message ID for current execution context

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
        user_id: str,  # Actual user ID (needed for encryption key lookup)
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
        
        Args:
            user_id: Actual user ID (needed to look up vault_key_id for encryption)
            user_id_hash: Hashed user ID for privacy
            credits_charged: Number of credits charged for this skill execution
            cost_system_prompt_credits: Optional system prompt credit cost
            cost_history_credits: Optional history credit cost
            cost_response_credits: Optional response credit cost
            actual_input_tokens: Optional input token count
            actual_output_tokens: Optional output token count
            usage_type: Type of usage (default: "skill_execution")
            chat_id: Optional chat ID (if not provided, will use _current_chat_id from execution context)
            message_id: Optional message ID (if not provided, will use _current_message_id from execution context)
        """
        if not self.app: # Should not happen if BaseApp passes itself correctly
            print(f"CRITICAL: BaseApp instance not available in skill '{self.skill_id}' for API call to record usage.")
            return

        # Use provided chat_id/message_id, or fall back to execution context if available
        # This allows skills to explicitly pass these values, or use the context from the current execution
        effective_chat_id = chat_id or self._current_chat_id
        effective_message_id = message_id or self._current_message_id

        current_ts = int(time.time())
        
        usage_payload = {
            "user_id": user_id,  # Required for encryption key lookup
            "user_id_hash": user_id_hash,
            "app_id": self.app_id,  # Required: ID of the app that contains the skill
            "skill_id": self.skill_id,  # Required: ID of the skill that was executed
            "type": usage_type,
            "timestamp": current_ts,
            "credits_charged": credits_charged,
            "model_used": self.full_model_reference,
            "chat_id": effective_chat_id,  # Use execution context if not explicitly provided
            "message_id": effective_message_id,  # Use execution context if not explicitly provided
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

    def _validate_and_normalize_request_id(
        self,
        req: Dict[str, Any],
        request_index: int,
        total_requests: int,
        request_ids: Set[Any],
        logger: Optional[logging.Logger] = None
    ) -> Tuple[Optional[Any], Optional[str]]:
        """
        Validates and normalizes the 'id' field for a request in a multi-request skill call.
        
        This helper method implements the standard pattern for handling request IDs:
        - For single requests: 'id' is optional - auto-generates id=1 if missing
        - For multiple requests: 'id' is required to match responses to requests
        - Validates that 'id' values are unique within the batch
        
        Args:
            req: The request dictionary to validate
            request_index: Zero-based index of the request in the requests array (for error messages)
            total_requests: Total number of requests in the batch
            request_ids: Set of already-seen request IDs (for uniqueness validation)
            logger: Optional logger instance for debug messages (if None, uses print)
        
        Returns:
            Tuple of (request_id, error_message_or_none):
            - request_id: The validated/normalized request ID, or None if validation failed
            - error_message_or_none: Error message string if validation failed, None if successful
        
        Example usage in a skill's execute() method:
            request_ids = set()
            for i, req in enumerate(requests):
                request_id, error = self._validate_and_normalize_request_id(
                    req=req,
                    request_index=i,
                    total_requests=len(requests),
                    request_ids=request_ids,
                    logger=logger
                )
                if error:
                    return Response(results=[], error=error)
                # Note: request_id is already added to request_ids by the helper
        """
        # Use provided logger or fall back to print for debug messages
        log_func = logger.debug if logger else print
        
        # Auto-generate 'id' ONLY if not provided
        # This respects user-provided IDs from REST API callers while still
        # auto-generating for requests that don't have IDs
        # Note: For LLM tool calls, main_processor.py sets IDs before calling skills,
        # so skills will see those as "provided" and use them consistently
        if "id" not in req:
            # Use request_index + 1 as the auto-generated ID (1-indexed for readability)
            auto_id = request_index + 1
            req["id"] = auto_id
            log_func(f"Auto-generated 'id'={auto_id} for request {request_index + 1} of {total_requests}")
        
        request_id = req.get("id")
        
        # Validate id is unique within this batch
        if request_id in request_ids:
            error_msg = (
                f"Request {request_index + 1} has duplicate 'id' value '{request_id}'. "
                f"Each request must have a unique 'id'."
            )
            return (None, error_msg)
        
        # Add to set for future uniqueness checks (caller should also add it)
        request_ids.add(request_id)
        
        return (request_id, None)

    async def _get_or_create_secrets_manager(
        self,
        secrets_manager: Optional[Any],
        skill_name: str,
        error_response_factory: Callable[[str], Any],
        logger: Optional[logging.Logger] = None
    ) -> Tuple[Optional[Any], Optional[Any]]:
        """
        Get or create a SecretsManager instance.
        
        This helper method standardizes the pattern of getting or creating a SecretsManager
        instance that is used across all skills. It first tries to use an injected instance,
        then tries to get one from the app, and finally creates a new one if needed.
        
        Args:
            secrets_manager: Optional SecretsManager instance (may be injected by app)
            skill_name: Name of the skill (for logging and error messages)
            error_response_factory: Callable that takes an error message and returns an error response object
            logger: Optional logger instance (if None, uses print)
        
        Returns:
            Tuple of (secrets_manager, error_response_or_none):
            - secrets_manager: The SecretsManager instance, or None if initialization failed
            - error_response_or_none: Error response object if initialization failed, None if successful
        
        Example usage:
            secrets_manager, error_response = await self._get_or_create_secrets_manager(
                secrets_manager=secrets_manager,
                skill_name="ReadSkill",
                error_response_factory=lambda msg: ReadResponse(results=[], error=msg),
                logger=logger
            )
            if error_response:
                return error_response
        """
        # Use injected secrets_manager or create a new one
        if secrets_manager is None:
            # Try to get from app if available
            if hasattr(self.app, 'secrets_manager') and self.app.secrets_manager:
                secrets_manager = self.app.secrets_manager
            else:
                # Create a new SecretsManager instance
                # Skills that need secrets should initialize their own SecretsManager
                try:
                    # Import here to avoid circular dependencies
                    from backend.core.api.app.utils.secrets_manager import SecretsManager
                    secrets_manager = SecretsManager()
                    await secrets_manager.initialize()
                    if logger:
                        logger.debug(f"{skill_name} initialized its own SecretsManager instance")
                    else:
                        print(f"{skill_name} initialized its own SecretsManager instance")
                except Exception as e:
                    error_msg = f"{skill_name} service configuration error: Failed to initialize secrets manager"
                    if logger:
                        logger.error(f"Failed to initialize SecretsManager for {skill_name}: {e}", exc_info=True)
                    else:
                        print(f"Failed to initialize SecretsManager for {skill_name}: {e}", exc_info=True)
                    return (None, error_response_factory(error_msg))
        
        return (secrets_manager, None)

    def _validate_requests_array(
        self,
        requests: List[Dict[str, Any]],
        required_field: str,
        field_display_name: str,
        empty_error_message: str,
        logger: logging.Logger
    ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """
        Validate requests array structure, IDs, and required fields.
        
        This helper method standardizes the validation pattern used across all skills:
        - Validates that requests array is not empty
        - Validates and normalizes request IDs using _validate_and_normalize_request_id
        - Validates that each request has the required field
        
        Args:
            requests: List of request dictionaries to validate
            required_field: Name of the required field to check (e.g., 'url', 'query')
            field_display_name: Display name for the field in error messages (e.g., 'url', 'query')
            empty_error_message: Error message to return if requests array is empty
            logger: Logger instance for error logging
        
        Returns:
            Tuple of (validated_requests, error_message_or_none):
            - validated_requests: The validated requests list, or None if validation failed
            - error_message_or_none: Error message string if validation failed, None if successful
        
        Example usage:
            validated_requests, error = self._validate_requests_array(
                requests=requests,
                required_field="url",
                field_display_name="url",
                empty_error_message="No read requests provided. 'requests' array must contain at least one request with a 'url' field.",
                logger=logger
            )
            if error:
                return ReadResponse(results=[], error=error)
        """
        # Validate requests array is not empty
        if not requests or len(requests) == 0:
            logger.error(f"No requests provided to {self.skill_name}")
            return (None, empty_error_message)
        
        # Validate that all requests have required fields: 'id' and the specified required field
        # Use BaseSkill helper method for consistent validation across all skills
        request_ids = set()
        for i, req in enumerate(requests):
            # Validate and normalize request 'id' field using BaseSkill helper
            request_id, error = self._validate_and_normalize_request_id(
                req=req,
                request_index=i,
                total_requests=len(requests),
                request_ids=request_ids,
                logger=logger
            )
            if error:
                logger.error(f"Request {i+1} validation failed: {error}")
                return (None, error)
            
            # Validate required field
            if not req.get(required_field):
                logger.error(f"Request {i+1} (id: {request_id}) in requests array is missing '{field_display_name}' field")
                return (None, f"Request {i+1} (id: {request_id}) is missing required '{field_display_name}' field")
        
        return (requests, None)

    async def _process_requests_in_parallel(
        self,
        requests: List[Dict[str, Any]],
        process_single_request_func: Callable,
        logger: logging.Logger,
        **kwargs
    ) -> List[Any]:
        """
        Process multiple requests in parallel using asyncio.gather.
        
        This helper method standardizes the parallel processing pattern used across all skills.
        It creates tasks for each request and executes them in parallel.
        
        Args:
            requests: List of request dictionaries to process
            process_single_request_func: Async function to process a single request
                                        Must accept req, request_id, and other kwargs
            logger: Logger instance for logging
            **kwargs: Additional keyword arguments to pass to process_single_request_func
        
        Returns:
            List of results from asyncio.gather (may include exceptions)
        
        Example usage:
            results = await self._process_requests_in_parallel(
                requests=read_requests,
                process_single_request_func=self._process_single_read_request,
                logger=logger,
                secrets_manager=secrets_manager,
                cache_service=cache_service
            )
        """
        # Process all requests in parallel using asyncio.gather()
        # Each request is processed independently
        logger.info(f"Processing {len(requests)} requests in parallel")
        tasks = [
            process_single_request_func(
                req=req,
                request_id=req.get("id"),
                **kwargs
            )
            for req in requests
        ]
        
        # Wait for all requests to complete (parallel execution)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results

    def _group_results_by_request_id(
        self,
        results: List[Any],
        requests: List[Dict[str, Any]],
        logger: logging.Logger
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Group results by request ID and handle errors.
        
        This helper method standardizes the result processing pattern used across all skills.
        It processes results from asyncio.gather, handles exceptions, and groups results by request ID.
        
        Args:
            results: List of results from asyncio.gather (may include exceptions)
            requests: Original list of requests (for maintaining order)
            logger: Logger instance for error logging
        
        Returns:
            Tuple of (grouped_results, errors):
            - grouped_results: List of dicts with 'id' and 'results' keys, grouped by request ID
            - errors: List of error message strings
        
        Example usage:
            grouped_results, errors = self._group_results_by_request_id(
                results=results,
                requests=read_requests,
                logger=logger
            )
        """
        # Process results and group by request id
        grouped_results: List[Dict[str, Any]] = []
        errors: List[str] = []
        
        for result in results:
            if isinstance(result, Exception):
                # Handle exceptions from asyncio.gather
                error_msg = f"Unexpected error processing request: {str(result)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
                continue
            
            # Result should be a tuple of (request_id, items, error)
            request_id, items, error = result
            
            if error:
                errors.append(error)
                # Still include the request in results (with empty results array) for consistency
                # Include error message in grouped_result so it can be used for error embeds
                grouped_results.append({
                    "id": request_id,
                    "results": [],
                    "error": error  # Store error message for this specific request
                })
            else:
                # Group results by request id
                grouped_results.append({
                    "id": request_id,
                    "results": items
                })
        
        # Sort results by request order (maintain original request order in response)
        request_order = {req.get("id"): i for i, req in enumerate(requests)}
        grouped_results.sort(key=lambda x: request_order.get(x["id"], 999))
        
        return (grouped_results, errors)

    def _build_response_with_errors(
        self,
        response_class: Type,
        grouped_results: List[Dict[str, Any]],
        errors: List[str],
        provider: str,
        suggestions: Optional[List[str]],
        logger: logging.Logger,
        **response_kwargs
    ) -> Any:
        """
        Build response object with error handling and suggestions.
        
        This helper method standardizes the response building pattern used across all skills.
        It creates a response object, adds errors if any, and includes suggestions if configured.
        
        Args:
            response_class: The response class to instantiate (e.g., ReadResponse, SearchResponse)
            grouped_results: List of grouped results (from _group_results_by_request_id)
            errors: List of error message strings
            provider: Provider name (e.g., "Firecrawl", "Brave Search")
            suggestions: Optional list of follow-up suggestions
            logger: Logger instance for logging
            **response_kwargs: Additional keyword arguments to pass to response_class constructor
        
        Returns:
            Instance of response_class with results, errors, and suggestions set
        
        Example usage:
            response = self._build_response_with_errors(
                response_class=ReadResponse,
                grouped_results=grouped_results,
                errors=errors,
                provider="Firecrawl",
                suggestions=suggestions,
                logger=logger
            )
        """
        # Calculate total results
        total_results = sum(len(group.get("results", [])) for group in grouped_results)
        
        # Use follow-up suggestions if we have results and suggestions are configured
        final_suggestions = None
        if total_results > 0 and suggestions:
            final_suggestions = suggestions
        
        # Build response with grouped results structure
        response = response_class(
            results=grouped_results,  # Grouped by request id
            provider=provider,  # Provider at root level
            suggestions_follow_up_requests=final_suggestions,
            **response_kwargs
        )
        
        # Add error message if there were errors (but still return results if any)
        if errors:
            response.error = "; ".join(errors)
            logger.warning(f"{self.skill_name} completed with {len(errors)} error(s): {response.error}")
        
        logger.info(f"{self.skill_name} execution completed: {len(grouped_results)} request groups, {total_results} total results, {len(errors)} errors")
        return response

    def _generate_result_hash(self, url: str) -> str:
        """
        Generate a hash for a result URL.
        Used for deduplication and tracking.
        
        This helper method provides a consistent way to generate hashes for URLs
        across all skills that need to track or deduplicate results.
        
        Args:
            url: The result URL to hash
        
        Returns:
            Hash string (first 16 characters of SHA256 hash)
        
        Example usage:
            hash_value = self._generate_result_hash(result_url)
        """
        return hashlib.sha256(url.encode()).hexdigest()[:16]

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