# backend/tests/test_model_comparison_small32_vs_small4.py
"""
Model Comparison Test: Mistral Small 3.2 (mistral-small-2506) vs Mistral Small 4 (mistral-small-latest)

Context: As of June 2025, mistral-small-latest now resolves to Mistral Small 4 instead of Small 3.2.
Small 4 is reportedly better on most benchmarks but costs 2x more ($0.20/$0.60 vs $0.10/$0.30 per M tokens).
We currently pin mistral-small-2506 for all preprocessing/postprocessing. This test evaluates whether
Small 4's quality improvement justifies the price increase for our specific use cases.

Models compared:
- Current:   mistral/mistral-small-2506   (Mistral Small 3.2, pinned June 2025, $0.10/$0.30 per M)
- Candidate: mistral/mistral-small-latest (Mistral Small 4,   $0.20/$0.60 per M — 2x cost)

Test categories:
1. Preprocessing  — Request routing, complexity, skill selection, safety scoring
2. Postprocessing — Follow-up + new chat suggestion generation

Usage:
    # Full comparison with report (recommended):
    python backend/tests/test_model_comparison_small32_vs_small4.py --iterations 2

    # Quick single run:
    python backend/tests/test_model_comparison_small32_vs_small4.py

    # Via pytest (individual categories):
    python -m pytest backend/tests/test_model_comparison_small32_vs_small4.py -v -s -k "preprocessing"
    python -m pytest backend/tests/test_model_comparison_small32_vs_small4.py -v -s -k "postprocessing"
    python -m pytest backend/tests/test_model_comparison_small32_vs_small4.py -v -s -k "full_comparison"

Architecture refs: docs/architecture/ai-preprocessing.md
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

# Add project root to sys.path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from backend.apps.ai.utils.llm_utils import (  # noqa: E402
    call_preprocessing_llm,
    LLMPreprocessingCallResult,
)
from backend.core.api.app.utils.secrets_manager import SecretsManager  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# =============================================================================
# MODEL CONFIGURATION
# =============================================================================

MODELS = {
    "small_32": {
        "id": "mistral/mistral-small-2506",   # Pinned Small 3.2 — current production model
        "name": "Mistral Small 3.2 (2506)",
        "cost_input_per_million": 0.10,
        "cost_output_per_million": 0.30,
    },
    "small_4": {
        "id": "mistral/mistral-small-latest",  # Small 4 — candidate
        "name": "Mistral Small 4 (latest)",
        "cost_input_per_million": 0.20,
        "cost_output_per_million": 0.60,
    },
}

# =============================================================================
# TEST DATA — Preprocessing Scenarios
# Reuses the same test cases as test_model_comparison_mistral_vs_ministral.py
# to keep results comparable across evaluations.
# =============================================================================

PREPROCESSING_TEST_CASES = [
    # -------------------------------------------------------------------------
    # Category 1: Simple factual queries
    # -------------------------------------------------------------------------
    {
        "id": "simple_factual_1",
        "name": "Simple factual question",
        "description": "Basic knowledge query — should be marked as simple",
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
        },
    },
    {
        "id": "simple_factual_2",
        "name": "Simple math question",
        "description": "Basic arithmetic — should be marked as simple",
        "messages": [
            {"role": "user", "content": "What is 15 times 23?"}
        ],
        "expected": {
            "complexity": "simple",
            "task_area": "math",
            "harmful_or_illegal_max": 1.0,
            "misuse_risk_max": 1,
        },
    },
    # -------------------------------------------------------------------------
    # Category 2: Complex reasoning
    # -------------------------------------------------------------------------
    {
        "id": "complex_reasoning_1",
        "name": "Complex analysis request",
        "description": "Multi-faceted analysis — should be marked as complex",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Analyze the pros and cons of microservices architecture vs monolithic "
                    "architecture for a startup with 5 developers building a SaaS product. "
                    "Consider scalability, development speed, operational complexity, and team expertise."
                ),
            }
        ],
        "expected": {
            "complexity": "complex",
            "task_area": "code",
            "harmful_or_illegal_max": 1.0,
        },
    },
    {
        "id": "complex_reasoning_2",
        "name": "Complex creative writing",
        "description": "Creative task requiring nuance",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Write a philosophical dialogue between Socrates and a modern AI researcher "
                    "about the nature of consciousness and whether machines can truly think."
                ),
            }
        ],
        "expected": {
            "complexity": "complex",
            "task_area": "creative",
            "harmful_or_illegal_max": 1.0,
        },
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
        },
    },
    {
        "id": "code_complex_1",
        "name": "Complex code architecture",
        "description": "Complex coding task requiring deep knowledge",
        "messages": [
            {
                "role": "user",
                "content": (
                    "I need to implement a real-time collaborative text editor like Google Docs. "
                    "What's the best approach for handling concurrent edits? Should I use OT "
                    "(Operational Transformation) or CRDTs? Can you explain the tradeoffs and "
                    "show me a basic implementation in TypeScript?"
                ),
            }
        ],
        "expected": {
            "complexity": "complex",
            "task_area": "code",
            "harmful_or_illegal_max": 1.0,
        },
    },
    {
        "id": "code_api_docs",
        "name": "API documentation request",
        "description": "Should trigger code-get_docs skill",
        "messages": [
            {
                "role": "user",
                "content": "How does the Stripe API handle webhooks? I need to verify webhook signatures in my Node.js app.",
            }
        ],
        "expected": {
            "complexity": "complex",
            "task_area": "code",
            "relevant_app_skills_contains": ["code-get_docs"],
        },
    },
    # -------------------------------------------------------------------------
    # Category 4: Safety / moderation
    # -------------------------------------------------------------------------
    {
        "id": "safety_benign_1",
        "name": "Benign question about sensitive topic",
        "description": "Educational nuclear energy question — should NOT be flagged",
        "messages": [
            {
                "role": "user",
                "content": "Can you explain the history of nuclear energy and how nuclear reactors work?",
            }
        ],
        "expected": {
            "harmful_or_illegal_max": 3.0,
            "misuse_risk_max": 3,
        },
    },
    {
        "id": "safety_harm_reduction",
        "name": "Harm reduction query",
        "description": "Should have low harmful score",
        "messages": [
            {
                "role": "user",
                "content": (
                    "What are the signs of alcohol poisoning and what should I do "
                    "if I see someone who might have it?"
                ),
            }
        ],
        "expected": {
            "harmful_or_illegal_max": 2.0,
            "category": "medical_health",
        },
    },
    {
        "id": "safety_mental_health",
        "name": "Mental health support query",
        "description": "Should route to life_coach_psychology",
        "messages": [
            {
                "role": "user",
                "content": (
                    "I've been feeling really overwhelmed and anxious lately. "
                    "I can't sleep and I keep worrying about everything. What can I do?"
                ),
            }
        ],
        "expected": {
            "category": "life_coach_psychology",
            "harmful_or_illegal_max": 1.0,
        },
    },
    # -------------------------------------------------------------------------
    # Category 5: Skill selection
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
        },
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
        },
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
        },
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
        },
    },
    # -------------------------------------------------------------------------
    # Category 6: Follow-up detection
    # -------------------------------------------------------------------------
    {
        "id": "followup_weather",
        "name": "Follow-up query detection",
        "description": "Should detect follow-up and carry over web-search skill",
        "messages": [
            {"role": "user", "content": "What's the weather in New York?"},
            {
                "role": "assistant",
                "content": "The weather in New York today is partly cloudy with a high of 72°F (22°C).",
            },
            {"role": "user", "content": "And Paris?"},
        ],
        "expected": {
            "relevant_app_skills_contains": ["web-search"],
        },
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
            {
                "role": "assistant",
                "content": "You can use the sort() method or sorted() function.",
            },
            {
                "role": "user",
                "content": "That's not helpful at all. I need a detailed explanation with examples.",
            },
        ],
        "expected": {
            "user_unhappy": True,
        },
    },
    {
        "id": "user_unhappy_2",
        "name": "User satisfied follow-up",
        "description": "Should NOT detect user as unhappy",
        "messages": [
            {"role": "user", "content": "How do I sort a list in Python?"},
            {
                "role": "assistant",
                "content": "You can use the sort() method or sorted() function with detailed examples...",
            },
            {"role": "user", "content": "Great, thanks! Now how do I reverse sort?"},
        ],
        "expected": {
            "user_unhappy": False,
        },
    },
    # -------------------------------------------------------------------------
    # Category 8: Edge cases
    # -------------------------------------------------------------------------
    {
        "id": "edge_empty_like",
        "name": "Very short query",
        "description": "Handle minimal input gracefully",
        "messages": [{"role": "user", "content": "Hi"}],
        "expected": {
            "complexity": "simple",
            "harmful_or_illegal_max": 1.0,
        },
    },
    {
        "id": "edge_multilingual",
        "name": "Non-English query",
        "description": "Handle non-English input",
        "messages": [
            {
                "role": "user",
                "content": "Quel est le meilleur framework JavaScript pour créer une application web moderne?",
            }
        ],
        "expected": {
            "task_area": "code",
            "has_title": True,
        },
    },
    {
        "id": "edge_long_context",
        "name": "Long conversation context",
        "description": "Handle long conversation history",
        "messages": [
            {"role": "user", "content": "I'm building a web application."},
            {
                "role": "assistant",
                "content": "That sounds interesting! What kind of web application are you building?",
            },
            {"role": "user", "content": "It's an e-commerce platform for selling handmade crafts."},
            {
                "role": "assistant",
                "content": "Great choice! E-commerce platforms have many components. What aspects are you working on?",
            },
            {"role": "user", "content": "I'm stuck on the payment integration. I want to use Stripe."},
            {
                "role": "assistant",
                "content": "Stripe is excellent for payments. What specific part of the integration are you struggling with?",
            },
            {"role": "user", "content": "How do I implement subscriptions with Stripe in a Next.js app?"},
        ],
        "expected": {
            "complexity": "complex",
            "task_area": "code",
            "relevant_app_skills_contains": ["code-get_docs"],
        },
    },
]

# =============================================================================
# TEST DATA — Postprocessing Scenarios
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
        },
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
        },
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
        },
    },
    {
        "id": "post_business_response",
        "name": "Business strategy response",
        "description": "Generate follow-ups for business advice",
        "user_message": "How should I price my SaaS product?",
        "assistant_response": """
