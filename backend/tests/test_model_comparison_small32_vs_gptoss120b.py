# backend/tests/test_model_comparison_small32_vs_gptoss120b.py
"""
Model Comparison Test: Mistral Small 3.2 (mistral-small-2506) vs GPT-OSS 120B via Groq

Context: GPT-OSS 120B is an open-source 120B-parameter model available via Groq's ultra-fast
inference API. It is significantly larger than Mistral Small 3.2 (24B) and may produce higher
quality outputs, but the cost is higher ($0.25/$0.69 vs $0.10/$0.30 per M tokens — 2.5x/2.3x).
Groq's inference hardware may also provide speed advantages despite the larger model size.

We currently pin mistral-small-2506 for all preprocessing/postprocessing. This test evaluates
whether GPT-OSS 120B via Groq offers better quality and/or speed for our specific use cases.

Models compared:
- Current:   mistral/mistral-small-2506       (Mistral Small 3.2, 24B, $0.10/$0.30 per M)
- Candidate: groq/openai/gpt-oss-120b         (GPT-OSS 120B via Groq, $0.25/$0.69 per M)

Note on model ID: "groq/openai/gpt-oss-120b" bypasses YAML server resolution and routes
directly to the Groq API using model identifier "openai/gpt-oss-120b". This is the same
format used internally by the groq_client after server resolution for other OpenAI OSS models.

Test categories:
1. Preprocessing  — Request routing, complexity, skill selection, safety scoring
2. Postprocessing — Follow-up + new chat suggestion generation

Uses the same 23 preprocessing + 4 postprocessing test cases as previous comparisons
to keep results comparable across evaluations.

Usage:
    # Full comparison (default 5 iterations):
    python backend/tests/test_model_comparison_small32_vs_gptoss120b.py

    # Quick single run:
    python backend/tests/test_model_comparison_small32_vs_gptoss120b.py --iterations 1

    # Preprocessing only:
    python backend/tests/test_model_comparison_small32_vs_gptoss120b.py --preprocessing-only

    # Via pytest (individual categories):
    python -m pytest backend/tests/test_model_comparison_small32_vs_gptoss120b.py -v -s -k "preprocessing"
    python -m pytest backend/tests/test_model_comparison_small32_vs_gptoss120b.py -v -s -k "postprocessing"
    python -m pytest backend/tests/test_model_comparison_small32_vs_gptoss120b.py -v -s -k "full_comparison"

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

# Exclude from daily CI — these are expensive inference benchmarks, not regression tests.
pytestmark = pytest.mark.benchmark
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv  # noqa: E402
    load_dotenv()

    from backend.apps.ai.utils.llm_utils import (  # noqa: E402
        call_preprocessing_llm,
        LLMPreprocessingCallResult,
    )
    from backend.core.api.app.utils.secrets_manager import SecretsManager  # noqa: E402
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend AI dependencies not installed: {_exc}")

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
        "id": "mistral/mistral-small-2506",     # Pinned Small 3.2 — current production model
        "name": "Mistral Small 3.2 (2506)",
        "cost_input_per_million": 0.10,
        "cost_output_per_million": 0.30,
    },
    "gpt_oss_120b": {
        # "groq/openai/gpt-oss-120b" routes directly to Groq API using model ID "openai/gpt-oss-120b"
        # This bypasses YAML default_server resolution (which would use Cerebras via OpenRouter).
        "id": "groq/openai/gpt-oss-120b",
        "name": "GPT-OSS 120B (Groq)",
        "cost_input_per_million": 0.25,
        "cost_output_per_million": 0.69,
    },
}

# =============================================================================
# TEST DATA — Preprocessing Scenarios
# Reuses the same test cases as test_model_comparison_small32_vs_small4.py
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
    latency_ms: float          # total wall-clock time including network round-trip
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float            # actual cost computed from real token counts
    raw_response: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    validation_results: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def output_tokens_per_second(self) -> float:
        """Output tokens generated per second (proxy for generation speed)."""
        if not self.success or self.output_tokens == 0 or self.latency_ms == 0:
            return 0.0
        return self.output_tokens / (self.latency_ms / 1000.0)

    @property
    def total_tokens_per_second(self) -> float:
        """Total tokens processed per second (input + output throughput)."""
        if not self.success or self.total_tokens == 0 or self.latency_ms == 0:
            return 0.0
        return self.total_tokens / (self.latency_ms / 1000.0)

    @property
    def cost_per_1k_requests_usd(self) -> float:
        """Projected cost for 1,000 identical requests."""
        return self.cost_usd * 1000


@dataclass
class ComparisonResult:
    """Aggregated comparison between Small 3.2 and GPT-OSS 120B."""
    test_category: str
    small_32_results: List[TestResult]
    gpt_oss_120b_results: List[TestResult]

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
            "gpt_oss_120b": calc_stats(self.gpt_oss_120b_results),
        }


# =============================================================================
# TEST RUNNER
# =============================================================================


class ModelComparisonTest:
    """Runs comparison tests between Mistral Small 3.2 (pinned) and GPT-OSS 120B via Groq."""

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

    async def run_all_tests(
        self,
        preprocessing_only: bool = False,
        postprocessing_only: bool = False,
    ) -> Dict[str, ComparisonResult]:
        results = {
            "preprocessing": ComparisonResult(
                test_category="preprocessing",
                small_32_results=[],
                gpt_oss_120b_results=[],
            ),
            "postprocessing": ComparisonResult(
                test_category="postprocessing",
                small_32_results=[],
                gpt_oss_120b_results=[],
            ),
        }

        if not postprocessing_only:
            logger.info("=" * 80)
            logger.info("STARTING PREPROCESSING TESTS")
            logger.info("=" * 80)

            for test_case in PREPROCESSING_TEST_CASES:
                for iteration in range(self.iterations):
                    logger.info(f"\nIteration {iteration + 1}/{self.iterations} — test '{test_case['id']}'")

                    r32 = await self._run_preprocessing_test(test_case, "small_32")
                    results["preprocessing"].small_32_results.append(r32)
                    self.results.append(r32)

                    r120b = await self._run_preprocessing_test(test_case, "gpt_oss_120b")
                    results["preprocessing"].gpt_oss_120b_results.append(r120b)
                    self.results.append(r120b)

                    await asyncio.sleep(0.5)

        if not preprocessing_only:
            logger.info("=" * 80)
            logger.info("STARTING POSTPROCESSING TESTS")
            logger.info("=" * 80)

            for test_case in POSTPROCESSING_TEST_CASES:
                for iteration in range(self.iterations):
                    logger.info(f"\nIteration {iteration + 1}/{self.iterations} — test '{test_case['id']}'")

                    r32 = await self._run_postprocessing_test(test_case, "small_32")
                    results["postprocessing"].small_32_results.append(r32)
                    self.results.append(r32)

                    r120b = await self._run_postprocessing_test(test_case, "gpt_oss_120b")
                    results["postprocessing"].gpt_oss_120b_results.append(r120b)
                    self.results.append(r120b)

                    await asyncio.sleep(0.5)

        return results

    # -------------------------------------------------------------------------
    # Report
    # -------------------------------------------------------------------------

    def generate_report(self, results: Dict[str, ComparisonResult]) -> str:  # noqa: C901
        lines = []
        W = 100
        lines.append("=" * W)
        lines.append("MODEL COMPARISON REPORT: Mistral Small 3.2 (mistral-small-2506) vs GPT-OSS 120B (Groq)")
        lines.append(f"Generated:  {datetime.now().isoformat()}")
        lines.append(f"Iterations: {self.iterations} per test case")
        lines.append(f"Tests:      {len(PREPROCESSING_TEST_CASES)} preprocessing + {len(POSTPROCESSING_TEST_CASES)} postprocessing")
        lines.append("Note:       Latency = full wall-clock round-trip (network + inference + function-call parse).")
        lines.append("            Tokens/sec = output_tokens / latency_s  (generation throughput proxy).")
        lines.append("            GPT-OSS 120B routed via Groq API (model ID: openai/gpt-oss-120b).")
        lines.append("=" * W)
        lines.append("")

        all_32 = []
        all_120b = []
        for comp in results.values():
            all_32.extend(comp.small_32_results)
            all_120b.extend(comp.gpt_oss_120b_results)

        def full_stats(rs: List[TestResult]) -> Dict[str, Any]:
            if not rs:
                return {}
            ok = [r for r in rs if r.success]
            if not ok:
                return {"total": len(rs), "successful": 0, "success_rate": 0}

            lats = [r.latency_ms for r in ok]
            costs = [r.cost_usd for r in ok]
            out_toks = [r.output_tokens for r in ok]
            in_toks = [r.input_tokens for r in ok]
            total_toks = [r.total_tokens for r in ok]
            otps = [r.output_tokens_per_second for r in ok if r.output_tokens_per_second > 0]

            lats_sorted = sorted(lats)
            p95_idx = max(0, int(len(lats_sorted) * 0.95) - 1)

            return {
                "total": len(rs),
                "successful": len(ok),
                "success_rate": len(ok) / len(rs) * 100,
                # latency
                "avg_latency_ms": statistics.mean(lats),
                "median_latency_ms": statistics.median(lats),
                "p95_latency_ms": lats_sorted[p95_idx],
                "min_latency_ms": min(lats),
                "max_latency_ms": max(lats),
                "stdev_latency_ms": statistics.stdev(lats) if len(lats) > 1 else 0,
                # tokens
                "avg_input_tokens": statistics.mean(in_toks),
                "avg_output_tokens": statistics.mean(out_toks),
                "avg_total_tokens": statistics.mean(total_toks),
                "total_input_tokens": sum(in_toks),
                "total_output_tokens": sum(out_toks),
                "total_tokens": sum(total_toks),
                # speed
                "avg_output_toks_per_sec": statistics.mean(otps) if otps else 0,
                "median_output_toks_per_sec": statistics.median(otps) if otps else 0,
                # cost
                "avg_cost_usd": statistics.mean(costs),
                "median_cost_usd": statistics.median(costs),
                "min_cost_usd": min(costs),
                "max_cost_usd": max(costs),
                "total_cost_usd": sum(costs),
            }

        s32 = full_stats(all_32)
        s120b = full_stats(all_120b)

        col_w = 34

        def w(a, b, higher_is_better=False):
            if higher_is_better:
                return "Small 3.2 ✓" if a > b else ("GPT-OSS 120B ✓" if b > a else "Tie")
            return "Small 3.2 ✓" if a < b else ("GPT-OSS 120B ✓" if b < a else "Tie")

        # ── SECTION 1: OVERALL SUMMARY ────────────────────────────────────────
        lines.append("┌─────────────────────────────────────────────────────────────────────────────────────────────────┐")
        lines.append("│  SECTION 1: OVERALL SUMMARY                                                                     │")
        lines.append("└─────────────────────────────────────────────────────────────────────────────────────────────────┘")
        lines.append(f"\n{'Metric':<{col_w}} {'Small 3.2 (2506)':<28} {'GPT-OSS 120B (Groq)':<28} {'Winner'}")
        lines.append("-" * W)

        sr32 = s32.get("success_rate", 0)
        sr120b = s120b.get("success_rate", 0)
        lines.append(f"{'Success Rate':<{col_w}} {sr32:.1f}%{'':<25} {sr120b:.1f}%{'':<25} {w(sr32, sr120b, higher_is_better=True)}")

        # ── SECTION 2: SPEED & PROCESSING TIME ────────────────────────────────
        lines.append("")
        lines.append("┌─────────────────────────────────────────────────────────────────────────────────────────────────┐")
        lines.append("│  SECTION 2: SPEED & TOTAL PROCESSING TIME                                                       │")
        lines.append("│  (wall-clock latency = full round-trip: DNS + TLS + queuing + inference + tool-call parse)      │")
        lines.append("└─────────────────────────────────────────────────────────────────────────────────────────────────┘")
        lines.append(f"\n{'Metric':<{col_w}} {'Small 3.2 (2506)':<28} {'GPT-OSS 120B (Groq)':<28} {'Winner'}")
        lines.append("-" * W)

        lat32 = s32.get("avg_latency_ms", 0)
        lat120b = s120b.get("avg_latency_ms", 0)
        lines.append(f"{'Avg latency (ms)':<{col_w}} {lat32:.0f} ms{'':<24} {lat120b:.0f} ms{'':<24} {w(lat32, lat120b)}")

        med32 = s32.get("median_latency_ms", 0)
        med120b = s120b.get("median_latency_ms", 0)
        lines.append(f"{'Median latency (ms)':<{col_w}} {med32:.0f} ms{'':<24} {med120b:.0f} ms{'':<24} {w(med32, med120b)}")

        p9532 = s32.get("p95_latency_ms", 0)
        p95120b = s120b.get("p95_latency_ms", 0)
        lines.append(f"{'P95 latency (ms)':<{col_w}} {p9532:.0f} ms{'':<24} {p95120b:.0f} ms{'':<24} {w(p9532, p95120b)}")

        min32 = s32.get("min_latency_ms", 0)
        min120b = s120b.get("min_latency_ms", 0)
        lines.append(f"{'Min latency (ms)':<{col_w}} {min32:.0f} ms{'':<24} {min120b:.0f} ms{'':<24} {w(min32, min120b)}")

        max32 = s32.get("max_latency_ms", 0)
        max120b = s120b.get("max_latency_ms", 0)
        lines.append(f"{'Max latency (ms)':<{col_w}} {max32:.0f} ms{'':<24} {max120b:.0f} ms{'':<24} {w(max32, max120b)}")

        std32 = s32.get("stdev_latency_ms", 0)
        std120b = s120b.get("stdev_latency_ms", 0)
        lines.append(f"{'Latency std-dev (ms)':<{col_w}} {std32:.0f} ms{'':<24} {std120b:.0f} ms{'':<24} {w(std32, std120b)}")

        lines.append("")
        otps32 = s32.get("avg_output_toks_per_sec", 0)
        otps120b = s120b.get("avg_output_toks_per_sec", 0)
        lines.append(f"{'Avg output tok/s':<{col_w}} {otps32:.1f} tok/s{'':<21} {otps120b:.1f} tok/s{'':<21} {w(otps32, otps120b, higher_is_better=True)}")

        motps32 = s32.get("median_output_toks_per_sec", 0)
        motps120b = s120b.get("median_output_toks_per_sec", 0)
        lines.append(f"{'Median output tok/s':<{col_w}} {motps32:.1f} tok/s{'':<21} {motps120b:.1f} tok/s{'':<21} {w(motps32, motps120b, higher_is_better=True)}")

        # ── SECTION 3: TOKEN USAGE ─────────────────────────────────────────────
        lines.append("")
        lines.append("┌─────────────────────────────────────────────────────────────────────────────────────────────────┐")
        lines.append("│  SECTION 3: TOKEN USAGE (avg per request)                                                       │")
        lines.append("└─────────────────────────────────────────────────────────────────────────────────────────────────┘")
        lines.append(f"\n{'Metric':<{col_w}} {'Small 3.2 (2506)':<28} {'GPT-OSS 120B (Groq)':<28} {'Winner'}")
        lines.append("-" * W)

        ai32 = s32.get("avg_input_tokens", 0)
        ai120b = s120b.get("avg_input_tokens", 0)
        lines.append(f"{'Avg input tokens':<{col_w}} {ai32:.0f}{'':<27} {ai120b:.0f}{'':<27} {w(ai32, ai120b)}")

        ao32 = s32.get("avg_output_tokens", 0)
        ao120b = s120b.get("avg_output_tokens", 0)
        lines.append(f"{'Avg output tokens':<{col_w}} {ao32:.0f}{'':<27} {ao120b:.0f}{'':<27} {w(ao32, ao120b)}")

        at32 = s32.get("avg_total_tokens", 0)
        at120b = s120b.get("avg_total_tokens", 0)
        lines.append(f"{'Avg total tokens':<{col_w}} {at32:.0f}{'':<27} {at120b:.0f}{'':<27} {w(at32, at120b)}")

        lines.append(f"{'Total input tokens (run)':<{col_w}} {s32.get('total_input_tokens',0):<28} {s120b.get('total_input_tokens',0)}")
        lines.append(f"{'Total output tokens (run)':<{col_w}} {s32.get('total_output_tokens',0):<28} {s120b.get('total_output_tokens',0)}")
        lines.append(f"{'Total tokens (run)':<{col_w}} {s32.get('total_tokens',0):<28} {s120b.get('total_tokens',0)}")

        # ── SECTION 4: COST ────────────────────────────────────────────────────
        lines.append("")
        lines.append("┌─────────────────────────────────────────────────────────────────────────────────────────────────┐")
        lines.append("│  SECTION 4: ACTUAL COST (computed from real token counts, not estimated from list price)        │")
        lines.append("│  Small 3.2: $0.10/M input + $0.30/M output    GPT-OSS 120B: $0.25/M input + $0.69/M output     │")
        lines.append("└─────────────────────────────────────────────────────────────────────────────────────────────────┘")
        lines.append(f"\n{'Metric':<{col_w}} {'Small 3.2 (2506)':<28} {'GPT-OSS 120B (Groq)':<28} {'Winner'}")
        lines.append("-" * W)

        c32 = s32.get("avg_cost_usd", 0)
        c120b = s120b.get("avg_cost_usd", 0)
        lines.append(f"{'Avg cost per request ($)':<{col_w}} ${c32:.6f}{'':<21} ${c120b:.6f}{'':<21} {w(c32, c120b)}")

        mc32 = s32.get("median_cost_usd", 0)
        mc120b = s120b.get("median_cost_usd", 0)
        lines.append(f"{'Median cost per request ($)':<{col_w}} ${mc32:.6f}{'':<21} ${mc120b:.6f}{'':<21} {w(mc32, mc120b)}")

        minc32 = s32.get("min_cost_usd", 0)
        minc120b = s120b.get("min_cost_usd", 0)
        lines.append(f"{'Min cost per request ($)':<{col_w}} ${minc32:.6f}{'':<21} ${minc120b:.6f}{'':<21} {w(minc32, minc120b)}")

        maxc32 = s32.get("max_cost_usd", 0)
        maxc120b = s120b.get("max_cost_usd", 0)
        lines.append(f"{'Max cost per request ($)':<{col_w}} ${maxc32:.6f}{'':<21} ${maxc120b:.6f}{'':<21} {w(maxc32, maxc120b)}")

        tc32 = s32.get("total_cost_usd", 0)
        tc120b = s120b.get("total_cost_usd", 0)
        lines.append(f"{'Total cost this run ($)':<{col_w}} ${tc32:.6f}{'':<21} ${tc120b:.6f}{'':<21} {w(tc32, tc120b)}")

        lines.append("")
        proj_1k_32 = c32 * 1_000
        proj_1k_120b = c120b * 1_000
        proj_1m_32 = c32 * 1_000_000
        proj_1m_120b = c120b * 1_000_000
        delta_1m = proj_1m_120b - proj_1m_32
        pct_more = (delta_1m / proj_1m_32 * 100) if proj_1m_32 > 0 else 0

        lines.append(f"{'Projected / 1k requests ($)':<{col_w}} ${proj_1k_32:>10,.4f}{'':<17} ${proj_1k_120b:>10,.4f}{'':<17} {w(proj_1k_32, proj_1k_120b)}")
        lines.append(f"{'Projected / 1M requests ($)':<{col_w}} ${proj_1m_32:>10,.2f}{'':<17} ${proj_1m_120b:>10,.2f}{'':<17} {w(proj_1m_32, proj_1m_120b)}")
        lines.append(f"{'Cost premium for GPT-OSS 120B':<{col_w}} {'—':<28} ${delta_1m:,.2f} extra/1M req ({pct_more:.0f}% more)")

        # ── SECTION 5: PER-CATEGORY BREAKDOWN ─────────────────────────────────
        lines.append("")
        lines.append("┌─────────────────────────────────────────────────────────────────────────────────────────────────┐")
        lines.append("│  SECTION 5: PER-CATEGORY BREAKDOWN                                                              │")
        lines.append("└─────────────────────────────────────────────────────────────────────────────────────────────────┘")

        for category, comp in results.items():
            lines.append(f"\n── {category.upper()} ──")
            rs32_cat = [r for r in comp.small_32_results if r.success]
            rs120b_cat = [r for r in comp.gpt_oss_120b_results if r.success]

            def cat_stats(rs_ok: List[TestResult]) -> Dict[str, Any]:
                if not rs_ok:
                    return {}
                lats = [r.latency_ms for r in rs_ok]
                otps_list = [r.output_tokens_per_second for r in rs_ok if r.output_tokens_per_second > 0]
                return {
                    "n": len(rs_ok),
                    "avg_lat": statistics.mean(lats),
                    "med_lat": statistics.median(lats),
                    "avg_otps": statistics.mean(otps_list) if otps_list else 0,
                    "avg_in_tok": statistics.mean([r.input_tokens for r in rs_ok]),
                    "avg_out_tok": statistics.mean([r.output_tokens for r in rs_ok]),
                    "avg_cost": statistics.mean([r.cost_usd for r in rs_ok]),
                    "success_rate": len(rs_ok) / max(len(comp.small_32_results), 1) * 100,
                }

            d32c = cat_stats(rs32_cat)
            d120bc = cat_stats(rs120b_cat)
            if not d32c or not d120bc:
                continue

            lines.append(f"  {'Metric':<32} {'Small 3.2':<22} {'GPT-OSS 120B':<22} {'Winner'}")
            lines.append(f"  {'-'*90}")
            lines.append(f"  {'Success Rate':<32} {d32c['success_rate']:.0f}%{'':<19} {d120bc['success_rate']:.0f}%{'':<19} {w(d32c['success_rate'], d120bc['success_rate'], higher_is_better=True)}")
            lines.append(f"  {'Avg latency (ms)':<32} {d32c['avg_lat']:.0f} ms{'':<18} {d120bc['avg_lat']:.0f} ms{'':<18} {w(d32c['avg_lat'], d120bc['avg_lat'])}")
            lines.append(f"  {'Median latency (ms)':<32} {d32c['med_lat']:.0f} ms{'':<18} {d120bc['med_lat']:.0f} ms{'':<18} {w(d32c['med_lat'], d120bc['med_lat'])}")
            lines.append(f"  {'Avg output tok/s':<32} {d32c['avg_otps']:.1f} tok/s{'':<15} {d120bc['avg_otps']:.1f} tok/s{'':<15} {w(d32c['avg_otps'], d120bc['avg_otps'], higher_is_better=True)}")
            lines.append(f"  {'Avg input tokens':<32} {d32c['avg_in_tok']:.0f}{'':<21} {d120bc['avg_in_tok']:.0f}{'':<21} {w(d32c['avg_in_tok'], d120bc['avg_in_tok'])}")
            lines.append(f"  {'Avg output tokens':<32} {d32c['avg_out_tok']:.0f}{'':<21} {d120bc['avg_out_tok']:.0f}{'':<21} {w(d32c['avg_out_tok'], d120bc['avg_out_tok'])}")
            lines.append(f"  {'Avg cost per request ($)':<32} ${d32c['avg_cost']:.6f}{'':<15} ${d120bc['avg_cost']:.6f}{'':<15} {w(d32c['avg_cost'], d120bc['avg_cost'])}")

        # ── SECTION 6: VALIDATION ACCURACY ────────────────────────────────────
        lines.append("")
        lines.append("┌─────────────────────────────────────────────────────────────────────────────────────────────────┐")
        lines.append("│  SECTION 6: VALIDATION ACCURACY BY TEST CASE                                                    │")
        lines.append("└─────────────────────────────────────────────────────────────────────────────────────────────────┘")

        for category, comp in results.items():
            lines.append(f"\n── {category.upper()} ──\n")

            by32: Dict[str, List[TestResult]] = {}
            for r in comp.small_32_results:
                by32.setdefault(r.test_id, []).append(r)

            by120b: Dict[str, List[TestResult]] = {}
            for r in comp.gpt_oss_120b_results:
                by120b.setdefault(r.test_id, []).append(r)

            def agg_validations(rs: List[TestResult]) -> Dict[str, Dict]:
                agg: Dict[str, Dict] = {}
                for r in rs:
                    for k, val in r.validation_results.items():
                        agg.setdefault(k, {"passed": 0, "total": 0})
                        agg[k]["total"] += 1
                        if val.get("passed"):
                            agg[k]["passed"] += 1
                return agg

            for test_id in by32:
                v32 = agg_validations(by32.get(test_id, []))
                v120b_v = agg_validations(by120b.get(test_id, []))

                ok32 = [r for r in by32.get(test_id, []) if r.success]
                ok120b = [r for r in by120b.get(test_id, []) if r.success]
                lat32t = statistics.mean([r.latency_ms for r in ok32]) if ok32 else 0
                lat120bt = statistics.mean([r.latency_ms for r in ok120b]) if ok120b else 0
                otps32t = statistics.mean([r.output_tokens_per_second for r in ok32 if r.output_tokens_per_second]) if ok32 else 0
                otps120bt = statistics.mean([r.output_tokens_per_second for r in ok120b if r.output_tokens_per_second]) if ok120b else 0
                cost32t = statistics.mean([r.cost_usd for r in ok32]) if ok32 else 0
                cost120bt = statistics.mean([r.cost_usd for r in ok120b]) if ok120b else 0

                lines.append(f"\n  Test: {test_id}")
                lines.append(f"    Latency:   3.2={lat32t:.0f}ms  |  120B={lat120bt:.0f}ms  ({w(lat32t, lat120bt)})")
                lines.append(f"    Out tok/s: 3.2={otps32t:.1f}  |  120B={otps120bt:.1f}  ({w(otps32t, otps120bt, higher_is_better=True)})")
                lines.append(f"    Cost:      3.2=${cost32t:.6f}  |  120B=${cost120bt:.6f}  ({w(cost32t, cost120bt)})")

                all_keys = sorted(set(v32) | set(v120b_v))
                for key in all_keys:
                    d32k = v32.get(key, {"passed": 0, "total": 0})
                    d120bk = v120b_v.get(key, {"passed": 0, "total": 0})
                    r32pct = d32k["passed"] / d32k["total"] * 100 if d32k["total"] > 0 else 0
                    r120bpct = d120bk["passed"] / d120bk["total"] * 100 if d120bk["total"] > 0 else 0
                    i32 = "✓" if r32pct == 100 else ("~" if r32pct > 0 else "✗")
                    i120b = "✓" if r120bpct == 100 else ("~" if r120bpct > 0 else "✗")
                    diff = " <<<" if abs(r32pct - r120bpct) >= 50 else ""
                    lines.append(f"    {key:<30} 3.2: {i32} {r32pct:.0f}%   120B: {i120b} {r120bpct:.0f}%{diff}")

                # Show first-iteration response diff for key fields
                if by32.get(test_id) and by120b.get(test_id):
                    r32_f = by32[test_id][0]
                    r120b_f = by120b[test_id][0]
                    if r32_f.raw_response and r120b_f.raw_response:
                        for fld in ["complexity", "task_area", "category", "relevant_app_skills"]:
                            v32f = r32_f.raw_response.get(fld)
                            v120bf = r120b_f.raw_response.get(fld)
                            if v32f is not None or v120bf is not None:
                                diff_marker = " <-- DIFFERS" if v32f != v120bf else ""
                                lines.append(f"    {fld:<30} 3.2={v32f!r:<30}  120B={v120bf!r}{diff_marker}")

        # ── SECTION 7: RECOMMENDATION ─────────────────────────────────────────
        lines.append("")
        lines.append("┌─────────────────────────────────────────────────────────────────────────────────────────────────┐")
        lines.append("│  SECTION 7: RECOMMENDATION                                                                      │")
        lines.append("└─────────────────────────────────────────────────────────────────────────────────────────────────┘")
        lines.append("")

        score_32 = 0
        score_120b = 0

        if sr32 > sr120b:
            score_32 += 2
        elif sr120b > sr32:
            score_120b += 2

        if lat32 < lat120b:
            score_32 += 1
        elif lat120b < lat32:
            score_120b += 1

        score_32 += 1  # cost always favours Small 3.2

        def total_pass_rate(rs: List[TestResult]) -> float:
            total = passed = 0
            for r in rs:
                for val in r.validation_results.values():
                    total += 1
                    if val.get("passed"):
                        passed += 1
            return (passed / total * 100) if total > 0 else 0

        pr32 = total_pass_rate(all_32)
        pr120b = total_pass_rate(all_120b)
        if pr120b > pr32 + 5:
            score_120b += 3
            lines.append(f"  Quality: GPT-OSS 120B pass rate {pr120b:.1f}% vs Small 3.2 {pr32:.1f}% (+{pr120b-pr32:.1f}pp) — MEANINGFUL quality gain")
        elif pr32 > pr120b:
            score_32 += 2
            lines.append(f"  Quality: Small 3.2 pass rate {pr32:.1f}% vs GPT-OSS 120B {pr120b:.1f}% — 3.2 wins on quality")
        else:
            score_32 += 1
            lines.append(f"  Quality: negligible delta ({pr32:.1f}% vs {pr120b:.1f}%) — does NOT justify higher cost")

        lines.append(f"  Speed:   Small 3.2 avg {lat32:.0f}ms vs GPT-OSS 120B avg {lat120b:.0f}ms  "
                     f"(3.2 is {abs(lat120b-lat32):.0f}ms {'faster' if lat32 < lat120b else 'slower'})")
        lines.append(f"  Cost:    Small 3.2 ${c32:.6f}/req vs GPT-OSS 120B ${c120b:.6f}/req  "
                     f"(GPT-OSS 120B costs {(c120b/c32 - 1)*100:.0f}% more per request)" if c32 > 0 else "")
        lines.append(f"\n  Score: Small 3.2 = {score_32}pts  |  GPT-OSS 120B = {score_120b}pts")
        lines.append("")

        if score_120b > score_32:
            lines.append("  VERDICT: Consider switching to GPT-OSS 120B via Groq")
            lines.append("  GPT-OSS 120B shows meaningful quality or speed improvements that may justify the cost increase.")
            lines.append("  Action: app.yml → preprocessing_model: groq/openai/gpt-oss-120b")
            lines.append("          Also update any hardcoded model IDs for preprocessing/postprocessing.")
        elif score_32 > score_120b:
            lines.append("  VERDICT: Keep Mistral Small 3.2 (mistral-small-2506) — no switch warranted")
            lines.append("  GPT-OSS 120B does NOT show sufficient quality improvement to justify higher cost.")
            lines.append("  Action: No change needed.")
        else:
            lines.append("  VERDICT: Models perform similarly — keep Small 3.2 on cost grounds")
            lines.append("  Action: No change needed.")

        lines.append("")
        lines.append("=" * W)
        lines.append("END OF REPORT")
        lines.append("=" * W)
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

        def _serialise(r: "TestResult") -> Dict[str, Any]:
            return {
                "test_id": r.test_id,
                "success": r.success,
                "latency_ms": round(r.latency_ms, 2),
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "total_tokens": r.total_tokens,
                "output_tokens_per_second": round(r.output_tokens_per_second, 2),
                "total_tokens_per_second": round(r.total_tokens_per_second, 2),
                "cost_usd": r.cost_usd,
                "cost_per_1k_requests_usd": round(r.cost_per_1k_requests_usd, 6),
                "validation": r.validation_results,
                "raw_response": r.raw_response,
                "error": r.error_message,
                "timestamp": r.timestamp,
            }

        for category, comp in results.items():
            raw["results"][category] = {
                "small_32":     [_serialise(r) for r in comp.small_32_results],
                "gpt_oss_120b": [_serialise(r) for r in comp.gpt_oss_120b_results],
            }

        results_file = output_dir / f"small32_vs_gptoss120b_results_{timestamp}.json"
        with open(results_file, "w") as f:
            json.dump(raw, f, indent=2, default=str)
        logger.info(f"Results saved to {results_file}")

        report = self.generate_report(results)
        report_file = output_dir / f"small32_vs_gptoss120b_report_{timestamp}.txt"
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
        r120b = await test_runner._run_preprocessing_test(test_case, "gpt_oss_120b")

        assert r32.success, f"Small 3.2 failed on '{test_case['id']}': {r32.error_message}"
        assert r120b.success, f"GPT-OSS 120B failed on '{test_case['id']}': {r120b.error_message}"

        logger.info(f"\n[{test_case['id']}]")
        logger.info(f"  Small 3.2:    {r32.latency_ms:.0f}ms  complexity={r32.raw_response.get('complexity') if r32.raw_response else 'N/A'}  skills={r32.raw_response.get('relevant_app_skills') if r32.raw_response else []}")
        logger.info(f"  GPT-OSS 120B: {r120b.latency_ms:.0f}ms  complexity={r120b.raw_response.get('complexity') if r120b.raw_response else 'N/A'}  skills={r120b.raw_response.get('relevant_app_skills') if r120b.raw_response else []}")

        for r, name in [(r32, "Small 3.2"), (r120b, "GPT-OSS 120B")]:
            for key, val in r.validation_results.items():
                if not val.get("passed"):
                    logger.warning(f"  {name} FAILED validation '{key}': {val}")


@pytest.mark.asyncio
async def test_postprocessing_all(test_runner):
    """Run all postprocessing test cases for both models and log comparison."""
    for test_case in POSTPROCESSING_TEST_CASES:
        r32 = await test_runner._run_postprocessing_test(test_case, "small_32")
        r120b = await test_runner._run_postprocessing_test(test_case, "gpt_oss_120b")

        assert r32.success, f"Small 3.2 failed on '{test_case['id']}': {r32.error_message}"
        assert r120b.success, f"GPT-OSS 120B failed on '{test_case['id']}': {r120b.error_message}"

        for r, name in [(r32, "Small 3.2"), (r120b, "GPT-OSS 120B")]:
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
        assert len(comp.gpt_oss_120b_results) > 0, f"No GPT-OSS 120B results for {category}"


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


async def main():
    parser = argparse.ArgumentParser(
        description="Compare Mistral Small 3.2 (mistral-small-2506) vs GPT-OSS 120B via Groq "
                    "for preprocessing and postprocessing tasks."
    )
    parser.add_argument("--iterations", type=int, default=5,
                        help="Number of iterations per test (default 5 for statistical significance)")
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
    logger.info("Mistral Small 3.2 (mistral-small-2506) vs GPT-OSS 120B (Groq)")
    logger.info(f"Iterations: {args.iterations}")
    logger.info(f"Preprocessing tests: {len(PREPROCESSING_TEST_CASES)}")
    logger.info(f"Postprocessing tests: {len(POSTPROCESSING_TEST_CASES)}")
    logger.info("=" * 60)

    results = await runner.run_all_tests(
        preprocessing_only=args.preprocessing_only,
        postprocessing_only=args.postprocessing_only,
    )
    report = runner.generate_report(results)
    print("\n" + report)

    results_file, report_file = runner.save_results(results, output_dir)
    print(f"\nResults JSON: {results_file}")
    print(f"Report TXT:  {report_file}")


if __name__ == "__main__":
    asyncio.run(main())
