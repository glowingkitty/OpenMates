#!/usr/bin/env python3
"""Exercise the CSS deployment lint path with the real installed parser.

Temporary Git repositories keep fixture staging isolated from product source.
The checks distinguish valid but unformatted CSS from invalid CSS syntax.
No browser, API account, or shared runtime is used by these tooling tests.
The repository's frozen frontend dependencies provide the Prettier parser.
"""
# contract-test-file: tooling
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("source", "expected_code", "expected_output"),
    [
        (".hint{white-space:normal;overflow-wrap:anywhere}", 0, "CSS: ok style.css"),
        (".hint { color: red;", 1, "CSS: error style.css"),
    ],
)
def test_css_lint_validates_syntax_without_requiring_reformatting(
    tmp_path, source, expected_code, expected_output
):
    prettier = REPO_ROOT / "node_modules/prettier/bin/prettier.cjs"
    assert prettier.is_file(), "Install the frozen frontend dependencies before this tooling check"
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(REPO_ROOT / "scripts/lint_changed.sh", tmp_path / "scripts/lint_changed.sh")
    (tmp_path / "node_modules").symlink_to(REPO_ROOT / "node_modules", target_is_directory=True)
    (tmp_path / "package.json").write_text('{"private":true}\n')
    (tmp_path / "style.css").write_text(source)
    subprocess.run(["git", "add", "style.css"], cwd=tmp_path, check=True)

    result = subprocess.run(
        ["bash", "scripts/lint_changed.sh", "full_repo", "--css", "--path", "style.css"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )

    assert result.returncode == expected_code, result.stdout + result.stderr
    assert expected_output in result.stdout + result.stderr
