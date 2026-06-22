# backend/tests/test_daily_inspiration_wiki_generator.py
#
# Regression tests for personalized Wikipedia Daily Inspirations.
# These cards bypass the video channel classifier, so they need their own
# content-policy guardrails before entries enter the public inspiration pool.
#
# Run: python -m pytest backend/tests/test_daily_inspiration_wiki_generator.py -v

import asyncio
import importlib
import sys
import types
from types import SimpleNamespace

from backend.shared.providers.wikipedia.wikipedia_api import WikipediaTopic


fake_llm_utils = types.ModuleType("backend.apps.ai.utils.llm_utils")


class FakeLLMPreprocessingCallResult(SimpleNamespace):
    def __init__(self, error_message=None, arguments=None, **kwargs):
        super().__init__(error_message=error_message, arguments=arguments or {}, **kwargs)


fake_llm_utils.LLMPreprocessingCallResult = FakeLLMPreprocessingCallResult
fake_llm_utils.call_preprocessing_llm = None
fake_llm_utils.resolve_fallback_servers_from_provider_config = lambda _model_id: []
fake_llm_utils.truncate_message_history_to_token_budget = lambda message_history, **_kwargs: message_history


def test_wiki_generator_rejects_company_profile_cards(monkeypatch) -> None:
    """Wikipedia cards must not promote company profiles like SpaceX."""
    monkeypatch.setitem(sys.modules, "backend.apps.ai.utils.llm_utils", fake_llm_utils)
    wiki_generator = importlib.import_module("backend.apps.ai.daily_inspiration.wiki_generator")

    async def fake_call_preprocessing_llm(*_args, **_kwargs):
        return SimpleNamespace(
            error_message=None,
            arguments={
                "articles": [
                    {
                        "wiki_title": "SpaceX",
                        "phrase": "How has SpaceX revolutionized tech? Explore its impact and innovations.",
                        "title": "SpaceX",
                        "assistant_response": "SpaceX changed rockets and satellite internet.",
                        "category": "science",
                        "follow_up_suggestions": [
                            "How do reusable rockets work?",
                            "What changed in launch economics?",
                            "Explain orbital launch constraints.",
                        ],
                    },
                    {
                        "wiki_title": "Antikythera_mechanism",
                        "phrase": "An ancient shipwreck held a machine. It predicted the sky.",
                        "title": "Antikythera Mechanism",
                        "assistant_response": "The Antikythera mechanism used gears to model astronomical cycles.",
                        "category": "history",
                        "follow_up_suggestions": [
                            "How did the gears work?",
                            "Who built this mechanism?",
                            "What could it predict?",
                        ],
                    },
                ]
            },
        )

    async def fake_batch_validate_topics(topics, language="en"):
        return [
            WikipediaTopic(
                topic="SpaceX",
                wiki_title="SpaceX",
                description="American spaceflight and AI company",
            ),
            WikipediaTopic(
                topic="Antikythera_mechanism",
                wiki_title="Antikythera mechanism",
                description="Ancient Greek hand-powered model of the cosmos",
            ),
        ]

    async def fake_fetch_page_summary(title, language="en"):
        summaries = {
            "SpaceX": {
                "title": "SpaceX",
                "description": "American spaceflight and AI company",
                "extract": "SpaceX is an American space technology company.",
            },
            "Antikythera_mechanism": {
                "title": "Antikythera mechanism",
                "description": "Ancient Greek hand-powered model of the cosmos",
                "extract": "The Antikythera mechanism is an ancient Greek orrery.",
            },
        }
        return summaries[title]

    monkeypatch.setattr(wiki_generator, "call_preprocessing_llm", fake_call_preprocessing_llm)
    monkeypatch.setattr(wiki_generator, "batch_validate_topics", fake_batch_validate_topics)
    monkeypatch.setattr(wiki_generator, "fetch_page_summary", fake_fetch_page_summary)

    inspirations = asyncio.run(
        wiki_generator.generate_wiki_inspirations(
            ["spaceflight engineering"],
            SimpleNamespace(),
            count=2,
            language="en",
            task_id="test_wiki_company_policy",
        )
    )

    assert [inspiration.wiki.wiki_title for inspiration in inspirations if inspiration.wiki] == [
        "Antikythera_mechanism"
    ]


