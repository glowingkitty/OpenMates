"""Task fence validation: pure parsing of assistant-authored openmates_task blocks."""

import json

from backend.apps.ai.utils.json_content_fences import json_content_embed_type
from backend.apps.ai.utils.task_fences import (
    TaskFenceContext,
    is_task_fence,
    task_validation_feedback,
    validate_task_fence,
)

PERSONAL = TaskFenceContext(known_projects={"kitchen renovation": "project-1", "kit-ab": "project-1"})
TEAM = TaskFenceContext(is_team=True, known_assignees={"ada": "member-1"})


def check(payload, ctx=PERSONAL, **kwargs):
    source = payload if isinstance(payload, str) else json.dumps(payload)
    return validate_task_fence(source, context=ctx, **kwargs)


def codes(result):
    return [error["code"] for error in result.errors]


# contract-test: direct surface=rest_api assertions=task-inline.create.fence-not-tool
def test_fence_languages_and_embed_type():
    assert is_task_fence("openmates_task") and is_task_fence(" OMTASK ")
    assert not is_task_fence("python") and not is_task_fence(None)
    assert json_content_embed_type("omtask") == "task"


# contract-test: direct surface=rest_api assertions=task-inline.create.fence-not-tool
def test_valid_create_with_defaults():
    result = check({"title": "  Call the plumber "})
    assert result.status == "valid" and result.title == "Call the plumber"
    assert result.model["status"] == "todo"
    assert result.model["assignee_type"] == "user"
    assert result.model["due_at"] is None and result.model["project_id"] is None


# contract-test: direct surface=rest_api assertions=task-inline.create.fence-not-tool
def test_full_task_with_date_assignee_and_project():
    result = check({"title": "Pause", "description": "d", "due_date": "2026-11-24", "status": "blocked",
                    "assignee": "OpenMates", "project": "Kitchen Renovation"})
    assert result.status == "valid"
    assert result.model["due_at"] == 1795478400
    assert result.model["due_date"] == "2026-11-24"
    assert result.model["assignee_type"] == "openmates"
    assert result.model["project_id"] == "project-1"
    assert check({"title": "x", "project": "KIT-AB"}).status == "valid"
    assert check({"title": "x", "assignee": "me"}).model["assignee_type"] == "user"


# contract-test: direct surface=rest_api assertions=task-inline.validation.visible-and-fed-back
def test_timestamp_with_offset_is_accepted():
    result = check({"title": "x", "due_date": "2026-11-24T10:00:00+01:00"})
    assert result.status == "valid" and result.model["due_at"] == 1795510800


# contract-test: direct surface=rest_api assertions=task-inline.validation.visible-and-fed-back
def test_error_codes():
    assert codes(check({"title": " "})) == ["missing_title"]
    assert codes(check({})) == ["missing_title"]
    assert codes(check({"title": "x" * 201})) == ["title_too_long"]
    assert codes(check({"title": "x", "status": "later"})) == ["invalid_status"]
    assert codes(check({"title": "x", "due_date": "2026-02-30"})) == ["invalid_due_date"]
    assert codes(check({"title": "x", "due_date": "2026-11-24T10:00:00"})) == ["invalid_due_date"]
    assert codes(check({"title": "x", "assignee": "ada"})) == ["unknown_assignee"]
    assert codes(check({"title": "x", "project": "Garden shed"})) == ["unknown_project"]
    assert codes(check("not json")) == ["invalid_json"]
    assert codes(check("[1]")) == ["invalid_json"]


# contract-test: direct surface=rest_api assertions=task-inline.validation.visible-and-fed-back
def test_messages_are_plain_english_and_feedback_lists_each():
    result = check({"title": "x", "project": "Garden shed", "status": "later"})
    assert result.status == "invalid" and result.model is None
    assert 'The Project "Garden shed" was not found.' in task_validation_feedback(result.errors)
    assert len(task_validation_feedback(result.errors).splitlines()) == 2


# contract-test: direct surface=rest_api assertions=task-inline.validation.visible-and-fed-back
def test_team_assignee_rules():
    ok = check({"title": "x", "assignee": "Ada"}, TEAM)
    assert ok.status == "valid"
    assert (ok.model["assignee_type"], ok.model["assignee_id"]) == ("member", "member-1")
    assert check({"title": "x", "assignee": "openmates"}, TEAM).status == "valid"
    assert codes(check({"title": "x", "assignee": "bob"}, TEAM)) == ["unknown_assignee"]
    assert check({"title": "x"}, TEAM).model["assignee_type"] == "user"


# contract-test: direct surface=rest_api assertions=task-inline.edit.diff-versioned
def test_done_only_in_edits():
    assert codes(check({"title": "x", "status": "done"})) == ["invalid_status"]
    assert check({"title": "x", "status": "done"}, allow_done=True).status == "valid"


# contract-test: direct surface=rest_api assertions=task-inline.validation.visible-and-fed-back
def test_unknown_fields_warn_and_are_dropped():
    result = check({"title": "x", "priority": "high"})
    assert result.status == "valid"
    assert [w["field"] for w in result.warnings] == ["priority"]
    assert "priority" not in result.source_json


# contract-test: direct surface=rest_api assertions=task-inline.edit.diff-versioned
def test_source_json_is_canonical_and_stable():
    a = check({"assignee": "user", "title": "x", "due_date": "2026-11-24", "description": "d"})
    b = check(a.source_json)
    assert a.source_json == b.source_json
    assert list(json.loads(a.source_json)) == ["title", "description", "status", "due_date", "assignee"]
    assert '\n  "title"' in a.source_json


# contract-test: direct surface=rest_api assertions=task-inline.create.fence-not-tool
def test_plan_reference_links_the_task_to_a_plan():
    result = check({"title": "Build the importer", "assignee": "openmates", "plan": "plan-1"})
    assert result.status == "valid" and result.model["plan_id"] == "plan-1"
    assert json.loads(result.source_json)["plan"] == "plan-1"
    assert codes(check({"title": "Build the importer", "plan": "  "})) == ["invalid_plan"]
