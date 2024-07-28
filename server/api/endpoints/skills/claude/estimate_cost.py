from anthropic import Anthropic
import json
from typing import List
from server.api.models.skills.claude.skills_claude_estimate_cost import ClaudeEstimateCostOutput, UsageCostEstimate, EstimatedCost, Tool, MessageItem

def estimate_cost(
        input_tokens: int,
        output_tokens: int,
        system: str,
        message: str,
        message_history: List[MessageItem],
        tools: List[Tool],
        ai_model: str = "claude-3.5-sonnet"
    ) -> ClaudeEstimateCostOutput:
    # Use provided token counts if available
    if input_tokens or output_tokens:
        total_estimated_tokens = input_tokens
    else:
        client = Anthropic()

        # Construct the input as Claude would see it
        input_text = f"{system}\n\n{message}"

        # Add tools
        if tools:
            input_text += "\n\nTools:\n"
            for tool in tools:
                tool_json = json.dumps(tool.model_dump(), ensure_ascii=False)
                input_text += f"{tool_json}\n"

        # Add message history
        if message_history:
            for m in message_history:
                input_text += f"\n\n{m.role.capitalize()}: {m.content}"

        # Use Anthropic's token counter
        input_tokens = client.count_tokens(input_text)

        # Update estimate by considering tools as well, and prefer to overestimate the costs instead of underestimating
        if tools:
            estimated_tool_instruction_tokens = len(tools) * 125  # Assuming ~125 tokens per tool

            total_estimated_tokens = input_tokens + round(estimated_tool_instruction_tokens * 1.2)
        else:
            total_estimated_tokens = round(input_tokens * 1.2)

    # Set pricing based on the model
    if ai_model == "claude-3.5-sonnet":
        input_cost_per_token = 3/1000000  # $3 per 1M tokens
        output_cost_per_token = 15/1000000  # $15 per 1M tokens
    elif ai_model == "claude-3-haiku":
        input_cost_per_token = 0.25/1000000  # $0.25 per 1M tokens
        output_cost_per_token = 1.25/1000000  # $1.25 per 1M tokens
    else:
        raise ValueError(f"Unsupported model: {ai_model}")

    input_cost = total_estimated_tokens * input_cost_per_token
    output_cost = output_tokens * output_cost_per_token if output_tokens else None

    return ClaudeEstimateCostOutput(
        usage=UsageCostEstimate(input_tokens=total_estimated_tokens, output_tokens=output_tokens),
        estimated_cost=EstimatedCost(
            input_USD=round(input_cost, 6),
            output_USD=round(output_cost, 6) if output_cost else None,
            output_100tokens_USD=round(100 * output_cost_per_token, 6) if not output_cost else None,
            output_500tokens_USD=round(500 * output_cost_per_token, 6) if not output_cost else None,
            output_2000tokens_USD=round(2000 * output_cost_per_token, 6) if not output_cost else None
        )
    )