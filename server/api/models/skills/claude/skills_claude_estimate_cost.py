from pydantic import BaseModel, Field, ConfigDict
from typing import List, Literal, Optional, Any, Callable
from models.skills.claude.skills_claude_ask import Usage, ClaudeAskInput, MessageItem, Tool
from pydantic import model_validator

class ClaudeEstimateCostInput(ClaudeAskInput):
    input_tokens: Optional[int] = Field(None, title="Input token count", description="The number of input tokens to estimate the cost for. If not provided, the cost will be estimated for the number of input tokens in the message.")
    output_tokens: Optional[int] = Field(None, title="Output token count", description="The number of output tokens to estimate the cost for. If not provided, the cost will be estimated for the number of output tokens in the message.")

    @model_validator(mode='after')
    def check_message_or_history(self):
        if self.message != None and self.message_history != None:
            raise ValueError("Only one of 'message' or 'message_history' should be provided.")
        if self.message == None and self.message_history == None and self.input_tokens == None and self.output_tokens == None:
            raise ValueError("Either 'message' or 'message_history' or 'input_tokens' or 'output_tokens' must be provided.")
        return self

class UsageCostEstimate(Usage):
    output_tokens: Optional[int] = Field(None, title="Number of output tokens")

class EstimatedCost(BaseModel):
    input_USD: float = Field(..., title="Input USD", description="Estimated cost for input tokens")
    output_USD: Optional[float] = Field(None, title="Output USD", description="Estimated cost for output tokens")
    output_100tokens_USD: Optional[float] = Field(None, title="Output 100 tokens USD", description="Estimated cost for 100 output tokens")
    output_500tokens_USD: Optional[float] = Field(None, title="Output 500 tokens USD", description="Estimated cost for 500 output tokens")
    output_2000tokens_USD: Optional[float] = Field(None, title="Output 2000 tokens USD", description="Estimated cost for 2000 output tokens")

class ClaudeEstimateCostOutput(BaseModel):
    usage: Usage
    estimated_cost: EstimatedCost

claude_estimate_cost_input_example = {
    "system": "You are a helpful assistant. Keep your answers short.",
    "message": "Whats the capital of Germany?",
    "ai_model": "claude-3-haiku"
}

claude_estimate_cost_output_example = {
    "usage": {"input_tokens": 50},
    "estimated_cost": {
        "input_USD": 0.0001,
        "output_USD": None,
        "output_100tokens_USD": 0.0002,
        "output_500tokens_USD": 0.001,
        "output_2000tokens_USD": 0.004
    }
}