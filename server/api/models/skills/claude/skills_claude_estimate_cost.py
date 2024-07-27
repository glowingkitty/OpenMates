from pydantic import BaseModel, Field, ConfigDict
from typing import List, Literal, Optional
from models.skills.claude.skills_claude_ask import ClaudeAskInput, MessageItem, Tool


class ClaudeEstimateCostInput(ClaudeAskInput):
    pass

class UsageCostEstimate(BaseModel):
    input_tokens: int

# TODO also optimize the other files with the models, to clearly define all fields and types

class EstimatedCost(BaseModel):
    input: float
    output_100tokens: float
    output_500tokens: float
    output_2000tokens: float

class ClaudeEstimateCostOutput(BaseModel):
    usage: UsageCostEstimate
    estimated_cost: EstimatedCost

claude_estimate_cost_input_example = {
    "system": "You are a helpful assistant. Keep your answers short.",
    "message": "Whats the capital of Germany?",
    "ai_model": "claude-3-haiku"
}

claude_estimate_cost_output_example = {
    "usage": {"input_tokens": 50},
    "estimated_cost": {
        "input": 0.0001,
        "output_100tokens": 0.0002,
        "output_500tokens": 0.001,
        "output_2000tokens": 0.004
    }
}