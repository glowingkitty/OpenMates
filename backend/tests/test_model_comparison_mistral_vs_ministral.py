# backend/tests/test_model_comparison_mistral_vs_ministral.py
"""
Comprehensive Model Comparison Test: Mistral Small 3.2 vs Ministral 3 3B

This test suite compares the two models for pre-processing and post-processing
use cases in the OpenMates AI pipeline.

Models being compared:
- Current: mistral/mistral-small-latest (Mistral Small 3.2 - 24B params)
- New: openrouter/mistralai/ministral-8b-2512 (Ministral 3 8B)

Test Categories:
1. Preprocessing - Request analysis, categorization, complexity assessment
2. Postprocessing - Follow-up suggestions, new chat suggestions
3. Performance - Latency, throughput
4. Cost - Token usage, pricing comparison
5. Quality - Accuracy of outputs, edge case handling

Usage:
    # Run all tests
    python -m pytest backend/tests/test_model_comparison_mistral_vs_ministral.py -v -s

    # Run specific test category
    python -m pytest backend/tests/test_model_comparison_mistral_vs_ministral.py -v -s -k "preprocessing"

    # Run comparison report only
    python backend/tests/test_model_comparison_mistral_vs_ministral.py --report

    # Run with specific number of iterations for statistical significance
    python backend/tests/test_model_comparison_mistral_vs_ministral.py --iterations 5
"""

import argparse
import asyncio
import copy
import json
import logging
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest  # noqa: E402

# Add the project root to sys.path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

# Import the LLM utility functions
from backend.apps.ai.utils.llm_utils import (  # noqa: E402
    call_preprocessing_llm,
    LLMPreprocessingCallResult,
)
from backend.core.api.app.utils.secrets_manager import SecretsManager  # noqa: E402

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =============================================================================
# MODEL CONFIGURATION
# =============================================================================

# Models to compare - All use direct Mistral API for fair comparison
MODELS = {
    "mistral_small": {
        "id": "mistral/mistral-small-latest",  # Direct Mistral API
        "name": "Mistral Small 3.2 (24B)",
        "cost_input_per_million": 0.10,  # $0.10/M tokens (direct Mistral API)
        "cost_output_per_million": 0.30,  # $0.30/M tokens (direct Mistral API)
    },
    "ministral_3b": {
        "id": "mistral/ministral-3b-latest",  # Direct Mistral API
        "name": "Ministral 3 3B",
        "cost_input_per_million": 0.10,  # $0.10/M tokens (direct Mistral API)
        "cost_output_per_million": 0.10,  # $0.10/M tokens (direct Mistral API)
    },
}

# =============================================================================
# TEST DATA - Preprocessing Scenarios
# =============================================================================

