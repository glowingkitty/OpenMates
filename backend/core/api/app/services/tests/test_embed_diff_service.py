"""
Tests for embed_diff_service — validates diff parsing and patch application.

Tests the 3-tier fallback strategy:
- Tier 1: Exact patch application
- Tier 2: Fuzzy patch (±3 line offset tolerance)
- Tier 3: Graceful failure (returns visual fallback)
"""

import pytest

from backend.core.api.app.services.embed_diff_service import (
    DiffHunk,
    ParsedDiff,
    apply_patch,
    apply_patch_exact,
    apply_patch_fuzzy,
    is_diff_fence_open,
    parse_unified_diff,
)
from backend.apps.ai.tasks.stream_consumer import (
    _parse_email_fence_content,
    _reconstruct_mail_fence,
)


# ─── Fixtures ────────────────────────────────────────────────────────

SAMPLE_CODE = """import pandas as pd


def process_csv(
    filepath: str,
    sort_column: str,
    ascending: bool = False,
    top_n: int = 5
) -> pd.DataFrame:
    df = pd.read_csv(filepath)
    df_sorted = df.sort_values(by=sort_column, ascending=ascending)
    return df_sorted.head(top_n)


# Example usage:
# result = process_csv('sales_data.csv', 'revenue')
# print(result)""".strip()

RENAME_DIFF = """@@ -3,8 +3,8 @@

-def process_csv(
+def parse_csv(
     filepath: str,
     sort_column: str,
     ascending: bool = False,
     top_n: int = 5
@@ -15,3 +15,3 @@
 # Example usage:
-# result = process_csv('sales_data.csv', 'revenue')
+# result = parse_csv('sales_data.csv', 'revenue')
 # print(result)"""

SAMPLE_TABLE = """|Name|Age|City|
|---|---|---|
|Alice|30|NYC|
|Bob|25|LA|
|Charlie|35|SF|"""

ADD_ROW_DIFF = """@@ -4,2 +4,3 @@
 |Bob|25|LA|
 |Charlie|35|SF|
+|Diana|28|CHI|"""


# ─── Diff Parsing Tests ──────────────────────────────────────────────

class TestParsing:
    def test_parse_single_hunk(self):
        diff = parse_unified_diff(RENAME_DIFF, "utils.py-k8D")
        assert diff.embed_ref == "utils.py-k8D"
        assert len(diff.hunks) == 2

    def test_parse_hunk_header(self):
        diff = parse_unified_diff(RENAME_DIFF, "test")
        h = diff.hunks[0]
        assert h.old_start == 3
        assert h.old_count == 8
        assert h.new_start == 3
        assert h.new_count == 8

    def test_parse_add_row(self):
        diff = parse_unified_diff(ADD_ROW_DIFF, "table-x4F")
        assert len(diff.hunks) == 1
        hunk = diff.hunks[0]
        # Should have 2 context + 1 add = 3 lines
        assert len(hunk.lines) == 3

    def test_is_diff_fence_open(self):
        assert is_diff_fence_open("```diff:process_data.py-k8D") == "process_data.py-k8D"
        assert is_diff_fence_open("```diff:report.html-x4F") == "report.html-x4F"
        assert is_diff_fence_open("```python") is None
        assert is_diff_fence_open("```diff") is None  # no embed_ref after colon
        assert is_diff_fence_open("```") is None


# ─── Tier 1: Exact Patch ─────────────────────────────────────────────

class TestExactPatch:
    def test_rename_function(self):
        result = apply_patch_exact(SAMPLE_CODE, parse_unified_diff(RENAME_DIFF, "test"))
        assert result.success
        assert "def parse_csv(" in result.new_content
        assert "def process_csv(" not in result.new_content
        assert "result = parse_csv(" in result.new_content

    def test_add_table_row(self):
        result = apply_patch_exact(SAMPLE_TABLE, parse_unified_diff(ADD_ROW_DIFF, "test"))
        assert result.success
        assert "|Diana|28|CHI|" in result.new_content
        assert result.new_content.count("\n") == SAMPLE_TABLE.count("\n") + 1

    def test_mismatch_fails(self):
        wrong_code = SAMPLE_CODE.replace("process_csv", "wrong_name")
        result = apply_patch_exact(wrong_code, parse_unified_diff(RENAME_DIFF, "test"))
        assert not result.success
        assert result.tier == 1
        assert "Context mismatch" in result.error


# ─── Tier 2: Fuzzy Patch ─────────────────────────────────────────────

class TestFuzzyPatch:
    def test_offset_by_1_line(self):
        # Add a blank line at the top, shifting everything down by 1
        shifted_code = "\n" + SAMPLE_CODE
        result = apply_patch_fuzzy(shifted_code, parse_unified_diff(RENAME_DIFF, "test"))
        assert result.success
        assert "def parse_csv(" in result.new_content

    def test_offset_by_3_lines(self):
        # Add 3 blank lines at the top
        shifted_code = "\n\n\n" + SAMPLE_CODE
        result = apply_patch_fuzzy(shifted_code, parse_unified_diff(RENAME_DIFF, "test"))
        assert result.success
        assert "def parse_csv(" in result.new_content

    def test_offset_beyond_tolerance_fails(self):
        # Add 5 blank lines — beyond ±3 tolerance
        shifted_code = "\n\n\n\n\n" + SAMPLE_CODE
        result = apply_patch_fuzzy(shifted_code, parse_unified_diff(RENAME_DIFF, "test"), max_offset=3)
        assert not result.success


# ─── Tier 3: Full Pipeline ───────────────────────────────────────────

