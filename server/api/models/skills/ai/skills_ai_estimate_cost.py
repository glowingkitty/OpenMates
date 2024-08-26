################
# Default Imports
################
import sys
import os
import re
from typing import Optional

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from pydantic import BaseModel, Field
from server.api.models.skills.ai.skills_ai_ask import AiAskInput

class AiEstimateCostInput(AiAskInput):
    token_count: Optional[int] = Field(None, title="Token Count", description="Number of tokens for which the cost is being estimated")

    class Config:
        extra = "forbid"

class EstimatedTotalCost(BaseModel):
    credits_for_100_output_tokens: int = Field(..., title="Estimated Cost for 100 Output Tokens", description="Estimated total cost in credits for the operation")
    credits_for_500_output_tokens: int = Field(..., title="Estimated Cost for 500 Output Tokens", description="Estimated total cost in credits for the operation")
    credits_for_2000_output_tokens: int = Field(..., title="Estimated Cost for 2000 Output Tokens", description="Estimated total cost in credits for the operation")

class AiEstimateCostOutput(BaseModel):
    estimated_total_cost: EstimatedTotalCost = Field(..., title="Estimated Total Cost", description="Estimated total cost in credits for the operation")

ai_estimate_cost_input_example = {
    "system": "You are a helpful assistant. Keep your answers short.",
    "message": "What's the capital of Germany?",
    "provider": {
        "name": "claude",
        "model": "claude-3-haiku"
    },
    "temperature": 0.5
}

ai_estimate_cost_output_example = {
    "estimated_total_cost": {
        "credits_for_100_output_tokens": 2,
        "credits_for_500_output_tokens": 7,
        "credits_for_2000_output_tokens": 25
    }
}