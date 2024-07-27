from server.api.models.skills.claude.skills_claude_estimate_cost import ClaudeEstimateCostOutput, UsageCostEstimate, EstimatedCost
from typing import List
from server.api.models.skills.claude.skills_claude_estimate_cost import Tool, MessageItem
import tiktoken

async def estimate_cost(
        system: str,
        message: str,
        message_history: List[MessageItem],
        tools: List[Tool]
    ) -> ClaudeEstimateCostOutput:

    # Calculate input tokens
    input_text = system + message + ''.join([f"{m.role}: {m.content}" for m in message_history])
    for tool in tools:
        input_text += str(tool.dict())

    # Use tiktoken to count tokens
    enc = tiktoken.encoding_for_model("claude-2")
    input_tokens = len(enc.encode(input_text))

    # Calculate costs (these are example rates, adjust as needed)
    input_cost_per_token = 0.00001  # $0.01 per 1000 tokens
    output_cost_per_token = 0.00003  # $0.03 per 1000 tokens

    input_cost = input_tokens * input_cost_per_token
    output_cost_100 = 100 * output_cost_per_token
    output_cost_500 = 500 * output_cost_per_token
    output_cost_2000 = 2000 * output_cost_per_token

    # TODO also return in other api endpoints the class and not a json (so type validation works)
    return ClaudeEstimateCostOutput(
        usage=UsageCostEstimate(input_tokens=input_tokens),
        estimated_cost=EstimatedCost(
            input=round(input_cost, 6),
            output_100tokens=round(output_cost_100, 6),
            output_500tokens=round(output_cost_500, 6),
            output_2000tokens=round(output_cost_2000, 6)
        )
    )