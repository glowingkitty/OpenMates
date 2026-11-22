"""The focus activation card names a Project's own Focus by its title, not its raw id."""
from types import SimpleNamespace

from backend.apps.ai.processing.main_processor import _project_focus_card_identity

FOCUS_ID = "project-focus:project-1:item-1"


# contract-test: supporting surface=gui.web assertions=focus-modes.project-layering
def test_project_focus_card_uses_the_catalog_title_and_projects_app() -> None:
    request = SimpleNamespace(project_focus_catalog=[
        {"kind": "focus", "id": "other", "title": "Write release notes"},
        {"kind": "focus", "id": "item-1", "title": "Add a new provider", "revision": "r1"},
    ])
    assert _project_focus_card_identity(request, FOCUS_ID) == ("Add a new provider", "projects")


# contract-test: supporting surface=gui.web assertions=focus-modes.project-layering
def test_other_focus_ids_and_missing_titles_keep_the_existing_naming() -> None:
    request = SimpleNamespace(project_focus_catalog=[{"id": "item-1", "title": "  "}])
    assert _project_focus_card_identity(request, "plans-write_specification") is None
    assert _project_focus_card_identity(request, FOCUS_ID) is None
    assert _project_focus_card_identity(SimpleNamespace(), FOCUS_ID) is None