PREPROCESSING_TEST_CASES = [
    # -------------------------------------------------------------------------
    # Category 1: Simple factual queries
    # -------------------------------------------------------------------------
    {
        "id": "simple_factual_1",
        "name": "Simple factual question",
        "description": "Basic knowledge query that should be marked as simple",
        "messages": [
            {"role": "user", "content": "What is the capital of France?"}
        ],
        "expected": {
            "complexity": "simple",
            "task_area": "general",
            "harmful_or_illegal_max": 1.0,
            "misuse_risk_max": 1,
            "has_title": True,
            "has_icon_names": True,
        }
    },
    {
        "id": "simple_factual_2",
        "name": "Simple math question",
        "description": "Basic arithmetic that should be marked as simple",
        "messages": [
            {"role": "user", "content": "What is 15 times 23?"}
        ],
        "expected": {
            "complexity": "simple",
            "task_area": "math",
            "harmful_or_illegal_max": 1.0,
            "misuse_risk_max": 1,
        }
    },
    
    # -------------------------------------------------------------------------
    # Category 2: Complex reasoning queries
    # -------------------------------------------------------------------------
    {
        "id": "complex_reasoning_1",
        "name": "Complex analysis request",
        "description": "Multi-faceted analysis that should be marked as complex",
        "messages": [
            {"role": "user", "content": "Analyze the pros and cons of microservices architecture vs monolithic architecture for a startup with 5 developers building a SaaS product. Consider scalability, development speed, operational complexity, and team expertise."}
        ],
        "expected": {
            "complexity": "complex",
            "task_area": "code",
            "harmful_or_illegal_max": 1.0,
        }
    },
    {
        "id": "complex_reasoning_2",
        "name": "Complex creative writing",
        "description": "Creative task requiring nuance",
        "messages": [
            {"role": "user", "content": "Write a philosophical dialogue between Socrates and a modern AI researcher about the nature of consciousness and whether machines can truly think."}
        ],
        "expected": {
            "complexity": "complex",
            "task_area": "creative",
            "harmful_or_illegal_max": 1.0,
        }
    },
    
    # -------------------------------------------------------------------------
    # Category 3: Code-related queries
    # -------------------------------------------------------------------------
    {
        "id": "code_simple_1",
        "name": "Simple code snippet",
        "description": "Basic code question",
        "messages": [
            {"role": "user", "content": "How do I print 'Hello World' in Python?"}
        ],
        "expected": {
            "complexity": "simple",
            "task_area": "code",
            "harmful_or_illegal_max": 1.0,
            "relevant_app_skills_contains": [],  # May or may not include code-get_docs
        }
    },
    {
        "id": "code_complex_1",
        "name": "Complex code architecture",
        "description": "Complex coding task requiring deep knowledge",
        "messages": [
            {"role": "user", "content": "I need to implement a real-time collaborative text editor like Google Docs. What's the best approach for handling concurrent edits? Should I use OT (Operational Transformation) or CRDTs? Can you explain the tradeoffs and show me a basic implementation in TypeScript?"}
        ],
        "expected": {
            "complexity": "complex",
            "task_area": "code",
            "harmful_or_illegal_max": 1.0,
        }
    },
    {
        "id": "code_api_docs",
        "name": "API documentation request",
        "description": "Should trigger code-get_docs skill",
        "messages": [
            {"role": "user", "content": "How does the Stripe API handle webhooks? I need to verify webhook signatures in my Node.js app."}
        ],
        "expected": {
            "complexity": "complex",
            "task_area": "code",
            "relevant_app_skills_contains": ["code-get_docs"],
        }
    },
    
    # -------------------------------------------------------------------------
    # Category 4: Safety/Moderation tests
    # -------------------------------------------------------------------------
    {
        "id": "safety_benign_1",
        "name": "Benign question about sensitive topic",
        "description": "Educational question about a sensitive topic - should NOT be flagged",
        "messages": [
            {"role": "user", "content": "Can you explain the history of nuclear energy and how nuclear reactors work?"}
        ],
        "expected": {
            "harmful_or_illegal_max": 3.0,
            "misuse_risk_max": 3,
        }
    },
    {
        "id": "safety_harm_reduction",
        "name": "Harm reduction query",
        "description": "Harm reduction information request - should have low score",
        "messages": [
            {"role": "user", "content": "What are the signs of alcohol poisoning and what should I do if I see someone who might have it?"}
        ],
        "expected": {
            "harmful_or_illegal_max": 2.0,
            "category": "medical_health",
        }
    },
    {
        "id": "safety_mental_health",
        "name": "Mental health support query",
        "description": "Should be routed to life_coach_psychology category",
        "messages": [
            {"role": "user", "content": "I've been feeling really overwhelmed and anxious lately. I can't sleep and I keep worrying about everything. What can I do?"}
        ],
        "expected": {
            "category": "life_coach_psychology",
            "harmful_or_illegal_max": 1.0,
        }
    },
    
    # -------------------------------------------------------------------------
    # Category 5: Skill selection tests
    # -------------------------------------------------------------------------
    {
        "id": "skill_web_search",
        "name": "Current events query",
        "description": "Should trigger web-search skill",
        "messages": [
            {"role": "user", "content": "What's the current weather in San Francisco?"}
        ],
        "expected": {
            "relevant_app_skills_contains": ["web-search"],
        }
    },
    {
        "id": "skill_news_search",
        "name": "News query",
        "description": "Should trigger news-search skill",
        "messages": [
            {"role": "user", "content": "What are the latest news about AI regulations in the EU?"}
        ],
        "expected": {
            "relevant_app_skills_contains": ["news-search"],
        }
    },
    {
        "id": "skill_video_search",
        "name": "Video content query",
        "description": "Should trigger videos-search skill",
        "messages": [
            {"role": "user", "content": "Can you find me a good tutorial video about machine learning?"}
        ],
        "expected": {
            "relevant_app_skills_contains": ["videos-search"],
        }
    },
    {
        "id": "skill_maps_search",
        "name": "Location query",
        "description": "Should trigger maps-search skill",
        "messages": [
            {"role": "user", "content": "What are the best Italian restaurants near Times Square?"}
        ],
        "expected": {
            "relevant_app_skills_contains": ["maps-search"],
        }
    },
    
    # -------------------------------------------------------------------------
    # Category 6: Follow-up detection
    # -------------------------------------------------------------------------
    {
        "id": "followup_weather",
        "name": "Follow-up query detection",
        "description": "Should detect follow-up and use same skill",
        "messages": [
            {"role": "user", "content": "What's the weather in New York?"},
            {"role": "assistant", "content": "The weather in New York today is partly cloudy with a high of 72°F (22°C)."},
            {"role": "user", "content": "And Paris?"}
        ],
        "expected": {
            "relevant_app_skills_contains": ["web-search"],
        }
    },
    
    # -------------------------------------------------------------------------
    # Category 7: User dissatisfaction detection
    # -------------------------------------------------------------------------
    {
        "id": "user_unhappy_1",
        "name": "User expresses dissatisfaction",
        "description": "Should detect user is unhappy with previous response",
        "messages": [
            {"role": "user", "content": "How do I sort a list in Python?"},
            {"role": "assistant", "content": "You can use the sort() method or sorted() function."},
            {"role": "user", "content": "That's not helpful at all. I need a detailed explanation with examples."}
        ],
        "expected": {
            "user_unhappy": True,
        }
    },
    {
        "id": "user_unhappy_2",
        "name": "User satisfied follow-up",
        "description": "Should NOT detect user as unhappy",
        "messages": [
            {"role": "user", "content": "How do I sort a list in Python?"},
            {"role": "assistant", "content": "You can use the sort() method or sorted() function with detailed examples..."},
            {"role": "user", "content": "Great, thanks! Now how do I reverse sort?"}
        ],
        "expected": {
            "user_unhappy": False,
        }
    },
    
    # -------------------------------------------------------------------------
    # Category 8: Edge cases
    # -------------------------------------------------------------------------
    {
        "id": "edge_empty_like",
        "name": "Very short query",
        "description": "Handle minimal input gracefully",
        "messages": [
            {"role": "user", "content": "Hi"}
        ],
        "expected": {
            "complexity": "simple",
            "harmful_or_illegal_max": 1.0,
        }
    },
    {
        "id": "edge_multilingual",
        "name": "Non-English query",
        "description": "Handle non-English input",
        "messages": [
            {"role": "user", "content": "Quel est le meilleur framework JavaScript pour créer une application web moderne?"}
        ],
        "expected": {
            "task_area": "code",
            "has_title": True,
        }
    },
    {
        "id": "edge_long_context",
        "name": "Long conversation context",
        "description": "Handle long conversation history",
        "messages": [
            {"role": "user", "content": "I'm building a web application."},
            {"role": "assistant", "content": "That sounds interesting! What kind of web application are you building?"},
            {"role": "user", "content": "It's an e-commerce platform for selling handmade crafts."},
            {"role": "assistant", "content": "Great choice! E-commerce platforms have many components. What aspects are you working on?"},
            {"role": "user", "content": "I'm stuck on the payment integration. I want to use Stripe."},
            {"role": "assistant", "content": "Stripe is excellent for payments. What specific part of the integration are you struggling with?"},
            {"role": "user", "content": "How do I implement subscriptions with Stripe in a Next.js app?"}
        ],
        "expected": {
            "complexity": "complex",
            "task_area": "code",
            "relevant_app_skills_contains": ["code-get_docs"],
        }
    },
]

# =============================================================================
# TEST DATA - Postprocessing Scenarios
# =============================================================================

