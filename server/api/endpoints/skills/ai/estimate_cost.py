################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server.api import *
################

from typing import List, Optional, Dict, Any
from server.api.models.skills.ai.skills_ai_estimate_cost import AiEstimateCostInput, AiEstimateCostOutput, EstimatedTotalCost
import json
import math
import tiktoken

# 1 USD = 10000 credits
pricing = {
    "claude-3-haiku": 12500,  # Cost in credits per 1M tokens
    "claude-3-sonnet": 150000,  # Cost in credits per 1M tokens
    "gpt-4o-mini": 6000,  # Cost in credits per 1M tokens
    "gpt-4o": 100000  # Cost in credits per 1M tokens
}

def count_tokens(text: str) -> int:
    # Use tiktoken to count tokens
    encoding = tiktoken.get_encoding("cl100k_base")  # Explicitly specify the encoding
    tokens = encoding.encode(text)
    return len(tokens)  # Return the number of tokens

def calculate_cost(total_tokens: int, cost_per_1M_tokens: int) -> int:
    total_cost = math.ceil((total_tokens * cost_per_1M_tokens) / 1000000)
    return max(1, total_cost)  # Ensure minimum cost is 1 credit

def estimate_cost(
    token_count: Optional[int] = None,
    system: Optional[str] = None,
    message: Optional[str] = None,
    message_history: Optional[List[Dict[str, str]]] = None,
    provider: Dict[str, str] = None,
    temperature: float = 0.5,
    stream: bool = False,
    cache: bool = False,
    max_tokens: Optional[int] = None,
    stop_sequence: Optional[List[str]] = None,
    tools: Optional[List[Dict[str, Any]]] = None
) -> AiEstimateCostOutput:
    # Parse input into AiEstimateCostInput for validation
    input_data = AiEstimateCostInput(
        token_count=token_count,
        system=system,
        message=message,
        message_history=message_history,
        provider=provider,
        temperature=temperature,
        stream=stream,
        cache=cache,
        max_tokens=max_tokens,
        stop_sequence=stop_sequence,
        tools=tools
    )

    # Use token_count directly if provided
    if input_data.token_count and input_data.token_count > 0:
        total_tokens = input_data.token_count
    else:
        # Construct the input as the AI model would see it
        input_text = f"{input_data.system}\n\n"
        if input_data.message:
            input_text += input_data.message

        # Add tools if present
        if input_data.tools:
            input_text += "\n\nTools:\n"
            for tool in input_data.tools:
                tool_json = json.dumps(tool, ensure_ascii=False)
                input_text += f"{tool_json}\n"

        # Add message history if present
        if input_data.message_history:
            for m in input_data.message_history:
                input_text += f"\n\n{m['role'].capitalize()}: {m['content']}"

        # Count input tokens
        total_tokens = count_tokens(input_text)

    # Set pricing based on the model
    if input_data.provider.model in pricing:
        cost_per_1M_tokens = pricing[input_data.provider.model]
    else:
        raise ValueError(f"Unsupported model: {input_data.provider.model}")

    # Calculate costs for different output token amounts
    cost_100 = calculate_cost(total_tokens + 100, cost_per_1M_tokens)
    cost_500 = calculate_cost(total_tokens + 500, cost_per_1M_tokens)
    cost_2000 = calculate_cost(total_tokens + 2000, cost_per_1M_tokens)

    # Calculate cost for input tokens alone
    input_token_cost = calculate_cost(total_tokens, cost_per_1M_tokens)

    return AiEstimateCostOutput(
        total_credits_cost_estimated=EstimatedTotalCost(
            credits_for_input_tokens=input_token_cost,
            credits_for_input_plus_100_output_tokens=cost_100,
            credits_for_input_plus_500_output_tokens=cost_500,
            credits_for_input_plus_2000_output_tokens=cost_2000
        )
    )