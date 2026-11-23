"""Issue A5455: a report longer than the title column keeps its full text."""

from backend.core.api.app.services.issue_report_storage import (
    ISSUE_REPORT_DB_TITLE_MAX_CHARS,
    fit_issue_text_for_storage,
)


# contract-test: supporting surface=rest_api assertions=issue-reporting.input.long-title-preserved
def test_short_title_is_stored_unchanged() -> None:
    assert fit_issue_text_for_storage("Login fails", None) == ("Login fails", None, False)
    assert fit_issue_text_for_storage("Login fails", "details") == ("Login fails", "details", False)


# contract-test: supporting surface=rest_api assertions=issue-reporting.input.long-title-preserved
def test_long_title_keeps_its_full_text_in_the_description() -> None:
    title = "Multiple issues. " + "The recording stopped and the text vanished. " * 20
    db_title, db_description, truncated = fit_issue_text_for_storage(title, None)
    assert truncated
    assert db_title == title[:ISSUE_REPORT_DB_TITLE_MAX_CHARS]
    assert db_description == title


# contract-test: supporting surface=rest_api assertions=issue-reporting.input.long-title-preserved
def test_long_title_is_placed_before_an_existing_description() -> None:
    title = "x" * (ISSUE_REPORT_DB_TITLE_MAX_CHARS + 1)
    _, db_description, _ = fit_issue_text_for_storage(title, "client description")
    assert db_description == f"{title}\n\nclient description"