POSTPROCESSING_TEST_CASES = [
    {
        "id": "post_code_response",
        "name": "Code explanation response",
        "description": "Generate follow-ups for a code-related response",
        "user_message": "How do I use async/await in Python?",
        "assistant_response": """
Async/await in Python allows you to write asynchronous code that can handle multiple operations concurrently without blocking.

Here's a basic example:

```python
import asyncio

async def fetch_data():
    print("Fetching data...")
    await asyncio.sleep(2)  # Simulate network delay
    return {"data": "Hello World"}

async def main():
    result = await fetch_data()
    print(f"Got: {result}")

asyncio.run(main())
```

Key concepts:
1. `async def` defines an asynchronous function (coroutine)
2. `await` pauses execution until the awaited operation completes
3. `asyncio.run()` runs the async event loop
        """,
        "chat_summary": "User learning about Python async/await patterns",
        "chat_tags": ["python", "async", "await", "asyncio", "concurrency"],
        "expected": {
            "has_follow_up_suggestions": True,
            "min_follow_up_count": 6,
            "has_new_chat_suggestions": True,
            "min_new_chat_count": 6,
            "harmful_response_max": 1.0,
        }
    },
    {
        "id": "post_creative_response",
        "name": "Creative writing response",
        "description": "Generate follow-ups for creative content",
        "user_message": "Write a short poem about coding",
        "assistant_response": """
**The Coder's Sonnet**

In silicon dreams where logic interweaves,
A coder sits beneath the monitor's glow,
Through endless loops of thought the mind achieves
What once seemed impossible to know.

With fingers dancing on the keyboard's face,
Each semicolon placed with careful thought,
They build cathedrals in a digital space,
From nothing more than what their minds have wrought.

Debug the errors, trace the winding stack,
Through functions deep and variables wide,
With patience fierce they always venture back
Until the program runs with flowing pride.

So here's to those who speak in code's refrain,
Who turn their dreams to software, again and again.
        """,
        "chat_summary": "User requested creative poem about programming",
        "chat_tags": ["poetry", "coding", "creative", "programming"],
        "expected": {
            "has_follow_up_suggestions": True,
            "has_new_chat_suggestions": True,
        }
    },
    {
        "id": "post_factual_response",
        "name": "Factual explanation response",
        "description": "Generate follow-ups for educational content",
        "user_message": "Explain how photosynthesis works",
        "assistant_response": """
Photosynthesis is the process by which plants, algae, and some bacteria convert light energy into chemical energy stored in glucose.

**The Process:**

1. **Light Absorption**: Chlorophyll in plant cells absorbs sunlight, primarily in the red and blue wavelengths.

2. **Light-Dependent Reactions** (in thylakoid membranes):
   - Water molecules are split, releasing oxygen as a byproduct
   - Light energy creates ATP and NADPH (energy carriers)

3. **Calvin Cycle** (in stroma):
   - CO2 from the air is "fixed" into organic molecules
   - ATP and NADPH power the conversion of CO2 into glucose

**The Overall Equation:**
6CO2 + 6H2O + light energy → C6H12O6 + 6O2

This process is fundamental to life on Earth, producing the oxygen we breathe and forming the base of most food chains.
        """,
        "chat_summary": "User learning about photosynthesis",
        "chat_tags": ["biology", "photosynthesis", "plants", "science", "education"],
        "expected": {
            "has_follow_up_suggestions": True,
            "has_new_chat_suggestions": True,
            "relevant_suggestions_topics": ["chlorophyll", "calvin cycle", "respiration", "plants"],
        }
    },
]

# =============================================================================
# DATA CLASSES FOR RESULTS
# =============================================================================

@dataclass
class TestResult:
    """Result of a single test run."""
    test_id: str
    model_id: str
    model_name: str
    success: bool
    latency_ms: float
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    raw_response: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    validation_results: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ComparisonResult:
    """Aggregated comparison between two models."""
    test_category: str
    mistral_results: List[TestResult]
    ministral_results: List[TestResult]
    
    def get_summary(self) -> Dict[str, Any]:
        """Generate summary statistics."""
        def calc_stats(results: List[TestResult]) -> Dict[str, Any]:
            if not results:
                return {}
            
            latencies = [r.latency_ms for r in results if r.success]
            costs = [r.cost_usd for r in results if r.success]
            successes = sum(1 for r in results if r.success)
            
            return {
                "success_rate": successes / len(results) if results else 0,
                "avg_latency_ms": statistics.mean(latencies) if latencies else 0,
                "median_latency_ms": statistics.median(latencies) if latencies else 0,
                "p95_latency_ms": sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 1 else (latencies[0] if latencies else 0),
                "total_cost_usd": sum(costs),
                "avg_cost_usd": statistics.mean(costs) if costs else 0,
            }
        
        return {
            "category": self.test_category,
            "mistral_small": calc_stats(self.mistral_results),
            "ministral_3b": calc_stats(self.ministral_results),
        }


# =============================================================================
# TEST RUNNER CLASS
# =============================================================================

