"""Ask first Project Memories use the same catalog, request and approval as personal ones.

The client catalogs its active Project's Ask first Memories as body-free rows
(source project); preprocessing selects them, the server requests
`memory:<id>`, and an approved body loads only under the active Project Focus.
"""

import pytest

from backend.apps.ai.processing.memory_document import build_memory_document
from backend.apps.ai.processing.rule_context import (
    approved_memory_definitions, catalog_discovery, requestable_catalog, split_selected_rule_snapshots,
)
from backend.shared.python_utils.memory_loader import parse_memory_catalog

STYLE = build_memory_document("Press style", "Writing press releases for this company.",
                              "Always write Example Solar.", load_mode="ask_first")
CATALOG = parse_memory_catalog([
    {"id": "item-style", "title": "Press style", "when_to_use": "Writing press releases for this company.",
     "load_mode": "ask_first", "source": "project"},
    {"id": "career-profile", "title": "Career profile", "when_to_use": "CVs.",
     "load_mode": "ask_first", "source": "personal"},
])


# contract-test: direct surface=rest_api assertions=app-memories.load-modes
def test_project_catalog_rows_are_requestable_only_under_an_active_project():
    assert [entry.id for entry in requestable_catalog(CATALOG, active_project_id=None)] == ["career-profile"]
    assert [entry.id for entry in requestable_catalog(CATALOG, active_project_id="project-1")] == [
        "item-style", "career-profile"]


# contract-test: direct surface=rest_api assertions=app-memories.load-modes
def test_project_catalog_discovery_row_carries_the_active_project_for_selection():
    project_row, personal_row = (catalog_discovery(entry, active_project_id="project-1") for entry in CATALOG)
    assert (project_row["source"], project_row["project_id"]) == ("project", "project-1")
    assert personal_row["project_id"] is None
    # Same filter the selection step applies to Project rows.
    kept = [row for row in (project_row, personal_row)
            if row["source"] == "personal" or row["project_id"] == "project-1"]
    assert [row["id"] for row in kept] == ["item-style", "career-profile"]


# contract-test: direct surface=rest_api assertions=app-memories.load-modes
def test_selected_ask_first_project_row_becomes_a_memory_request_not_a_guide():
    snapshots = [
        {"id": "item-style", "revision": None, "source": "project", "load_mode": "ask_first"},
        {"id": "item-body", "revision": "r", "source": "project", "load_mode": "auto_include"},
        {"id": "item-style", "revision": None, "source": "personal", "load_mode": "ask_first"},
    ]
    memory_keys, guides = split_selected_rule_snapshots(snapshots, CATALOG)
    assert memory_keys == ["memory:item-style"]
    assert [row["id"] for row in guides] == ["item-body"]


# contract-test: direct surface=rest_api assertions=app-memories.conversation.explicit-approval
def test_approved_project_body_loads_as_a_memory_of_the_active_project():
    memories, rest = approved_memory_definitions(
        {"memory:item-style": STYLE, "other": 1}, CATALOG,
        requested_keys=["memory:item-style"], active_project_id="project-1",
    )
    assert rest == {"other": 1}
    assert [(m.id, m.source, m.project_id) for m in memories] == [("item-style", "project", "project-1")]


# contract-test: direct surface=rest_api assertions=app-memories.conversation.explicit-approval
def test_approved_project_body_without_an_active_project_is_rejected():
    with pytest.raises(ValueError, match="not requested"):
        approved_memory_definitions({"memory:item-style": STYLE}, CATALOG,
                                    requested_keys=["memory:item-style"], active_project_id=None)


# contract-test: direct surface=rest_api assertions=app-memories.conversation.explicit-approval
def test_approved_project_body_must_match_its_catalog_metadata():
    other = build_memory_document("Other title", "Writing press releases for this company.", "x", load_mode="ask_first")
    with pytest.raises(ValueError, match="catalog metadata"):
        approved_memory_definitions({"memory:item-style": other}, CATALOG,
                                    requested_keys=["memory:item-style"], active_project_id="project-1")