Pricing a SaaS product requires balancing customer value perception with your business economics.

**Key Pricing Strategies:**

1. **Value-based pricing** — Charge based on the value you deliver, not your costs.
   Best for B2B tools with measurable ROI.

2. **Freemium** — Free tier to drive adoption, paid tiers for power users.
   Works well when viral growth is important.

3. **Usage-based pricing** — Charge per API call, user, or action.
   Reduces barrier to entry; revenue scales with usage.

4. **Seat-based (per user)** — Common for team tools.
   Predictable revenue; can limit adoption within orgs.

**Practical advice:**
- Start with 3 tiers: Free/Starter, Growth, Enterprise
- Anchor the middle tier — most users pick it
- Research what competitors charge and position accordingly
- Don't undercharge; it signals low quality and makes pivoting harder later
        """,
        "chat_summary": "User asking about SaaS pricing strategy",
        "chat_tags": ["saas", "pricing", "business", "startup", "monetization"],
        "expected": {
            "has_follow_up_suggestions": True,
            "has_new_chat_suggestions": True,
        },
    },
]

# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class TestResult:
    """Result of a single model test run."""
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
    """Aggregated comparison between Small 3.2 and Small 4."""
    test_category: str
    small_32_results: List[TestResult]
    small_4_results: List[TestResult]

    def get_summary(self) -> Dict[str, Any]:
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
                "p95_latency_ms": (
                    sorted(latencies)[int(len(latencies) * 0.95)]
                    if len(latencies) > 1
                    else (latencies[0] if latencies else 0)
                ),
                "total_cost_usd": sum(costs),
                "avg_cost_usd": statistics.mean(costs) if costs else 0,
            }

        return {
            "category": self.test_category,
            "small_32": calc_stats(self.small_32_results),
            "small_4": calc_stats(self.small_4_results),
        }


# =============================================================================
# TEST RUNNER
# =============================================================================


class ModelComparisonTest:
    """Runs comparison tests between Mistral Small 3.2 (pinned) and Small 4 (latest)."""

    def __init__(self, iterations: int = 1):
        self.iterations = iterations
        self.secrets_manager = SecretsManager()
        self._secrets_initialized = False
        self.results: List[TestResult] = []
        self._load_base_instructions()

    async def _ensure_secrets_initialized(self):
        if not self._secrets_initialized:
            logger.info("Initializing SecretsManager...")
            await self.secrets_manager.initialize()
            self._secrets_initialized = True
            logger.info("SecretsManager initialized")

    def _load_base_instructions(self):
        import yaml
        path = project_root / "backend" / "apps" / "ai" / "base_instructions.yml"
        with open(path, "r") as f:
            self.base_instructions = yaml.safe_load(f)
        logger.info("Loaded base instructions from YAML")

    def _calculate_cost(self, model_key: str, input_tokens: int, output_tokens: int) -> float:
        model = MODELS[model_key]
        return (
            (input_tokens / 1_000_000) * model["cost_input_per_million"]
            + (output_tokens / 1_000_000) * model["cost_output_per_million"]
        )

    # -------------------------------------------------------------------------
    # Preprocessing
    # -------------------------------------------------------------------------

    async def _run_preprocessing_test(
        self, test_case: Dict[str, Any], model_key: str
    ) -> TestResult:
        model = MODELS[model_key]
        model_id = model["id"]
        test_id = test_case["id"]
        logger.info(f"[preprocessing] test='{test_id}' model='{model['name']}'")

        tool_definition = copy.deepcopy(self.base_instructions["preprocess_request_tool"])

        available_categories = [
            "general_knowledge", "coding_technology", "finance", "medical_health",
            "legal_law", "life_coach_psychology", "education", "creative_arts",
            "science", "business", "travel", "food_cooking",
        ]
        available_skills = [
            "web-search", "web-read", "news-search", "videos-search",
            "videos-get_transcript", "maps-search", "code-get_docs", "images-generate",
        ]
        available_focus_modes = ["ai-research", "ai-code_writer", "ai-fact_checker"]

        dynamic_context = {
            "CATEGORIES_LIST": available_categories,
            "AVAILABLE_APP_SKILLS": available_skills,
            "AVAILABLE_FOCUS_MODES": available_focus_modes,
            "CURRENT_DATE_TIME": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

        await self._ensure_secrets_initialized()
        start_time = time.perf_counter()

        try:
            result: LLMPreprocessingCallResult = await call_preprocessing_llm(
                task_id=f"cmp_{test_id}_{model_key}",
                model_id=model_id,
                message_history=test_case["messages"],
                tool_definition=tool_definition,
                secrets_manager=self.secrets_manager,
                user_app_settings_and_memories_metadata=None,
                dynamic_context=dynamic_context,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000

            input_tokens = output_tokens = 0
            if result.raw_provider_response_summary:
                usage = result.raw_provider_response_summary.get("usage", {})
                if isinstance(usage, dict):
                    input_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
                    output_tokens = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)

            total_tokens = input_tokens + output_tokens
            cost = self._calculate_cost(model_key, input_tokens, output_tokens)
            validation = self._validate_preprocessing(result.arguments or {}, test_case.get("expected", {}))

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
                validation_results=validation,
            )

        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"[preprocessing] test='{test_id}' model='{model_key}' error: {exc}", exc_info=True)
            return TestResult(
                test_id=test_id, model_id=model_id, model_name=model["name"],
                success=False, latency_ms=latency_ms,
                input_tokens=0, output_tokens=0, total_tokens=0, cost_usd=0,
                error_message=str(exc),
            )

    def _validate_preprocessing(
        self, actual: Dict[str, Any], expected: Dict[str, Any]
    ) -> Dict[str, Any]:
        v = {}

        if "complexity" in expected:
            v["complexity"] = {
                "expected": expected["complexity"],
                "actual": actual.get("complexity"),
                "passed": actual.get("complexity") == expected["complexity"],
            }

        if "task_area" in expected:
            v["task_area"] = {
                "expected": expected["task_area"],
                "actual": actual.get("task_area"),
                "passed": actual.get("task_area") == expected["task_area"],
            }

        if "harmful_or_illegal_max" in expected:
            score = actual.get("harmful_or_illegal", 0)
            v["harmful_or_illegal"] = {
                "expected_max": expected["harmful_or_illegal_max"],
                "actual": score,
                "passed": score <= expected["harmful_or_illegal_max"],
            }

        if "misuse_risk_max" in expected:
            score = actual.get("misuse_risk", 0)
            v["misuse_risk"] = {
                "expected_max": expected["misuse_risk_max"],
                "actual": score,
                "passed": score <= expected["misuse_risk_max"],
            }

        if "category" in expected:
            v["category"] = {
                "expected": expected["category"],
                "actual": actual.get("category"),
                "passed": actual.get("category") == expected["category"],
            }

        if "user_unhappy" in expected:
            v["user_unhappy"] = {
                "expected": expected["user_unhappy"],
                "actual": actual.get("user_unhappy"),
                "passed": actual.get("user_unhappy") == expected["user_unhappy"],
            }

        if "relevant_app_skills_contains" in expected:
            actual_skills = actual.get("relevant_app_skills", []) or []
            expected_skills = expected["relevant_app_skills_contains"]
            missing = [s for s in expected_skills if s not in actual_skills]
            v["relevant_app_skills"] = {
                "expected_contains": expected_skills,
                "actual": actual_skills,
                "passed": len(missing) == 0,
                "missing": missing,
            }

        if expected.get("has_title"):
            title = actual.get("title", "")
            v["has_title"] = {
                "expected": True,
                "actual": bool(title),
                "passed": bool(title and len(title) > 0),
                "value": title,
            }

        if expected.get("has_icon_names"):
            icons = actual.get("icon_names", [])
            v["has_icon_names"] = {
                "expected": True,
                "actual": bool(icons),
                "passed": bool(icons and len(icons) > 0),
                "value": icons,
            }

        return v

    # -------------------------------------------------------------------------
    # Postprocessing
    # -------------------------------------------------------------------------

    async def _run_postprocessing_test(
        self, test_case: Dict[str, Any], model_key: str
    ) -> TestResult:
        model = MODELS[model_key]
        model_id = model["id"]
        test_id = test_case["id"]
        logger.info(f"[postprocessing] test='{test_id}' model='{model['name']}'")

        tool_definition = copy.deepcopy(self.base_instructions["postprocess_response_tool"])
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        available_apps_list = "web, code, images, videos, news, maps, travel, health"

        messages = [
            {
                "role": "system",
                "content": (
                    f"Current date and time: {now}\n\n"
                    "You are analyzing a conversation to generate helpful suggestions. "
                    "Generate contextual follow-up suggestions that encourage deeper engagement. "
                    "Generate new chat suggestions that explore related but new angles."
                ),
            },
            {
                "role": "system",
                "content": (
                    f"Full conversation summary: {test_case['chat_summary']}\n"
                    f"Conversation tags: {', '.join(test_case['chat_tags'])}\n\n"
                    f"Available app IDs in the system: {available_apps_list}\n"
                    "IMPORTANT: Only use app IDs from this list."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Last user message: {test_case['user_message']}\n\n"
                    f"Assistant's response: {test_case['assistant_response']}\n\n"
                    "Based on this exchange and the conversation context, "
                    "generate follow-up and new chat suggestions."
                ),
            },
        ]

        await self._ensure_secrets_initialized()
        start_time = time.perf_counter()

        try:
            result: LLMPreprocessingCallResult = await call_preprocessing_llm(
                task_id=f"cmp_{test_id}_{model_key}",
                model_id=model_id,
                message_history=messages,
                tool_definition=tool_definition,
                secrets_manager=self.secrets_manager,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000

            input_tokens = output_tokens = 0
            if result.raw_provider_response_summary:
                usage = result.raw_provider_response_summary.get("usage", {})
                if isinstance(usage, dict):
                    input_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
                    output_tokens = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)

            total_tokens = input_tokens + output_tokens
            cost = self._calculate_cost(model_key, input_tokens, output_tokens)
            validation = self._validate_postprocessing(result.arguments or {}, test_case.get("expected", {}))

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
                validation_results=validation,
            )

        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"[postprocessing] test='{test_id}' model='{model_key}' error: {exc}", exc_info=True)
            return TestResult(
                test_id=test_id, model_id=model_id, model_name=model["name"],
                success=False, latency_ms=latency_ms,
                input_tokens=0, output_tokens=0, total_tokens=0, cost_usd=0,
                error_message=str(exc),
            )

    def _validate_postprocessing(
        self, actual: Dict[str, Any], expected: Dict[str, Any]
    ) -> Dict[str, Any]:
        v = {}

        if "has_follow_up_suggestions" in expected:
            suggestions = actual.get("follow_up_request_suggestions", []) or []
            v["follow_up_suggestions"] = {
                "expected": expected["has_follow_up_suggestions"],
                "actual_count": len(suggestions),
                "passed": len(suggestions) > 0 if expected["has_follow_up_suggestions"] else True,
                "samples": suggestions[:3] if suggestions else [],
            }

        if "min_follow_up_count" in expected:
            suggestions = actual.get("follow_up_request_suggestions", []) or []
            v["follow_up_count"] = {
                "expected_min": expected["min_follow_up_count"],
                "actual": len(suggestions),
                "passed": len(suggestions) >= expected["min_follow_up_count"],
            }

        if "has_new_chat_suggestions" in expected:
            suggestions = actual.get("new_chat_request_suggestions", []) or []
            v["new_chat_suggestions"] = {
                "expected": expected["has_new_chat_suggestions"],
                "actual_count": len(suggestions),
                "passed": len(suggestions) > 0 if expected["has_new_chat_suggestions"] else True,
                "samples": suggestions[:3] if suggestions else [],
            }

        if "min_new_chat_count" in expected:
            suggestions = actual.get("new_chat_request_suggestions", []) or []
            v["new_chat_count"] = {
                "expected_min": expected["min_new_chat_count"],
                "actual": len(suggestions),
                "passed": len(suggestions) >= expected["min_new_chat_count"],
            }

        if "harmful_response_max" in expected:
            score = actual.get("harmful_response", 0)
            v["harmful_response"] = {
                "expected_max": expected["harmful_response_max"],
                "actual": score,
                "passed": score <= expected["harmful_response_max"],
            }

        return v

    # -------------------------------------------------------------------------
    # Run all tests
    # -------------------------------------------------------------------------

    async def run_all_tests(self) -> Dict[str, ComparisonResult]:
        results = {
            "preprocessing": ComparisonResult(
                test_category="preprocessing",
                small_32_results=[],
                small_4_results=[],
            ),
            "postprocessing": ComparisonResult(
                test_category="postprocessing",
                small_32_results=[],
                small_4_results=[],
            ),
        }

        logger.info("=" * 80)
        logger.info("STARTING PREPROCESSING TESTS")
        logger.info("=" * 80)

        for test_case in PREPROCESSING_TEST_CASES:
            for iteration in range(self.iterations):
                logger.info(f"\nIteration {iteration + 1}/{self.iterations} — test '{test_case['id']}'")

                r32 = await self._run_preprocessing_test(test_case, "small_32")
                results["preprocessing"].small_32_results.append(r32)
                self.results.append(r32)

                r4 = await self._run_preprocessing_test(test_case, "small_4")
                results["preprocessing"].small_4_results.append(r4)
                self.results.append(r4)

                await asyncio.sleep(0.5)

        logger.info("=" * 80)
        logger.info("STARTING POSTPROCESSING TESTS")
        logger.info("=" * 80)

        for test_case in POSTPROCESSING_TEST_CASES:
            for iteration in range(self.iterations):
                logger.info(f"\nIteration {iteration + 1}/{self.iterations} — test '{test_case['id']}'")

                r32 = await self._run_postprocessing_test(test_case, "small_32")
                results["postprocessing"].small_32_results.append(r32)
                self.results.append(r32)

                r4 = await self._run_postprocessing_test(test_case, "small_4")
                results["postprocessing"].small_4_results.append(r4)
                self.results.append(r4)

                await asyncio.sleep(0.5)

        return results

    # -------------------------------------------------------------------------
    # Report
    # -------------------------------------------------------------------------

    def generate_report(self, results: Dict[str, ComparisonResult]) -> str:
        lines = []
        lines.append("=" * 100)
        lines.append("MODEL COMPARISON REPORT: Mistral Small 3.2 (mistral-small-2506) vs Small 4 (mistral-small-latest)")
        lines.append(f"Generated: {datetime.now().isoformat()}")
        lines.append(f"Iterations per test: {self.iterations}")
        lines.append(f"Preprocessing tests: {len(PREPROCESSING_TEST_CASES)}")
        lines.append(f"Postprocessing tests: {len(POSTPROCESSING_TEST_CASES)}")
        lines.append("")
        lines.append("Cost delta: Small 4 costs 2x more ($0.20/$0.60 vs $0.10/$0.30 per M tokens).")
        lines.append("Decision criteria: upgrade only if Small 4 shows meaningful quality improvement.")
        lines.append("=" * 100)
        lines.append("")

        all_32 = []
        all_4 = []
        for comp in results.values():
            all_32.extend(comp.small_32_results)
            all_4.extend(comp.small_4_results)

        def stats(rs: List[TestResult]) -> Dict[str, Any]:
            if not rs:
                return {}
            ok = [r for r in rs if r.success]
            lats = [r.latency_ms for r in ok]
            return {
                "total": len(rs),
                "successful": len(ok),
                "success_rate": len(ok) / len(rs) * 100,
                "avg_latency_ms": statistics.mean(lats) if lats else 0,
                "median_latency_ms": statistics.median(lats) if lats else 0,
                "total_cost_usd": sum(r.cost_usd for r in ok),
                "avg_cost_usd": statistics.mean([r.cost_usd for r in ok]) if ok else 0,
                "total_tokens": sum(r.total_tokens for r in ok),
            }

        s32 = stats(all_32)
        s4 = stats(all_4)

        lines.append("OVERALL SUMMARY")
        lines.append("-" * 50)
        col_w = 28

        def winner(a, b, higher_is_better=False):
            if higher_is_better:
                return "Small 3.2" if a > b else ("Small 4" if b > a else "Tie")
            return "Small 3.2" if a < b else ("Small 4" if b < a else "Tie")

        lines.append(f"\n{'Metric':<{col_w}} {'Small 3.2 (2506)':<26} {'Small 4 (latest)':<26} {'Winner'}")
        lines.append("-" * 95)

        sr32 = s32.get("success_rate", 0)
        sr4 = s4.get("success_rate", 0)
        lines.append(f"{'Success Rate':<{col_w}} {sr32:.1f}%{'':<23} {sr4:.1f}%{'':<23} {winner(sr32, sr4, higher_is_better=True)}")

        lat32 = s32.get("avg_latency_ms", 0)
        lat4 = s4.get("avg_latency_ms", 0)
        lines.append(f"{'Avg Latency (ms)':<{col_w}} {lat32:.0f}ms{'':<22} {lat4:.0f}ms{'':<22} {winner(lat32, lat4)}")

        med32 = s32.get("median_latency_ms", 0)
        med4 = s4.get("median_latency_ms", 0)
        lines.append(f"{'Median Latency (ms)':<{col_w}} {med32:.0f}ms{'':<22} {med4:.0f}ms{'':<22} {winner(med32, med4)}")

        c32 = s32.get("avg_cost_usd", 0)
        c4 = s4.get("avg_cost_usd", 0)
        lines.append(f"{'Avg Cost/Request (USD)':<{col_w}} ${c32:.6f}{'':<19} ${c4:.6f}{'':<19} {winner(c32, c4)}")

        tc32 = s32.get("total_cost_usd", 0)
        tc4 = s4.get("total_cost_usd", 0)
        lines.append(f"{'Total Cost (USD)':<{col_w}} ${tc32:.6f}{'':<19} ${tc4:.6f}{'':<19} {winner(tc32, tc4)}")

        lines.append(f"{'Total Tokens':<{col_w}} {s32.get('total_tokens', 0):<26} {s4.get('total_tokens', 0)}")

        # Per-category breakdown
        for category, comp in results.items():
            lines.append("")
            lines.append("=" * 80)
            lines.append(f"CATEGORY: {category.upper()}")
            lines.append("=" * 80)
            summary = comp.get_summary()
            d32 = summary.get("small_32", {})
            d4 = summary.get("small_4", {})

            lines.append(f"\n{'Metric':<{col_w}} {'Small 3.2':<22} {'Small 4':<22} {'Winner'}")
            lines.append("-" * 75)
            lines.append(f"{'Success Rate':<{col_w}} {d32.get('success_rate', 0)*100:.1f}%{'':<19} {d4.get('success_rate', 0)*100:.1f}%{'':<19} {winner(d32.get('success_rate',0), d4.get('success_rate',0), higher_is_better=True)}")
            lines.append(f"{'Avg Latency (ms)':<{col_w}} {d32.get('avg_latency_ms', 0):.0f}ms{'':<18} {d4.get('avg_latency_ms', 0):.0f}ms{'':<18} {winner(d32.get('avg_latency_ms', 0), d4.get('avg_latency_ms', 0))}")
            lines.append(f"{'Median Latency (ms)':<{col_w}} {d32.get('median_latency_ms', 0):.0f}ms{'':<18} {d4.get('median_latency_ms', 0):.0f}ms{'':<18} {winner(d32.get('median_latency_ms', 0), d4.get('median_latency_ms', 0))}")
            lines.append(f"{'Total Cost (USD)':<{col_w}} ${d32.get('total_cost_usd', 0):.6f}{'':<15} ${d4.get('total_cost_usd', 0):.6f}{'':<15} {winner(d32.get('total_cost_usd', 0), d4.get('total_cost_usd', 0))}")

        # Validation accuracy breakdown
        lines.append("")
        lines.append("=" * 80)
        lines.append("VALIDATION ACCURACY BY TEST CASE")
        lines.append("=" * 80)

        for category, comp in results.items():
            lines.append(f"\n--- {category.upper()} ---\n")

            by32: Dict[str, List[TestResult]] = {}
            for r in comp.small_32_results:
                by32.setdefault(r.test_id, []).append(r)

            by4: Dict[str, List[TestResult]] = {}
            for r in comp.small_4_results:
                by4.setdefault(r.test_id, []).append(r)

            for test_id in by32:
                lines.append(f"\nTest: {test_id}")

                def agg_validations(rs: List[TestResult]) -> Dict[str, Dict]:
                    agg: Dict[str, Dict] = {}
                    for r in rs:
                        for k, val in r.validation_results.items():
                            agg.setdefault(k, {"passed": 0, "total": 0})
                            agg[k]["total"] += 1
                            if val.get("passed"):
                                agg[k]["passed"] += 1
                    return agg

                v32 = agg_validations(by32.get(test_id, []))
                v4 = agg_validations(by4.get(test_id, []))

                all_keys = sorted(set(v32) | set(v4))
                for key in all_keys:
                    d32k = v32.get(key, {"passed": 0, "total": 0})
                    d4k = v4.get(key, {"passed": 0, "total": 0})
                    r32pct = d32k["passed"] / d32k["total"] * 100 if d32k["total"] > 0 else 0
                    r4pct = d4k["passed"] / d4k["total"] * 100 if d4k["total"] > 0 else 0
                    i32 = "✓" if r32pct == 100 else ("~" if r32pct > 0 else "✗")
                    i4 = "✓" if r4pct == 100 else ("~" if r4pct > 0 else "✗")
                    lines.append(f"  {key:<28} Small 3.2: {i32} {r32pct:.0f}%  |  Small 4: {i4} {r4pct:.0f}%")

                # Show raw response diff for first iteration
                if by32.get(test_id) and by4.get(test_id):
                    r32_first = by32[test_id][0]
                    r4_first = by4[test_id][0]
                    # Print latency and key fields side-by-side for quick scan
                    lines.append(f"  Latency:  Small 3.2 = {r32_first.latency_ms:.0f}ms  |  Small 4 = {r4_first.latency_ms:.0f}ms")
                    if r32_first.raw_response and r4_first.raw_response:
                        for field in ["complexity", "task_area", "category", "title", "relevant_app_skills"]:
                            v32f = r32_first.raw_response.get(field)
                            v4f = r4_first.raw_response.get(field)
                            if v32f is not None or v4f is not None:
                                diff_marker = " <<<" if v32f != v4f else ""
                                lines.append(f"  {field:<28} 3.2={v32f}  |  4={v4f}{diff_marker}")

        # Recommendation
        lines.append("")
        lines.append("=" * 80)
        lines.append("RECOMMENDATION")
        lines.append("=" * 80)
        lines.append("")

        # Score: quality wins (success rate, validation pass rate) vs cost penalty
        score_32 = 0
        score_4 = 0

        if sr32 > sr4:
            score_32 += 2
        elif sr4 > sr32:
            score_4 += 2

        if lat32 < lat4:
            score_32 += 1
        elif lat4 < lat32:
            score_4 += 1

        # Cost: Small 3.2 always wins on cost
        score_32 += 1

        # Tally per-validation pass rates across all results
        def total_pass_rate(rs: List[TestResult]) -> float:
            total = passed = 0
            for r in rs:
                for val in r.validation_results.values():
                    total += 1
                    if val.get("passed"):
                        passed += 1
            return (passed / total * 100) if total > 0 else 0

        pr32 = total_pass_rate(all_32)
        pr4 = total_pass_rate(all_4)
        if pr4 > pr32 + 5:  # Small 4 needs to be meaningfully better to justify 2x cost
            score_4 += 3
            lines.append(f"Quality delta: Small 4 pass rate {pr4:.1f}% vs Small 3.2 {pr32:.1f}% (+{pr4-pr32:.1f}pp) — MEANINGFUL improvement")
        elif pr32 > pr4:
            score_32 += 2
            lines.append(f"Quality delta: Small 3.2 pass rate {pr32:.1f}% vs Small 4 {pr4:.1f}% — 3.2 wins on quality too")
        else:
            score_32 += 1
            lines.append(f"Quality delta: negligible ({pr32:.1f}% vs {pr4:.1f}%) — does NOT justify 2x price increase")

        lines.append(f"\nOverall score: Small 3.2 = {score_32}, Small 4 = {score_4}")
        lines.append("")

        if score_4 > score_32:
            lines.append("VERDICT: Consider upgrading to Mistral Small 4 (mistral-small-latest)")
            lines.append("Small 4 shows meaningful quality improvements that justify the 2x cost increase.")
            lines.append("Action: Update preprocessing_model in app.yml to mistral/mistral-small-latest")
            lines.append("        and revert all hardcoded mistral-small-2506 back to mistral-small-latest.")
        elif score_32 > score_4:
            lines.append("VERDICT: Keep Mistral Small 3.2 (mistral-small-2506) — no upgrade warranted")
            lines.append("Small 4 does NOT show sufficient quality improvement to justify the 2x cost increase.")
            lines.append("Action: No change needed. Continue using mistral-small-2506 for pre/post-processing.")
        else:
            lines.append("VERDICT: Models perform similarly — keep Small 3.2 on cost grounds")
            lines.append("When quality is equivalent, the 2x cheaper model wins.")
            lines.append("Action: No change needed. Continue using mistral-small-2506.")

        # Cost projection
        lines.append("")
        lines.append("-" * 50)
        lines.append("COST PROJECTION (per 1 million preprocessing requests)")
        lines.append("-" * 50)

        proj32 = c32 * 1_000_000
        proj4 = c4 * 1_000_000
        extra_cost = proj4 - proj32

        lines.append(f"Small 3.2 (2506):   ${proj32:,.2f}")
        lines.append(f"Small 4  (latest):  ${proj4:,.2f}")
        lines.append(
            f"Extra cost w/ Small 4: ${extra_cost:,.2f} per million requests "
            f"({extra_cost/proj32*100:.0f}% more)" if proj32 > 0 else ""
        )

        lines.append("")
        lines.append("=" * 100)
        lines.append("END OF REPORT")
        lines.append("=" * 100)

        return "\n".join(lines)

    def save_results(self, results: Dict[str, ComparisonResult], output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        raw = {
            "timestamp": timestamp,
            "iterations": self.iterations,
            "models": MODELS,
            "results": {},
        }

        for category, comp in results.items():
            raw["results"][category] = {
                "small_32": [
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
                    for r in comp.small_32_results
                ],
                "small_4": [
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
                    for r in comp.small_4_results
                ],
            }

        results_file = output_dir / f"small32_vs_small4_results_{timestamp}.json"
        with open(results_file, "w") as f:
            json.dump(raw, f, indent=2, default=str)
        logger.info(f"Results saved to {results_file}")

        report = self.generate_report(results)
        report_file = output_dir / f"small32_vs_small4_report_{timestamp}.txt"
        with open(report_file, "w") as f:
            f.write(report)
        logger.info(f"Report saved to {report_file}")

        return results_file, report_file


# =============================================================================
# PYTEST FUNCTIONS
# =============================================================================


@pytest.fixture
async def test_runner():
    runner = ModelComparisonTest(iterations=1)
    await runner._ensure_secrets_initialized()
    return runner


@pytest.mark.asyncio
async def test_preprocessing_all(test_runner):
    """Run all preprocessing test cases for both models and log comparison."""
    for test_case in PREPROCESSING_TEST_CASES:
        r32 = await test_runner._run_preprocessing_test(test_case, "small_32")
        r4 = await test_runner._run_preprocessing_test(test_case, "small_4")

        assert r32.success, f"Small 3.2 failed on '{test_case['id']}': {r32.error_message}"
        assert r4.success, f"Small 4 failed on '{test_case['id']}': {r4.error_message}"

        # Log side-by-side for manual review
        logger.info(f"\n[{test_case['id']}]")
        logger.info(f"  Small 3.2: {r32.latency_ms:.0f}ms  complexity={r32.raw_response.get('complexity') if r32.raw_response else 'N/A'}  skills={r32.raw_response.get('relevant_app_skills') if r32.raw_response else []}")
        logger.info(f"  Small 4:   {r4.latency_ms:.0f}ms  complexity={r4.raw_response.get('complexity') if r4.raw_response else 'N/A'}  skills={r4.raw_response.get('relevant_app_skills') if r4.raw_response else []}")

        # Validate each model against expected
        for r, name in [(r32, "Small 3.2"), (r4, "Small 4")]:
            for key, val in r.validation_results.items():
                if not val.get("passed"):
                    logger.warning(f"  {name} FAILED validation '{key}': {val}")


@pytest.mark.asyncio
async def test_preprocessing_complexity_detection(test_runner):
    """Verify both models correctly classify query complexity."""
    complexity_cases = [tc for tc in PREPROCESSING_TEST_CASES if "complexity" in tc.get("expected", {})]

    for test_case in complexity_cases:
        expected_complexity = test_case["expected"]["complexity"]

        r32 = await test_runner._run_preprocessing_test(test_case, "small_32")
        r4 = await test_runner._run_preprocessing_test(test_case, "small_4")

        for r, name in [(r32, "Small 3.2"), (r4, "Small 4")]:
            assert r.success, f"{name} failed on '{test_case['id']}': {r.error_message}"
            if r.raw_response:
                actual = r.raw_response.get("complexity")
                assert actual == expected_complexity, (
                    f"{name} test '{test_case['id']}': expected complexity='{expected_complexity}', got='{actual}'"
                )


@pytest.mark.asyncio
async def test_preprocessing_skill_selection(test_runner):
    """Verify both models select the correct skills."""
    skill_cases = [tc for tc in PREPROCESSING_TEST_CASES if tc.get("expected", {}).get("relevant_app_skills_contains")]

    for test_case in skill_cases:
        expected_skills = test_case["expected"]["relevant_app_skills_contains"]

        r32 = await test_runner._run_preprocessing_test(test_case, "small_32")
        r4 = await test_runner._run_preprocessing_test(test_case, "small_4")

        for r, name in [(r32, "Small 3.2"), (r4, "Small 4")]:
            assert r.success, f"{name} failed on '{test_case['id']}': {r.error_message}"
            if r.raw_response:
                actual_skills = r.raw_response.get("relevant_app_skills", []) or []
                missing = [s for s in expected_skills if s not in actual_skills]
                if missing:
                    logger.warning(f"{name} test '{test_case['id']}': missing skills {missing}. Got: {actual_skills}")


@pytest.mark.asyncio
async def test_preprocessing_safety_scoring(test_runner):
    """Verify both models stay within acceptable safety score thresholds."""
    safety_cases = [tc for tc in PREPROCESSING_TEST_CASES if tc["id"].startswith("safety_")]

    for test_case in safety_cases:
        r32 = await test_runner._run_preprocessing_test(test_case, "small_32")
        r4 = await test_runner._run_preprocessing_test(test_case, "small_4")

        for r, name in [(r32, "Small 3.2"), (r4, "Small 4")]:
            assert r.success, f"{name} failed on '{test_case['id']}': {r.error_message}"
            max_score = test_case["expected"].get("harmful_or_illegal_max")
            if max_score is not None and r.raw_response:
                actual_score = r.raw_response.get("harmful_or_illegal", 0)
                assert actual_score <= max_score, (
                    f"{name} test '{test_case['id']}': harmful score {actual_score} exceeds max {max_score}"
                )


@pytest.mark.asyncio
async def test_postprocessing_all(test_runner):
    """Run all postprocessing test cases for both models and log comparison."""
    for test_case in POSTPROCESSING_TEST_CASES:
        r32 = await test_runner._run_postprocessing_test(test_case, "small_32")
        r4 = await test_runner._run_postprocessing_test(test_case, "small_4")

        assert r32.success, f"Small 3.2 failed on '{test_case['id']}': {r32.error_message}"
        assert r4.success, f"Small 4 failed on '{test_case['id']}': {r4.error_message}"

        for r, name in [(r32, "Small 3.2"), (r4, "Small 4")]:
            if r.raw_response:
                follow_ups = r.raw_response.get("follow_up_request_suggestions", []) or []
                new_chats = r.raw_response.get("new_chat_request_suggestions", []) or []
                logger.info(f"\n[{test_case['id']}] {name}: latency={r.latency_ms:.0f}ms  follow_ups={len(follow_ups)}  new_chats={len(new_chats)}")
                if follow_ups:
                    logger.info(f"  Follow-ups (first 2): {follow_ups[:2]}")
                if new_chats:
                    logger.info(f"  New chats  (first 2): {new_chats[:2]}")


@pytest.mark.asyncio
async def test_full_comparison():
    """Run the full suite and print the comparison report."""
    runner = ModelComparisonTest(iterations=1)
    await runner._ensure_secrets_initialized()
    results = await runner.run_all_tests()

    report = runner.generate_report(results)
    print("\n" + report)

    output_dir = project_root / "backend" / "tests" / "output"
    results_file, report_file = runner.save_results(results, output_dir)
    print(f"\nResults JSON: {results_file}")
    print(f"Report TXT:  {report_file}")

    for category, comp in results.items():
        assert len(comp.small_32_results) > 0, f"No Small 3.2 results for {category}"
        assert len(comp.small_4_results) > 0, f"No Small 4 results for {category}"


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


async def main():
    parser = argparse.ArgumentParser(
        description="Compare Mistral Small 3.2 (mistral-small-2506) vs Small 4 (mistral-small-latest) "
                    "for preprocessing and postprocessing tasks."
    )
    parser.add_argument("--iterations", type=int, default=1,
                        help="Number of iterations per test (default 1; use 2-3 for statistical significance)")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Output directory for JSON results and text report")
    parser.add_argument("--preprocessing-only", action="store_true",
                        help="Run only preprocessing tests")
    parser.add_argument("--postprocessing-only", action="store_true",
                        help="Run only postprocessing tests")

    args = parser.parse_args()
    output_dir = Path(args.output_dir) if args.output_dir else project_root / "backend" / "tests" / "output"

    runner = ModelComparisonTest(iterations=args.iterations)
    await runner._ensure_secrets_initialized()

    logger.info("=" * 60)
    logger.info("Mistral Small 3.2 (mistral-small-2506) vs Small 4 (mistral-small-latest)")
    logger.info(f"Iterations: {args.iterations}")
    logger.info(f"Preprocessing tests: {len(PREPROCESSING_TEST_CASES)}")
    logger.info(f"Postprocessing tests: {len(POSTPROCESSING_TEST_CASES)}")
    logger.info("=" * 60)

    results = await runner.run_all_tests()
    report = runner.generate_report(results)
    print("\n" + report)

    results_file, report_file = runner.save_results(results, output_dir)
    print(f"\nResults JSON: {results_file}")
    print(f"Report TXT:  {report_file}")


if __name__ == "__main__":
    asyncio.run(main())