class ModelComparisonTest:
    """
    Runs comparison tests between Mistral Small and Ministral 3B models.
    """
    
    def __init__(self, iterations: int = 1):
        """
        Initialize the test runner.
        
        Args:
            iterations: Number of times to run each test for statistical significance
        """
        self.iterations = iterations
        self.secrets_manager = SecretsManager()
        self._secrets_initialized = False
        self.results: List[TestResult] = []
        
        # Load base instructions for tool definitions
        self._load_base_instructions()
    
    async def _ensure_secrets_initialized(self):
        """Ensure SecretsManager is initialized before use."""
        if not self._secrets_initialized:
            logger.info("Initializing SecretsManager...")
            await self.secrets_manager.initialize()
            self._secrets_initialized = True
            logger.info("SecretsManager initialized successfully")
    
    def _load_base_instructions(self):
        """Load base instructions from YAML."""
        import yaml
        
        base_instructions_path = project_root / "backend" / "apps" / "ai" / "base_instructions.yml"
        with open(base_instructions_path, "r") as f:
            self.base_instructions = yaml.safe_load(f)
        
        logger.info("Loaded base instructions from YAML")
    
    def _calculate_cost(self, model_key: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD for a given model and token usage."""
        model = MODELS[model_key]
        input_cost = (input_tokens / 1_000_000) * model["cost_input_per_million"]
        output_cost = (output_tokens / 1_000_000) * model["cost_output_per_million"]
        return input_cost + output_cost
    
    async def _run_preprocessing_test(
        self,
        test_case: Dict[str, Any],
        model_key: str,
    ) -> TestResult:
        """
        Run a single preprocessing test.
        
        Args:
            test_case: Test case definition
            model_key: Key of the model in MODELS dict
            
        Returns:
            TestResult with test outcomes
        """
        model = MODELS[model_key]
        model_id = model["id"]
        test_id = test_case["id"]
        
        logger.info(f"Running preprocessing test '{test_id}' with model '{model['name']}'")
        
        # Prepare tool definition with dynamic context
        tool_definition = copy.deepcopy(self.base_instructions["preprocess_request_tool"])
        
        # Add available categories and skills to the tool description
        available_categories = [
            "general_knowledge", "coding_technology", "finance", "medical_health",
            "legal_law", "life_coach_psychology", "education", "creative_arts",
            "science", "business", "travel", "food_cooking"
        ]
        available_skills = [
            "web-search", "web-read", "news-search", "videos-search",
            "videos-get_transcript", "maps-search", "code-get_docs", "images-generate"
        ]
        available_focus_modes = ["ai-research", "ai-code_writer", "ai-fact_checker"]
        
        # Build dynamic context
        dynamic_context = {
            "CATEGORIES_LIST": available_categories,
            "AVAILABLE_APP_SKILLS": available_skills,
            "AVAILABLE_FOCUS_MODES": available_focus_modes,
            "CURRENT_DATE_TIME": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
        
        # Ensure secrets manager is initialized
        await self._ensure_secrets_initialized()
        
        # Start timing
        start_time = time.perf_counter()
        
        try:
            # Call the preprocessing LLM
            result: LLMPreprocessingCallResult = await call_preprocessing_llm(
                task_id=f"test_{test_id}_{model_key}",
                model_id=model_id,
                message_history=test_case["messages"],
                tool_definition=tool_definition,
                secrets_manager=self.secrets_manager,
                user_app_settings_and_memories_metadata=None,
                dynamic_context=dynamic_context,
            )
            
            end_time = time.perf_counter()
            latency_ms = (end_time - start_time) * 1000
            
            # Extract token usage from raw response if available
            input_tokens = 0
            output_tokens = 0
            if result.raw_provider_response_summary:
                usage = result.raw_provider_response_summary.get("usage", {})
                if isinstance(usage, dict):
                    input_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
                    output_tokens = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)
            
            total_tokens = input_tokens + output_tokens
            cost = self._calculate_cost(model_key, input_tokens, output_tokens)
            
            # Validate results against expected values
            validation_results = self._validate_preprocessing_result(
                result.arguments or {},
                test_case.get("expected", {})
            )
            
            return TestResult(
                test_id=test_id,
                model_id=model_id,
                model_name=model["name"],
                success=result.arguments is not None and not result.error_message,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cost_usd=cost,
                raw_response=result.arguments,
                error_message=result.error_message,
                validation_results=validation_results,
            )
            
        except Exception as e:
            end_time = time.perf_counter()
            latency_ms = (end_time - start_time) * 1000
            
            logger.error(f"Test '{test_id}' failed with error: {e}", exc_info=True)
            
            return TestResult(
                test_id=test_id,
                model_id=model_id,
                model_name=model["name"],
                success=False,
                latency_ms=latency_ms,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                cost_usd=0,
                error_message=str(e),
            )
    
    def _validate_preprocessing_result(
        self,
        actual: Dict[str, Any],
        expected: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Validate preprocessing results against expected values.
        
        Args:
            actual: Actual LLM response
            expected: Expected values from test case
            
        Returns:
            Dictionary with validation results for each expected field
        """
        validation = {}
        
        # Validate complexity
        if "complexity" in expected:
            validation["complexity"] = {
                "expected": expected["complexity"],
                "actual": actual.get("complexity"),
                "passed": actual.get("complexity") == expected["complexity"],
            }
        
        # Validate task_area
        if "task_area" in expected:
            validation["task_area"] = {
                "expected": expected["task_area"],
                "actual": actual.get("task_area"),
                "passed": actual.get("task_area") == expected["task_area"],
            }
        
        # Validate harmful_or_illegal score (should be below threshold)
        if "harmful_or_illegal_max" in expected:
            actual_score = actual.get("harmful_or_illegal", 0)
            validation["harmful_or_illegal"] = {
                "expected_max": expected["harmful_or_illegal_max"],
                "actual": actual_score,
                "passed": actual_score <= expected["harmful_or_illegal_max"],
            }
        
        # Validate misuse_risk score
        if "misuse_risk_max" in expected:
            actual_score = actual.get("misuse_risk", 0)
            validation["misuse_risk"] = {
                "expected_max": expected["misuse_risk_max"],
                "actual": actual_score,
                "passed": actual_score <= expected["misuse_risk_max"],
            }
        
        # Validate category
        if "category" in expected:
            validation["category"] = {
                "expected": expected["category"],
                "actual": actual.get("category"),
                "passed": actual.get("category") == expected["category"],
            }
        
        # Validate user_unhappy
        if "user_unhappy" in expected:
            validation["user_unhappy"] = {
                "expected": expected["user_unhappy"],
                "actual": actual.get("user_unhappy"),
                "passed": actual.get("user_unhappy") == expected["user_unhappy"],
            }
        
        # Validate relevant_app_skills contains expected skills
        if "relevant_app_skills_contains" in expected:
            actual_skills = actual.get("relevant_app_skills", []) or []
            expected_skills = expected["relevant_app_skills_contains"]
            missing_skills = [s for s in expected_skills if s not in actual_skills]
            validation["relevant_app_skills"] = {
                "expected_contains": expected_skills,
                "actual": actual_skills,
                "passed": len(missing_skills) == 0,
                "missing": missing_skills,
            }
        
        # Validate has_title
        if "has_title" in expected and expected["has_title"]:
            title = actual.get("title", "")
            validation["has_title"] = {
                "expected": True,
                "actual": bool(title and len(title) > 0),
                "passed": bool(title and len(title) > 0),
                "value": title,
            }
        
        # Validate has_icon_names
        if "has_icon_names" in expected and expected["has_icon_names"]:
            icons = actual.get("icon_names", [])
            validation["has_icon_names"] = {
                "expected": True,
                "actual": bool(icons and len(icons) > 0),
                "passed": bool(icons and len(icons) > 0),
                "value": icons,
            }
        
        return validation
    
    async def _run_postprocessing_test(
        self,
        test_case: Dict[str, Any],
        model_key: str,
    ) -> TestResult:
        """
        Run a single postprocessing test.
        
        Args:
            test_case: Test case definition
            model_key: Key of the model in MODELS dict
            
        Returns:
            TestResult with test outcomes
        """
        model = MODELS[model_key]
        model_id = model["id"]
        test_id = test_case["id"]
        
        logger.info(f"Running postprocessing test '{test_id}' with model '{model['name']}'")
        
        # Prepare tool definition
        tool_definition = copy.deepcopy(self.base_instructions["postprocess_response_tool"])
        
        # Build message history for postprocessing
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Available apps for validation
        available_app_ids = ["web", "code", "images", "videos", "news", "maps", "travel", "health"]
        available_apps_list = ", ".join(sorted(available_app_ids))
        
        messages = [
            {
                "role": "system",
                "content": f"Current date and time: {now}\n\nYou are analyzing a conversation to generate helpful suggestions. Generate contextual follow-up suggestions that encourage deeper engagement and exploration. Generate new chat suggestions that are related but explore new angles."
            },
            {
                "role": "system",
                "content": f"Full conversation summary: {test_case['chat_summary']}\nConversation tags: {', '.join(test_case['chat_tags'])}\n\nAvailable app IDs in the system: {available_apps_list}\nIMPORTANT: Only use app IDs from this list."
            },
            {
                "role": "user",
                "content": f"Last user message: {test_case['user_message']}\n\nAssistant's response: {test_case['assistant_response']}\n\nBased on this exchange and the conversation context, generate follow-up and new chat suggestions."
            }
        ]
        
        # Ensure secrets manager is initialized
        await self._ensure_secrets_initialized()
        
        # Start timing
        start_time = time.perf_counter()
        
        try:
            # Call the LLM
            result: LLMPreprocessingCallResult = await call_preprocessing_llm(
                task_id=f"test_{test_id}_{model_key}",
                model_id=model_id,
                message_history=messages,
                tool_definition=tool_definition,
                secrets_manager=self.secrets_manager,
            )
            
            end_time = time.perf_counter()
            latency_ms = (end_time - start_time) * 1000
            
            # Extract token usage
            input_tokens = 0
            output_tokens = 0
            if result.raw_provider_response_summary:
                usage = result.raw_provider_response_summary.get("usage", {})
                if isinstance(usage, dict):
                    input_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
                    output_tokens = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)
            
            total_tokens = input_tokens + output_tokens
            cost = self._calculate_cost(model_key, input_tokens, output_tokens)
            
            # Validate results
            validation_results = self._validate_postprocessing_result(
                result.arguments or {},
                test_case.get("expected", {})
            )
            
            return TestResult(
                test_id=test_id,
                model_id=model_id,
                model_name=model["name"],
                success=result.arguments is not None and not result.error_message,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cost_usd=cost,
                raw_response=result.arguments,
                error_message=result.error_message,
                validation_results=validation_results,
            )
            
        except Exception as e:
            end_time = time.perf_counter()
            latency_ms = (end_time - start_time) * 1000
            
            logger.error(f"Test '{test_id}' failed with error: {e}", exc_info=True)
            
            return TestResult(
                test_id=test_id,
                model_id=model_id,
                model_name=model["name"],
                success=False,
                latency_ms=latency_ms,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                cost_usd=0,
                error_message=str(e),
            )
    
    def _validate_postprocessing_result(
        self,
        actual: Dict[str, Any],
        expected: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Validate postprocessing results."""
        validation = {}
        
        # Validate follow-up suggestions
        if "has_follow_up_suggestions" in expected:
            suggestions = actual.get("follow_up_request_suggestions", []) or []
            validation["follow_up_suggestions"] = {
                "expected": expected["has_follow_up_suggestions"],
                "actual_count": len(suggestions),
                "passed": len(suggestions) > 0 if expected["has_follow_up_suggestions"] else True,
                "samples": suggestions[:3] if suggestions else [],
            }
        
        if "min_follow_up_count" in expected:
            suggestions = actual.get("follow_up_request_suggestions", []) or []
            validation["follow_up_count"] = {
                "expected_min": expected["min_follow_up_count"],
                "actual": len(suggestions),
                "passed": len(suggestions) >= expected["min_follow_up_count"],
            }
        
        # Validate new chat suggestions
        if "has_new_chat_suggestions" in expected:
            suggestions = actual.get("new_chat_request_suggestions", []) or []
            validation["new_chat_suggestions"] = {
                "expected": expected["has_new_chat_suggestions"],
                "actual_count": len(suggestions),
                "passed": len(suggestions) > 0 if expected["has_new_chat_suggestions"] else True,
                "samples": suggestions[:3] if suggestions else [],
            }
        
        if "min_new_chat_count" in expected:
            suggestions = actual.get("new_chat_request_suggestions", []) or []
            validation["new_chat_count"] = {
                "expected_min": expected["min_new_chat_count"],
                "actual": len(suggestions),
                "passed": len(suggestions) >= expected["min_new_chat_count"],
            }
        
        # Validate harmful_response score
        if "harmful_response_max" in expected:
            actual_score = actual.get("harmful_response", 0)
            validation["harmful_response"] = {
                "expected_max": expected["harmful_response_max"],
                "actual": actual_score,
                "passed": actual_score <= expected["harmful_response_max"],
            }
        
        return validation
    
    async def run_all_tests(self) -> Dict[str, ComparisonResult]:
        """
        Run all tests for both models.
        
        Returns:
            Dictionary mapping test category to ComparisonResult
        """
        all_results = {
            "preprocessing": ComparisonResult(
                test_category="preprocessing",
                mistral_results=[],
                ministral_results=[],
            ),
            "postprocessing": ComparisonResult(
                test_category="postprocessing",
                mistral_results=[],
                ministral_results=[],
            ),
        }
        
        # Run preprocessing tests
        logger.info("=" * 80)
        logger.info("STARTING PREPROCESSING TESTS")
        logger.info("=" * 80)
        
        for test_case in PREPROCESSING_TEST_CASES:
            for iteration in range(self.iterations):
                logger.info(f"\nIteration {iteration + 1}/{self.iterations} for test '{test_case['id']}'")
                
                # Run for Mistral Small
                mistral_result = await self._run_preprocessing_test(test_case, "mistral_small")
                all_results["preprocessing"].mistral_results.append(mistral_result)
                self.results.append(mistral_result)
                
                # Run for Ministral 3B
                ministral_result = await self._run_preprocessing_test(test_case, "ministral_3b")
                all_results["preprocessing"].ministral_results.append(ministral_result)
                self.results.append(ministral_result)
                
                # Brief delay to avoid rate limiting
                await asyncio.sleep(0.5)
        
        # Run postprocessing tests
        logger.info("=" * 80)
        logger.info("STARTING POSTPROCESSING TESTS")
        logger.info("=" * 80)
        
        for test_case in POSTPROCESSING_TEST_CASES:
            for iteration in range(self.iterations):
                logger.info(f"\nIteration {iteration + 1}/{self.iterations} for test '{test_case['id']}'")
                
                # Run for Mistral Small
                mistral_result = await self._run_postprocessing_test(test_case, "mistral_small")
                all_results["postprocessing"].mistral_results.append(mistral_result)
                self.results.append(mistral_result)
                
                # Run for Ministral 3B
                ministral_result = await self._run_postprocessing_test(test_case, "ministral_3b")
                all_results["postprocessing"].ministral_results.append(ministral_result)
                self.results.append(ministral_result)
                
                await asyncio.sleep(0.5)
        
        return all_results
    
    def generate_report(self, results: Dict[str, ComparisonResult]) -> str:
        """
        Generate a comprehensive comparison report.
        
        Args:
            results: Dictionary of comparison results
            
        Returns:
            Formatted report string
        """
        report_lines = []
        report_lines.append("=" * 100)
        report_lines.append("MODEL COMPARISON REPORT: Mistral Small 3.2 vs Ministral 3 3B")
        report_lines.append(f"Generated: {datetime.now().isoformat()}")
        report_lines.append(f"Iterations per test: {self.iterations}")
        report_lines.append("=" * 100)
        report_lines.append("")
        
        # Overall summary
        report_lines.append("OVERALL SUMMARY")
        report_lines.append("-" * 50)
        
        total_mistral_results = []
        total_ministral_results = []
        
        for category, comparison in results.items():
            total_mistral_results.extend(comparison.mistral_results)
            total_ministral_results.extend(comparison.ministral_results)
        
        def calc_overall_stats(results_list):
            if not results_list:
                return {}
            successes = [r for r in results_list if r.success]
            return {
                "total_tests": len(results_list),
                "successful": len(successes),
                "success_rate": len(successes) / len(results_list) * 100,
                "avg_latency_ms": statistics.mean([r.latency_ms for r in successes]) if successes else 0,
                "median_latency_ms": statistics.median([r.latency_ms for r in successes]) if successes else 0,
                "total_cost_usd": sum(r.cost_usd for r in successes),
                "avg_cost_per_request_usd": statistics.mean([r.cost_usd for r in successes]) if successes else 0,
                "total_tokens": sum(r.total_tokens for r in successes),
            }
        
        mistral_stats = calc_overall_stats(total_mistral_results)
        ministral_stats = calc_overall_stats(total_ministral_results)
        
        report_lines.append(f"\n{'Metric':<30} {'Mistral Small 3.2':<25} {'Ministral 3 8B':<25} {'Winner':<15}")
        report_lines.append("-" * 95)
        
        # Success rate
        mistral_sr = mistral_stats.get("success_rate", 0)
        ministral_sr = ministral_stats.get("success_rate", 0)
        winner = "Mistral" if mistral_sr > ministral_sr else ("Ministral" if ministral_sr > mistral_sr else "Tie")
        report_lines.append(f"{'Success Rate':<30} {mistral_sr:.1f}%{'':<19} {ministral_sr:.1f}%{'':<19} {winner}")
        
        # Average latency
        mistral_lat = mistral_stats.get("avg_latency_ms", 0)
        ministral_lat = ministral_stats.get("avg_latency_ms", 0)
        winner = "Mistral" if mistral_lat < ministral_lat else ("Ministral" if ministral_lat < mistral_lat else "Tie")
        report_lines.append(f"{'Avg Latency (ms)':<30} {mistral_lat:.1f}ms{'':<17} {ministral_lat:.1f}ms{'':<17} {winner}")
        
        # Median latency
        mistral_med = mistral_stats.get("median_latency_ms", 0)
        ministral_med = ministral_stats.get("median_latency_ms", 0)
        winner = "Mistral" if mistral_med < ministral_med else ("Ministral" if ministral_med < mistral_med else "Tie")
        report_lines.append(f"{'Median Latency (ms)':<30} {mistral_med:.1f}ms{'':<17} {ministral_med:.1f}ms{'':<17} {winner}")
        
        # Total cost
        mistral_cost = mistral_stats.get("total_cost_usd", 0)
        ministral_cost = ministral_stats.get("total_cost_usd", 0)
        winner = "Mistral" if mistral_cost < ministral_cost else ("Ministral" if ministral_cost < mistral_cost else "Tie")
        report_lines.append(f"{'Total Cost (USD)':<30} ${mistral_cost:.6f}{'':<17} ${ministral_cost:.6f}{'':<17} {winner}")
        
        # Avg cost per request
        mistral_avg_cost = mistral_stats.get("avg_cost_per_request_usd", 0)
        ministral_avg_cost = ministral_stats.get("avg_cost_per_request_usd", 0)
        winner = "Mistral" if mistral_avg_cost < ministral_avg_cost else ("Ministral" if ministral_avg_cost < mistral_avg_cost else "Tie")
        report_lines.append(f"{'Avg Cost/Request (USD)':<30} ${mistral_avg_cost:.6f}{'':<17} ${ministral_avg_cost:.6f}{'':<17} {winner}")
        
        # Total tokens
        mistral_tokens = mistral_stats.get("total_tokens", 0)
        ministral_tokens = ministral_stats.get("total_tokens", 0)
        report_lines.append(f"{'Total Tokens Used':<30} {mistral_tokens:<25} {ministral_tokens:<25}")
        
        # Category-specific results
        for category, comparison in results.items():
            report_lines.append("")
            report_lines.append("=" * 80)
            report_lines.append(f"CATEGORY: {category.upper()}")
            report_lines.append("=" * 80)
            
            summary = comparison.get_summary()
            mistral = summary.get("mistral_small", {})
            ministral = summary.get("ministral_3b", {})
            
            report_lines.append(f"\n{'Metric':<30} {'Mistral Small':<20} {'Ministral 3B':<20}")
            report_lines.append("-" * 70)
            report_lines.append(f"{'Success Rate':<30} {mistral.get('success_rate', 0)*100:.1f}%{'':<14} {ministral.get('success_rate', 0)*100:.1f}%")
            report_lines.append(f"{'Avg Latency (ms)':<30} {mistral.get('avg_latency_ms', 0):.1f}{'':<14} {ministral.get('avg_latency_ms', 0):.1f}")
            report_lines.append(f"{'Median Latency (ms)':<30} {mistral.get('median_latency_ms', 0):.1f}{'':<14} {ministral.get('median_latency_ms', 0):.1f}")
            report_lines.append(f"{'Total Cost (USD)':<30} ${mistral.get('total_cost_usd', 0):.6f}{'':<12} ${ministral.get('total_cost_usd', 0):.6f}")
        
        # Validation accuracy breakdown
        report_lines.append("")
        report_lines.append("=" * 80)
        report_lines.append("VALIDATION ACCURACY BY TEST CASE")
        report_lines.append("=" * 80)
        
        # Group results by test_id
        for category, comparison in results.items():
            report_lines.append(f"\n--- {category.upper()} ---\n")
            
            mistral_by_test = {}
            for r in comparison.mistral_results:
                if r.test_id not in mistral_by_test:
                    mistral_by_test[r.test_id] = []
                mistral_by_test[r.test_id].append(r)
            
            ministral_by_test = {}
            for r in comparison.ministral_results:
                if r.test_id not in ministral_by_test:
                    ministral_by_test[r.test_id] = []
                ministral_by_test[r.test_id].append(r)
            
            for test_id in mistral_by_test:
                report_lines.append(f"\nTest: {test_id}")
                
                # Calculate pass rate for each validation
                mistral_validations = {}
                for r in mistral_by_test.get(test_id, []):
                    for key, val in r.validation_results.items():
                        if key not in mistral_validations:
                            mistral_validations[key] = {"passed": 0, "total": 0}
                        mistral_validations[key]["total"] += 1
                        if val.get("passed"):
                            mistral_validations[key]["passed"] += 1
                
                ministral_validations = {}
                for r in ministral_by_test.get(test_id, []):
                    for key, val in r.validation_results.items():
                        if key not in ministral_validations:
                            ministral_validations[key] = {"passed": 0, "total": 0}
                        ministral_validations[key]["total"] += 1
                        if val.get("passed"):
                            ministral_validations[key]["passed"] += 1
                
                all_keys = set(mistral_validations.keys()) | set(ministral_validations.keys())
                for key in sorted(all_keys):
                    m_data = mistral_validations.get(key, {"passed": 0, "total": 0})
                    n_data = ministral_validations.get(key, {"passed": 0, "total": 0})
                    m_rate = m_data["passed"] / m_data["total"] * 100 if m_data["total"] > 0 else 0
                    n_rate = n_data["passed"] / n_data["total"] * 100 if n_data["total"] > 0 else 0
                    
                    m_icon = "✓" if m_rate == 100 else ("~" if m_rate > 0 else "✗")
                    n_icon = "✓" if n_rate == 100 else ("~" if n_rate > 0 else "✗")
                    
                    report_lines.append(f"  {key:<25} Mistral: {m_icon} {m_rate:.0f}%  |  Ministral: {n_icon} {n_rate:.0f}%")
        
        # Recommendations
        report_lines.append("")
        report_lines.append("=" * 80)
        report_lines.append("RECOMMENDATIONS")
        report_lines.append("=" * 80)
        
        # Calculate overall scores
        mistral_score = 0
        ministral_score = 0
        
        # Success rate comparison
        if mistral_stats.get("success_rate", 0) > ministral_stats.get("success_rate", 0):
            mistral_score += 2
        elif ministral_stats.get("success_rate", 0) > mistral_stats.get("success_rate", 0):
            ministral_score += 2
        
        # Latency comparison (lower is better)
        if mistral_stats.get("avg_latency_ms", float('inf')) < ministral_stats.get("avg_latency_ms", float('inf')):
            mistral_score += 1
        else:
            ministral_score += 1
        
        # Cost comparison (lower is better)
        if mistral_stats.get("avg_cost_per_request_usd", float('inf')) < ministral_stats.get("avg_cost_per_request_usd", float('inf')):
            mistral_score += 1
        else:
            ministral_score += 1
        
        report_lines.append(f"\nOverall Score: Mistral Small = {mistral_score}, Ministral 3B = {ministral_score}")
        report_lines.append("")
        
        if mistral_score > ministral_score:
            report_lines.append("RECOMMENDATION: Keep using Mistral Small 3.2")
            report_lines.append("Reasoning: Higher overall score based on success rate, latency, and cost metrics.")
        elif ministral_score > mistral_score:
            report_lines.append("RECOMMENDATION: Consider switching to Ministral 3 8B")
            report_lines.append("Reasoning: Higher overall score based on success rate, latency, and cost metrics.")
        else:
            report_lines.append("RECOMMENDATION: Both models perform similarly")
            report_lines.append("Reasoning: Scores are tied. Consider other factors like:")
            report_lines.append("  - Specific use case requirements")
            report_lines.append("  - Model availability and reliability")
            report_lines.append("  - Future roadmap and updates")
        
        # Cost projection
        report_lines.append("")
        report_lines.append("-" * 50)
        report_lines.append("COST PROJECTION (per 1 million requests)")
        report_lines.append("-" * 50)
        
        mistral_proj = mistral_stats.get("avg_cost_per_request_usd", 0) * 1_000_000
        ministral_proj = ministral_stats.get("avg_cost_per_request_usd", 0) * 1_000_000
        savings = abs(mistral_proj - ministral_proj)
        
        report_lines.append(f"Mistral Small 3.2:  ${mistral_proj:,.2f}")
        report_lines.append(f"Ministral 3 8B:     ${ministral_proj:,.2f}")
        report_lines.append(f"Potential Savings:  ${savings:,.2f} per million requests")
        report_lines.append(f"Better Value:       {'Ministral 3B' if ministral_proj < mistral_proj else 'Mistral Small'}")
        
        report_lines.append("")
        report_lines.append("=" * 100)
        report_lines.append("END OF REPORT")
        report_lines.append("=" * 100)
        
        return "\n".join(report_lines)
    
    def save_results(self, results: Dict[str, ComparisonResult], output_dir: Path):
        """Save detailed results to JSON files."""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save raw results
        raw_results = {
            "timestamp": timestamp,
            "iterations": self.iterations,
            "models": MODELS,
            "results": {}
        }
        
        for category, comparison in results.items():
            raw_results["results"][category] = {
                "mistral": [
                    {
                        "test_id": r.test_id,
                        "success": r.success,
                        "latency_ms": r.latency_ms,
                        "tokens": r.total_tokens,
                        "cost_usd": r.cost_usd,
                        "validation": r.validation_results,
                        "raw_response": r.raw_response,
                        "error": r.error_message,
                    }
                    for r in comparison.mistral_results
                ],
                "ministral": [
                    {
                        "test_id": r.test_id,
                        "success": r.success,
                        "latency_ms": r.latency_ms,
                        "tokens": r.total_tokens,
                        "cost_usd": r.cost_usd,
                        "validation": r.validation_results,
                        "raw_response": r.raw_response,
                        "error": r.error_message,
                    }
                    for r in comparison.ministral_results
                ],
            }
        
        results_file = output_dir / f"model_comparison_results_{timestamp}.json"
        with open(results_file, "w") as f:
            json.dump(raw_results, f, indent=2, default=str)
        
        logger.info(f"Results saved to {results_file}")
        
        # Save report
        report = self.generate_report(results)
        report_file = output_dir / f"model_comparison_report_{timestamp}.txt"
        with open(report_file, "w") as f:
            f.write(report)
        
        logger.info(f"Report saved to {report_file}")
        
        return results_file, report_file


# =============================================================================
# PYTEST TEST FUNCTIONS
# =============================================================================

@pytest.fixture
async def test_runner():
    """Create a test runner instance with initialized SecretsManager."""
    runner = ModelComparisonTest(iterations=1)
    await runner._ensure_secrets_initialized()
    return runner


@pytest.mark.asyncio
async def test_preprocessing_simple_factual(test_runner):
    """Test preprocessing with simple factual queries."""
    test_cases = [tc for tc in PREPROCESSING_TEST_CASES if tc["id"].startswith("simple_factual")]
    
    for test_case in test_cases:
        mistral_result = await test_runner._run_preprocessing_test(test_case, "mistral_small")
        ministral_result = await test_runner._run_preprocessing_test(test_case, "ministral_3b")
        
        # Both models should succeed
        assert mistral_result.success, f"Mistral failed: {mistral_result.error_message}"
        assert ministral_result.success, f"Ministral failed: {ministral_result.error_message}"
        
        # Log results for comparison
        logger.info(f"Test {test_case['id']}:")
        logger.info(f"  Mistral: {mistral_result.latency_ms:.1f}ms, ${mistral_result.cost_usd:.6f}")
        logger.info(f"  Ministral: {ministral_result.latency_ms:.1f}ms, ${ministral_result.cost_usd:.6f}")


@pytest.mark.asyncio
async def test_preprocessing_complex_reasoning(test_runner):
    """Test preprocessing with complex reasoning queries."""
    test_cases = [tc for tc in PREPROCESSING_TEST_CASES if tc["id"].startswith("complex_reasoning")]
    
    for test_case in test_cases:
        mistral_result = await test_runner._run_preprocessing_test(test_case, "mistral_small")
        ministral_result = await test_runner._run_preprocessing_test(test_case, "ministral_3b")
        
        assert mistral_result.success, f"Mistral failed: {mistral_result.error_message}"
        assert ministral_result.success, f"Ministral failed: {ministral_result.error_message}"
        
        # Check complexity is correctly identified
        if mistral_result.raw_response:
            assert mistral_result.raw_response.get("complexity") == "complex", \
                f"Mistral should identify as complex, got: {mistral_result.raw_response.get('complexity')}"
        
        if ministral_result.raw_response:
            assert ministral_result.raw_response.get("complexity") == "complex", \
                f"Ministral should identify as complex, got: {ministral_result.raw_response.get('complexity')}"


@pytest.mark.asyncio
async def test_preprocessing_code_queries(test_runner):
    """Test preprocessing with code-related queries."""
    test_cases = [tc for tc in PREPROCESSING_TEST_CASES if tc["id"].startswith("code_")]
    
    for test_case in test_cases:
        mistral_result = await test_runner._run_preprocessing_test(test_case, "mistral_small")
        ministral_result = await test_runner._run_preprocessing_test(test_case, "ministral_3b")
        
        assert mistral_result.success, f"Mistral failed: {mistral_result.error_message}"
        assert ministral_result.success, f"Ministral failed: {ministral_result.error_message}"
        
        # Check task_area is code
        for result, name in [(mistral_result, "Mistral"), (ministral_result, "Ministral")]:
            if result.raw_response:
                assert result.raw_response.get("task_area") == "code", \
                    f"{name} should identify task_area as 'code', got: {result.raw_response.get('task_area')}"


@pytest.mark.asyncio
async def test_preprocessing_safety_checks(test_runner):
    """Test preprocessing safety/moderation checks."""
    test_cases = [tc for tc in PREPROCESSING_TEST_CASES if tc["id"].startswith("safety_")]
    
    for test_case in test_cases:
        mistral_result = await test_runner._run_preprocessing_test(test_case, "mistral_small")
        ministral_result = await test_runner._run_preprocessing_test(test_case, "ministral_3b")
        
        assert mistral_result.success, f"Mistral failed: {mistral_result.error_message}"
        assert ministral_result.success, f"Ministral failed: {ministral_result.error_message}"
        
        # Check validation results
        for result, name in [(mistral_result, "Mistral"), (ministral_result, "Ministral")]:
            for key, val in result.validation_results.items():
                if not val.get("passed"):
                    logger.warning(f"{name} failed validation '{key}' for test '{test_case['id']}': {val}")


@pytest.mark.asyncio
async def test_preprocessing_skill_selection(test_runner):
    """Test preprocessing skill selection."""
    test_cases = [tc for tc in PREPROCESSING_TEST_CASES if tc["id"].startswith("skill_")]
    
    for test_case in test_cases:
        mistral_result = await test_runner._run_preprocessing_test(test_case, "mistral_small")
        ministral_result = await test_runner._run_preprocessing_test(test_case, "ministral_3b")
        
        assert mistral_result.success, f"Mistral failed: {mistral_result.error_message}"
        assert ministral_result.success, f"Ministral failed: {ministral_result.error_message}"
        
        # Check skill selection validation
        expected_skills = test_case.get("expected", {}).get("relevant_app_skills_contains", [])
        
        for result, name in [(mistral_result, "Mistral"), (ministral_result, "Ministral")]:
            if result.raw_response:
                actual_skills = result.raw_response.get("relevant_app_skills", []) or []
                for skill in expected_skills:
                    if skill not in actual_skills:
                        logger.warning(f"{name} missed skill '{skill}' for test '{test_case['id']}'. Actual: {actual_skills}")


@pytest.mark.asyncio
async def test_postprocessing_suggestions(test_runner):
    """Test postprocessing suggestion generation."""
    for test_case in POSTPROCESSING_TEST_CASES:
        mistral_result = await test_runner._run_postprocessing_test(test_case, "mistral_small")
        ministral_result = await test_runner._run_postprocessing_test(test_case, "ministral_3b")
        
        assert mistral_result.success, f"Mistral failed: {mistral_result.error_message}"
        assert ministral_result.success, f"Ministral failed: {ministral_result.error_message}"
        
        # Check suggestion counts
        for result, name in [(mistral_result, "Mistral"), (ministral_result, "Ministral")]:
            if result.raw_response:
                follow_ups = result.raw_response.get("follow_up_request_suggestions", []) or []
                new_chats = result.raw_response.get("new_chat_request_suggestions", []) or []
                
                logger.info(f"{name} - Test '{test_case['id']}':")
                logger.info(f"  Follow-ups ({len(follow_ups)}): {follow_ups[:2]}...")
                logger.info(f"  New chats ({len(new_chats)}): {new_chats[:2]}...")


@pytest.mark.asyncio
async def test_full_comparison():
    """Run the full comparison test suite."""
    runner = ModelComparisonTest(iterations=1)
    await runner._ensure_secrets_initialized()
    results = await runner.run_all_tests()
    
    # Generate and print report
    report = runner.generate_report(results)
    print("\n" + report)
    
    # Save results
    output_dir = project_root / "backend" / "tests" / "output"
    runner.save_results(results, output_dir)
    
    # Basic assertions
    for category, comparison in results.items():
        assert len(comparison.mistral_results) > 0, f"No Mistral results for {category}"
        assert len(comparison.ministral_results) > 0, f"No Ministral results for {category}"


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

async def main():
    """Main entry point for running the comparison."""
    parser = argparse.ArgumentParser(description="Compare Mistral Small vs Ministral 3B for preprocessing/postprocessing")
    parser.add_argument("--iterations", type=int, default=1, help="Number of iterations per test")
    parser.add_argument("--report", action="store_true", help="Only generate report from existing results")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory for results")
    
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir) if args.output_dir else project_root / "backend" / "tests" / "output"
    
    if args.report:
        # Load existing results and generate report
        logger.error("Report-only mode not implemented yet. Run full tests first.")
        return
    
    # Run full comparison
    runner = ModelComparisonTest(iterations=args.iterations)
    
    # Initialize SecretsManager before running tests
    await runner._ensure_secrets_initialized()
    
    logger.info("Starting model comparison tests...")
    logger.info(f"Iterations per test: {args.iterations}")
    logger.info(f"Total preprocessing tests: {len(PREPROCESSING_TEST_CASES)}")
    logger.info(f"Total postprocessing tests: {len(POSTPROCESSING_TEST_CASES)}")
    
    results = await runner.run_all_tests()
    
    # Generate and display report
    report = runner.generate_report(results)
    print("\n" + report)
    
    # Save results
    results_file, report_file = runner.save_results(results, output_dir)
    
    print(f"\nResults saved to: {results_file}")
    print(f"Report saved to: {report_file}")


if __name__ == "__main__":
    asyncio.run(main())
