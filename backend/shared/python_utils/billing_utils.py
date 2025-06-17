# backend/shared/python_utils/billing_utils.py
# This module contains utility functions for calculating costs and credits
# based on usage metrics and pricing configurations.

import math
import logging
from typing import Dict, Any, Optional, Union

logger = logging.getLogger(__name__)

# Define a type alias for pricing configuration for clarity
PricingConfig = Dict[str, Any]
ModelPricingDetails = PricingConfig

MINIMUM_CREDITS_CHARGED = 1

class BillingError(Exception):
    """Custom exception for billing related errors."""
    pass

# A constant representing the value of one credit in USD.
# This is based on the standard pricing tier of 110,000 credits for $110.
USD_PER_CREDIT = 0.001

def get_usd_per_credit() -> float:
    """
    Returns the fixed USD value per credit.
    """
    return USD_PER_CREDIT

def calculate_real_and_charged_costs(
    input_tokens: int,
    output_tokens: int,
    model_pricing_details: ModelPricingDetails,
    total_credits_charged: int,
    pricing_config: PricingConfig,
) -> Dict[str, float]:
    """
    Calculates the real cost of the LLM call and the cost charged to the user.
    """
    costs = model_pricing_details.get("costs", {})
    input_cost_config = costs.get("input_per_million_token", {})
    output_cost_config = costs.get("output_per_million_token", {})

    input_price_per_million = input_cost_config.get("price", 0)
    output_price_per_million = output_cost_config.get("price", 0)

    real_input_cost = (input_tokens / 1_000_000) * input_price_per_million
    real_output_cost = (output_tokens / 1_000_000) * output_price_per_million
    real_total_cost = real_input_cost + real_output_cost

    usd_per_credit = get_usd_per_credit()
    charged_cost_usd = total_credits_charged * usd_per_credit
    
    margin = charged_cost_usd - real_total_cost

    return {
        "real_cost_usd": real_total_cost,
        "charged_cost_usd": charged_cost_usd,
        "margin_usd": margin,
    }

def calculate_credits_from_tokens(
    input_tokens: int,
    output_tokens: int,
    pricing_details: ModelPricingDetails
) -> float:
    """
    Calculates credits based on input and output tokens and their respective pricing.
    Handles cases where output_tokens is 0 (e.g., for interruptions after input is processed).
    """
    credits = 0.0
    token_pricing = pricing_details.get("tokens")
    if not token_pricing:
        return 0.0

    input_pricing = token_pricing.get("input", {})
    output_pricing = token_pricing.get("output", {})

    input_per_credit_unit = input_pricing.get("per_credit_unit")
    output_per_credit_unit = output_pricing.get("per_credit_unit")

    if input_per_credit_unit and input_per_credit_unit > 0:
        credits += (input_tokens / input_per_credit_unit)
    
    if output_tokens > 0 and output_per_credit_unit and output_per_credit_unit > 0:
        credits += (output_tokens / output_per_credit_unit)
        
    return credits

def calculate_credits_from_units(
    units: int,
    pricing_details: ModelPricingDetails
) -> float:
    """
    Calculates credits based on units processed (e.g., images, API calls).
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
    """
    fixed_pricing = pricing_details.get("fixed")
    if fixed_pricing and fixed_pricing.get("credits") is not None:
        return float(fixed_pricing.get("credits", 0))
    return 0.0


def calculate_total_credits(
    *,  # Force keyword arguments
    pricing_config: PricingConfig,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    units_processed: Optional[int] = None,
    duration_minutes: Optional[float] = None,
) -> int:
    """
    Calculates the total credits for a skill execution based on its pricing config and usage metrics.
    Rounds down to the nearest whole credit, but ensures a minimum of 1 credit is charged if any cost is incurred.
    """
    if not pricing_config:
        return 0

    # If the pricing_config contains a 'pricing' key, use that as the basis for calculation.
    # This handles cases where the full model pricing details are passed.
    pricing_rules = pricing_config.get("pricing", pricing_config)

    raw_credits = 0.0

    if "fixed" in pricing_rules:
        raw_credits += calculate_fixed_credits(pricing_rules)

    if "tokens" in pricing_rules and input_tokens is not None:
        # Ensure output_tokens is at least 0 if not provided
        output_tokens = output_tokens if output_tokens is not None else 0
        raw_credits += calculate_credits_from_tokens(input_tokens, output_tokens, pricing_rules)

    if "per_unit" in pricing_rules and units_processed is not None:
        raw_credits += calculate_credits_from_units(units_processed, pricing_rules)

    if "per_minute" in pricing_rules and duration_minutes is not None:
        raw_credits += calculate_credits_from_duration(duration_minutes, pricing_rules)

    # Floor the raw credits to round down.
    final_credits = math.floor(raw_credits)

    # If the result is 0 after flooring, but there was some cost, charge the minimum.
    if raw_credits > 0 and final_credits == 0:
        final_credits = MINIMUM_CREDITS_CHARGED
    
    logger.info(f"Calculated credits (raw: {raw_credits}, final: {final_credits}) for pricing config: {pricing_config}")

    return int(final_credits)
