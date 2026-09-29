# contract-test-file: tooling
"""The daily CI email accepts a bounded, escaped report payload."""

from pathlib import Path

from backend.core.api.app.tasks.email_tasks.test_run_summary_email_task import _sanitize_daily_digest


def test_daily_digest_escapes_text_and_rejects_untrusted_links() -> None:
    data = _sanitize_daily_digest({
        "date": "2026-09-28", "status": "BLOCKED<script>", "source": "abcd",
        "rows": [{"name": "Web <E2E>", "detail": "No run", "executed": 0,
                  "passed": 0, "failed": 0, "skipped": 0}],
        "signup": "<bad>", "highlights": ["Unclassified <spec>"],
        "report_url": "https://evil.example/v1/status/tests/daily/2026-09-28",
    })
    assert data["status"] == "BLOCKED&lt;script&gt;"
    assert data["rows"][0]["name"] == "Web &lt;E2E&gt;"
    assert data["report_url"] == ""
    template = (Path(__file__).resolve().parents[2] / "backend/core/api/templates/email/daily_ci_digest.mjml").read_text()
    assert "{% for row in daily_digest.rows %}" in template
