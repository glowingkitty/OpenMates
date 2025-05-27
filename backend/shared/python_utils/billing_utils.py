# backend/shared/python_utils/billing_utils.py
# This module contains utility functions for calculating costs and credits
# based on usage metrics and pricing configurations.

import math
import logging # Added logging
from typing import Dict, Any, Optional, Union

# Removed: from backend.core.api.app.utils.config_manager import ConfigManager
# ConfigManager should not be accessed directly from backend_shared.
# Pricing information should be passed into functions here.

logger = logging.getLogger(__name__) # Added logger

# Define a type alias for pricing configuration for clarity
PricingConfig = Dict[str, Any]
# ModelPricingDetails is essentially the same as PricingConfig in this context,
# as this util only cares about the structure for calculation, not its origin.
ModelPricingDetails = PricingConfig

MINIMUM_CREDITS_CHARGED = 1

class BillingError(Exception):
    """Custom exception for billing related errors."""
    pass

# Removed get_model_pricing_details function.
# The responsibility for obtaining the pricing_config (either from skill's app.yml
# or via an internal API call made by BaseSkill) lies outside of this utility module.
# This module should only perform calculations based on a provided pricing_config.

def calculate_credits_from_tokens(
    input_tokens: int,
    output_tokens: int,
    pricing_details: ModelPricingDetails
) -> float:
    """
    Calculates credits based on input and output tokens and their respective pricing.
    """
    credits = 0.0
    token_pricing = pricing_details.get("tokens")
    if not token_pricing:
        # This model might not be priced per token, or pricing is misconfigured
        return 0.0

    input_pricing = token_pricing.get("input", {})
    output_pricing = token_pricing.get("output", {})

    input_per_credit_unit = input_pricing.get("per_credit_unit")
    output_per_credit_unit = output_pricing.get("per_credit_unit")

    if input_per_credit_unit and input_per_credit_unit > 0:
        credits += (input_tokens / input_per_credit_unit)
    
    if output_per_credit_unit and output_per_credit_unit > 0:
        credits += (output_tokens / output_per_credit_unit)
        
    return credits

def calculate_credits_from_units(
    units: int,
    pricing_details: ModelPricingDetails
) -> float:
    """
    Calculates credits based on units processed (e.g., images, API calls).
    Assumes pricing_details contains something like:
    "per_unit": { "credits": 1, "unit_name": "image" }
    """
    credits = 0.0
    unit_pricing = pricing_details.get("per_unit")
    if unit_pricing and unit_pricing.get("credits") is not None:
        credits_per_unit = unit_pricing.get("credits", 0)
        credits += units * credits_per_unit
    return credits

def calculate_credits_from_duration(
    duration_minutes: float,
    pricing_details: ModelPricingDetails
) -> float:
    """
    Calculates credits based on duration in minutes.
    Assumes pricing_details contains something like:
    "per_minute": { "credits": 0.5 }
    """
    credits = 0.0
    duration_pricing = pricing_details.get("per_minute")
    if duration_pricing and duration_pricing.get("credits") is not None:
        credits_per_minute = duration_pricing.get("credits", 0)
        credits += duration_minutes * credits_per_minute
    return credits

def calculate_fixed_credits(
    pricing_details: ModelPricingDetails
) -> float:
    """
    Returns fixed credits if defined.
    Assumes pricing_details contains something like:
    "fixed": { "credits": 5 }
    """
    fixed_pricing = pricing_details.get("fixed")
    if fixed_pricing and fixed_pricing.get("credits") is not None:
        return float(fixed_pricing.get("credits", 0))
    return 0.0


def calculate_total_credits(
    *, # Force keyword arguments
    pricing_config: PricingConfig, # Can be from skill's app.yml or resolved from provider model
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    units_processed: Optional[int] = None,
    duration_minutes: Optional[float] = None,
) -> int:
    """
    Calculates the total credits for a skill execution based on its pricing config and usage metrics.

    Args:
        pricing_config: The pricing configuration block for the skill or model.
                        Example structure:
                        {
                            "tokens": { "input": { "per_credit_unit": 7000 }, "output": { "per_credit_unit": 2000 } },
                            "per_unit": { "credits": 1, "unit_name": "image" },
                            "per_minute": { "credits": 0.5 },
                            "fixed": { "credits": 10 }
                        }
                        Only one primary pricing method (tokens, per_unit, per_minute, fixed) should be dominant.
                        If multiple are present, the function will sum them, which might be unintended unless
                        the pricing_config is carefully structured (e.g. a base fixed cost + token cost).
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.
        units_processed: Number of units (e.g., images).
        duration_minutes: Duration in minutes.

    Returns:
        The total credits, rounded up to the nearest whole number, and at least MINIMUM_CREDITS_CHARGED.
        Returns 0 if no relevant pricing information is found or no chargeable metrics are provided.
    """
    if not pricing_config:
        # If a skill is meant to be free or tracking is not required, it might not have pricing.
        # Or, this indicates a configuration issue if it's supposed to be billable.
        return 0 # Or raise BillingError("Pricing configuration is missing.")

    raw_credits = 0.0

    # Check for fixed pricing first, as it might be a standalone cost
    if "fixed" in pricing_config:
        raw_credits += calculate_fixed_credits(pricing_config)
    
    # Token-based pricing
    if "tokens" in pricing_config and input_tokens is not None and output_tokens is not None:
        raw_credits += calculate_credits_from_tokens(input_tokens, output_tokens, pricing_config)

    # Unit-based pricing
    if "per_unit" in pricing_config and units_processed is not None:
        raw_credits += calculate_credits_from_units(units_processed, pricing_config)

    # Duration-based pricing
    if "per_minute" in pricing_config and duration_minutes is not None:
        raw_credits += calculate_credits_from_duration(duration_minutes, pricing_config)

    if raw_credits <= 0:
        return 0 # No billable activity or pricing not applicable

    # Apply minimum credit rule and round up
    final_credits = math.ceil(raw_credits)
    if final_credits < MINIMUM_CREDITS_CHARGED:
        final_credits = MINIMUM_CREDITS_CHARGED
        
    return int(final_credits)