def test_wiki_generator_rejects_wikidata_company_entity_type(monkeypatch) -> None:
    """Wikidata instance-of company/business types must reject neutral-looking wiki cards."""
    monkeypatch.setitem(sys.modules, "backend.apps.ai.utils.llm_utils", fake_llm_utils)
    wiki_generator = importlib.import_module("backend.apps.ai.daily_inspiration.wiki_generator")

    async def fake_call_preprocessing_llm(*_args, **_kwargs):
        return SimpleNamespace(
            error_message=None,
            arguments={
                "articles": [
                    {
                        "wiki_title": "Example_Robotics",
                        "phrase": "Reusable robots can reshape factories. What makes their design difficult?",
                        "title": "Reusable Robot Design",
                        "assistant_response": "Robotics can combine sensors, motors, and feedback loops in surprising ways.",
                        "category": "electrical_engineering",
                        "follow_up_suggestions": [
                            "How do robot sensors work?",
                            "Explain actuator feedback loops.",
                            "What makes robots reliable?",
                        ],
                    },
                    {
                        "wiki_title": "Control_theory",
                        "phrase": "Machines can correct themselves. Feedback makes that possible.",
                        "title": "Control Theory",
                        "assistant_response": "Control theory studies how systems use feedback to stay stable.",
                        "category": "electrical_engineering",
                        "follow_up_suggestions": [
                            "Explain feedback control simply.",
                            "Where is PID used?",
                            "Why do systems oscillate?",
                        ],
                    },
                ]
            },
        )

    async def fake_batch_validate_topics(topics, language="en"):
        return [
            WikipediaTopic(
                topic="Example_Robotics",
                wiki_title="Example Robotics",
                wikidata_id="QCOMPANY",
                description="Reusable robotics laboratory",
            ),
            WikipediaTopic(
                topic="Control_theory",
                wiki_title="Control theory",
                wikidata_id="QCONCEPT",
                description="Engineering and mathematical discipline",
            ),
        ]

    async def fake_fetch_page_summary(title, language="en"):
        summaries = {
            "Example_Robotics": {
                "title": "Example Robotics",
                "description": "Reusable robotics laboratory",
                "extract": "Example Robotics studies reusable robot platforms.",
            },
            "Control_theory": {
                "title": "Control theory",
                "description": "Engineering and mathematical discipline",
                "extract": "Control theory studies dynamical systems with feedback.",
            },
        }
        return summaries[title]

    async def fake_fetch_wikidata_entity(qid):
        if qid == "QCOMPANY":
            return {
                "claims": {
                    "P31": [
                        {
                            "mainsnak": {
                                "datavalue": {
                                    "value": {"id": "Q4830453"},
                                }
                            }
                        }
                    ]
                }
            }
        return {"claims": {"P31": []}}

    monkeypatch.setattr(wiki_generator, "call_preprocessing_llm", fake_call_preprocessing_llm)
    monkeypatch.setattr(wiki_generator, "batch_validate_topics", fake_batch_validate_topics)
    monkeypatch.setattr(wiki_generator, "fetch_page_summary", fake_fetch_page_summary)
    monkeypatch.setattr(wiki_generator, "fetch_wikidata_entity", fake_fetch_wikidata_entity)

    inspirations = asyncio.run(
        wiki_generator.generate_wiki_inspirations(
            ["robotics feedback control"],
            SimpleNamespace(),
            count=2,
            language="en",
            task_id="test_wikidata_company_policy",
        )
    )

    assert [inspiration.wiki.wiki_title for inspiration in inspirations if inspiration.wiki] == [
        "Control_theory"
    ]