class TestFullPipeline:
    def test_exact_success(self):
        result = apply_patch(SAMPLE_CODE, parse_unified_diff(RENAME_DIFF, "test"))
        assert result.success
        assert result.tier == 1

    def test_fuzzy_fallback(self):
        shifted_code = "\n\n" + SAMPLE_CODE
        result = apply_patch(shifted_code, parse_unified_diff(RENAME_DIFF, "test"))
        assert result.success
        assert result.tier == 2

    def test_total_failure_tier3(self):
        garbage = "completely different content\nnothing matches"
        result = apply_patch(garbage, parse_unified_diff(RENAME_DIFF, "test"))
        assert not result.success
        assert result.tier == 3

    def test_empty_hunks(self):
        empty_diff = parse_unified_diff("", "test")
        result = apply_patch(SAMPLE_CODE, empty_diff)
        assert not result.success
        assert result.tier == 3


# ─── Document (HTML) Diff ────────────────────────────────────────────

class TestDocumentDiff:
    def test_html_title_change(self):
        html = """<!-- title: "My Report" -->
<h1>My Report</h1>
<p>Introduction paragraph.</p>
<p>Second paragraph.</p>"""

        diff_text = """@@ -1,4 +1,4 @@
-<!-- title: "My Report" -->
-<h1>My Report</h1>
+<!-- title: "Updated Report" -->
+<h1>Updated Report</h1>
 <p>Introduction paragraph.</p>
 <p>Second paragraph.</p>"""

        result = apply_patch(html, parse_unified_diff(diff_text, "report-x4F"))
        assert result.success
        assert "Updated Report" in result.new_content
        assert "My Report" not in result.new_content


# ─── Mail Diff ───────────────────────────────────────────────────────

class TestMailDiff:
    """Tests for mail embed diff editing via reconstruct → patch → re-parse."""

    def test_change_subject(self):
        """Change only the subject line of a mail embed."""
        mail_fence = """to: john@example.com
subject: Meeting tomorrow at 3pm
content:
Hi John,

I wanted to confirm our meeting tomorrow.
Please bring the Q2 report.

footer:
Best regards,
Alice"""

        diff_text = """@@ -1,3 +1,3 @@
 to: john@example.com
-subject: Meeting tomorrow at 3pm
+subject: Meeting rescheduled to 4pm
 content:"""

        result = apply_patch(mail_fence, parse_unified_diff(diff_text, "email-k8D"))
        assert result.success
        assert "subject: Meeting rescheduled to 4pm" in result.new_content
        assert "subject: Meeting tomorrow at 3pm" not in result.new_content
        # Other fields preserved
        assert "to: john@example.com" in result.new_content
        assert "Best regards," in result.new_content

    def test_change_receiver(self):
        """Change the recipient of a mail."""
        mail_fence = """to: john@example.com
subject: Project update
content:
Here is the latest update."""

        diff_text = """@@ -1,2 +1,2 @@
-to: john@example.com
+to: jane@example.com
 subject: Project update"""

        result = apply_patch(mail_fence, parse_unified_diff(diff_text, "email-x4F"))
        assert result.success
        assert "to: jane@example.com" in result.new_content

    def test_modify_body_content(self):
        """Modify a line in the body content."""
        mail_fence = """to: team@company.com
subject: Sprint review
content:
Hi team,

The sprint review is scheduled for Friday.
Please prepare your demos.

footer:
Thanks,
PM"""

        diff_text = """@@ -5,3 +5,3 @@

-The sprint review is scheduled for Friday.
+The sprint review has been moved to Monday.
 Please prepare your demos."""

        result = apply_patch(mail_fence, parse_unified_diff(diff_text, "sprint-email-k8D"))
        assert result.success
        assert "moved to Monday" in result.new_content
        assert "scheduled for Friday" not in result.new_content
        # Rest preserved
        assert "team@company.com" in result.new_content
        assert "Thanks," in result.new_content

    def test_add_footer(self):
        """Add a footer to a mail that didn't have one."""
        mail_fence = """to: client@example.com
subject: Invoice attached
content:
Please find the invoice attached.
Let me know if you have questions."""

        diff_text = """@@ -4,2 +4,5 @@
 Please find the invoice attached.
 Let me know if you have questions.
+
+footer:
+Best regards,
+Finance Team"""

        result = apply_patch(mail_fence, parse_unified_diff(diff_text, "invoice-email-x4F"))
        assert result.success
        assert "footer:" in result.new_content
        assert "Finance Team" in result.new_content

    def test_roundtrip_reconstruct_patch_reparse(self):
        """Full roundtrip: reconstruct fence → apply diff → re-parse into fields."""
        # Simulate what stream_consumer does: reconstruct from stored fields
        original_fence = _reconstruct_mail_fence(
            receiver="alice@company.com",
            subject="Q2 Report",
            content="Hi Alice,\n\nPlease review the attached Q2 report.",
            footer="Thanks,\nBob"
        )

        # Verify reconstruction
        assert "to: alice@company.com" in original_fence
        assert "subject: Q2 Report" in original_fence
        assert "Please review" in original_fence
        assert "Thanks," in original_fence

        # Apply a diff (change subject)
        diff_text = """@@ -1,3 +1,3 @@
 to: alice@company.com
-subject: Q2 Report
+subject: Q2 Report — URGENT
 content:"""

        result = apply_patch(original_fence, parse_unified_diff(diff_text, "report-email"))
        assert result.success

        # Re-parse the patched content back into fields
        parsed = _parse_email_fence_content(result.new_content)
        assert parsed["receiver"] == "alice@company.com"
        assert parsed["subject"] == "Q2 Report — URGENT"
        assert "Please review" in parsed["content"]
        assert "Thanks," in parsed["footer"]
