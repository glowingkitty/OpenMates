# contract-test-file: tooling
# backend/tests/test_skill_provider_attribution.py
#
# Billing provider attribution for conference sources of the events app.

from types import SimpleNamespace

from backend.shared.python_utils.skill_provider_attribution import resolve_skill_usage_provider_id


def _skill(*names):
    return SimpleNamespace(full_model_reference=None, providers=[SimpleNamespace(name=n) for n in names])


def test_events_conference_source_resolves_to_pretalx():
    assert resolve_skill_usage_provider_id("events", "search", _skill("GPN24", "39C3")) == "pretalx"


def test_other_skill_keeps_first_declared_provider():
    assert resolve_skill_usage_provider_id("news", "search", _skill("brave")) == "brave"
