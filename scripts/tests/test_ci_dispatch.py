# contract-test-file: tooling
"""Verify test selection is bound to the published candidate.

Dirty local tests must neither enter nor alter a requested commit's inventory.
The fixture repository is disposable and does not dispatch any GitHub jobs.
Existing daily AI policy remains authoritative for scheduled selection.
See docs/plans/isolated-github-tests/plan.yml.
"""

from types import SimpleNamespace
import subprocess
import pytest
from scripts.ci_dispatch import select_specs
from test_ci_source import repository


def test_selection_reads_immutable_source(tmp_path):
    root = repository(tmp_path)
    tests = root / "frontend/apps/web_app/tests"
    tests.mkdir(parents=True)
    (tests / "present.spec.ts").write_text("// original")
    (root / "scripts").mkdir()
    (root / "scripts/daily_ai_test_manifest.json").write_text("{}")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=CI",
            "-c",
            "user.email=ci@example.com",
            "commit",
            "-m",
            "subject",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    (tests / "present.spec.ts").unlink()
    (tests / "dirty.spec.ts").write_text("// untested")
    assert select_specs(
        root, SimpleNamespace(spec=["present.spec.ts"], daily=False), source
    ) == ["present.spec.ts"]
    with pytest.raises(ValueError, match="Unknown E2E"):
        select_specs(root, SimpleNamespace(spec=["dirty.spec.ts"], daily=False), source)
