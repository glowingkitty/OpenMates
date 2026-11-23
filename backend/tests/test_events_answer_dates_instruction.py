"""The events app asks the model to state dates, and never hides date fields from it."""
from pathlib import Path

import yaml

from backend.apps.events.skills.search_skill import SearchResponse

_APP = Path(__file__).resolve().parents[1] / "apps" / "events" / "app.yml"


# contract-test: direct surface=rest_api assertions=events-search.answer.states-dates
def test_events_instruction_requires_dates_for_search_skill():
    instructions = yaml.safe_load(_APP.read_text())["instructions"]
    search = [item for item in instructions if item.get("for_skills") == ["search"]]
    assert len(search) == 1
    text = search[0]["instruction"]
    for field in ("date_start", "date_end", "venue"):
        assert field in text


# contract-test: direct surface=rest_api assertions=events-search.answer.states-dates
def test_date_and_venue_fields_reach_the_model():
    hidden = set(SearchResponse.model_fields["ignore_fields_for_inference"].default_factory())
    assert not hidden & {"title", "date_start", "date_end", "venue", "url"}
