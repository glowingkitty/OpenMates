# backend/tests/test_accessibility_audit.py
#
# Unit coverage for the deterministic accessibility audit helper script.
# These tests keep the host-safe static checks stable without launching the
# web app, Playwright, Xcode, or external services.
# Architecture context: scripts/accessibility_audit.py

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import accessibility_audit  # noqa: E402


def test_contrast_check_ignores_dark_theme_overrides(tmp_path, monkeypatch) -> None:
    """The light-background contrast check must not flag dark-theme overrides."""

    token_file = tmp_path / "theme.generated.css"
    token_file.write_text(
        "\n".join(
            [
                ":root {",
                "  --color-font-secondary: #a9a9a9;",
                "  --color-font-tertiary: #6b6b6b;",
                "}",
                "/* Dark theme overrides */",
                "[data-theme=\"dark\"] {",
                "  --color-font-primary: #e6e6e6;",
                "  --color-font-secondary: #cfcfcf;",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(accessibility_audit, "THEME_TOKENS", token_file)

    findings = accessibility_audit.check_web_contrast_tokens()

    assert len(findings) == 1
    assert findings[0].line == 2
    assert findings[0].id == "web.contrast.font-token"


def test_markdown_report_groups_representative_findings() -> None:
    """Markdown output should summarize repeated rules before examples."""

    sample = accessibility_audit.finding(
        id="web.example",
        area="web",
        category="example",
        severity="high",
        title="Example finding",
        description="Example description",
        path=REPO_ROOT / "scripts" / "accessibility_audit.py",
        line=1,
        snippet="example",
        recommendation="Fix example",
    )
    report = {
        "generated_at": "2026-06-04T00:00:00+00:00",
        "summary": {
            "total_findings": 1,
            "counts_by_severity": {"critical": 0, "high": 1, "medium": 0, "low": 0, "info": 0},
            "counts_by_area": {"web": 1},
            "counts_by_category": {"example": 1},
            "counts_by_rule": [
                {
                    "id": sample.id,
                    "area": sample.area,
                    "category": sample.category,
                    "severity": sample.severity,
                    "title": sample.title,
                    "count": 1,
                    "example": f"{sample.path}:{sample.line}",
                }
            ],
        },
        "findings": [accessibility_audit.asdict(sample)],
    }

    markdown = accessibility_audit.format_markdown(report)

    assert "## Top Rule Groups" in markdown
    assert "`web.example`" in markdown
    assert "## Top Finding Examples" in markdown
