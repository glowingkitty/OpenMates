# backend/tests/test_daily_inspiration_content_policy.py
#
# Unit tests for the shared Daily Inspiration content policy.
# The policy is stricter than regular chat because inspirations are proactive
# recommendations; they must not accidentally promote commercial entities.
#
# Run: python -m pytest backend/tests/test_daily_inspiration_content_policy.py -v

from backend.apps.ai.daily_inspiration.content_filter import check_daily_inspiration_entry


def test_policy_rejects_named_company_as_inspiration_subject() -> None:
    result = check_daily_inspiration_entry(
        {
            "content_type": "wiki",
            "title": "SpaceX",
            "phrase": "How has SpaceX revolutionized technology? Explore its innovations.",
            "assistant_response": "SpaceX changed launch economics and satellite internet.",
            "category": "science",
            "wiki_metadata": {
                "title": "SpaceX",
                "description": "American spaceflight organization",
            },
        }
    )

    assert result["verdict"] == "REJECT"
    assert "company_names" in result["violations"]


def test_policy_rejects_company_profile_language_without_known_name() -> None:
    result = check_daily_inspiration_entry(
        {
            "content_type": "wiki",
            "title": "Reusable Launch Startup",
            "phrase": "A rocket startup made launches cheaper. How did it happen?",
            "assistant_response": "This company changed how engineers approach reusable launches.",
            "category": "science",
        }
    )

    assert result["verdict"] == "REJECT"
    assert result["violations"]["company_subject"] == ["company_profile_marker"]


def test_policy_rejects_wikidata_company_entity_type() -> None:
    result = check_daily_inspiration_entry(
        {
            "content_type": "wiki",
            "title": "Reusable Robotics",
            "phrase": "Reusable robots can self-correct. Feedback makes that possible.",
            "assistant_response": "Robotics combines sensors, actuators, and control loops.",
            "category": "electrical_engineering",
        },
        wikidata_entity={
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
        },
    )

    assert result["verdict"] == "REJECT"
    assert result["violations"]["wikidata_company_type"] == ["Q4830453"]


def test_policy_allows_reframed_noncommercial_concept() -> None:
    result = check_daily_inspiration_entry(
        {
            "content_type": "wiki",
            "title": "Reusable Rocket Engineering",
            "phrase": "Rockets can fly more than once. The engineering tradeoffs are fascinating.",
            "assistant_response": "Reusable launch systems involve heat shields, propellant margins, and control loops.",
            "category": "science",
            "wiki_metadata": {
                "title": "Reusable launch system",
                "description": "Launch system concept",
            },
        },
        wikidata_entity={"claims": {"P31": []}},
    )

    assert result["verdict"] == "PASS"


def test_policy_allows_first_party_feature_cards() -> None:
    result = check_daily_inspiration_entry(
        {
            "content_type": "feature",
            "title": "Privacy controls",
            "phrase": "OpenMates gives you privacy controls worth reviewing before you need them.",
            "assistant_response": "Tune encryption, personal-data hiding, and privacy preferences in one place.",
            "category": "openmates_official",
            "feature_metadata": {
                "feature_id": "privacy-dashboard",
                "title": "Privacy controls",
            },
        }
    )

    assert result["verdict"] == "PASS"
