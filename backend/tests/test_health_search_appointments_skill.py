"""Unit tests for the health appointment search skill.

These tests cover deterministic quality filters and provider-normalization
contracts without live Doctolib or Jameda calls. The live provider APIs are
covered separately by CLI/API smoke tests; this file guards local filtering
logic that should never regress because of German city spelling variants.
"""

from __future__ import annotations

from backend.apps.health.skills.search_appointments_skill import _cities_match


def test_jameda_city_matching_accepts_umlaut_city_names() -> None:
    """Jameda returns display cities while requests use URL slug city names."""

    assert _cities_match("Köln", "koeln") is True
    assert _cities_match("München", "muenchen") is True
    assert _cities_match("Düsseldorf", "duesseldorf") is True
    assert _cities_match("Nürnberg", "nuernberg") is True


def test_jameda_city_matching_rejects_different_cities() -> None:
    assert _cities_match("Berlin", "hamburg") is False
    assert _cities_match("Köln", "bonn") is False
    assert _cities_match("", "koeln") is False
