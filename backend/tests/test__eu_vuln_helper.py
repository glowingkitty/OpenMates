"""Test complete dependency discovery for vulnerability scanning.

The supplementary OSV scanner must discover manifests instead of maintaining a
small hand-written list. Distinct installed-version candidates remain separate
because one safe runtime must not hide another vulnerable runtime.
"""

from pathlib import Path

from scripts import _eu_vuln_helper as inventory


ROOT = Path(__file__).resolve().parents[2]


# contract-test: infrastructure
def test_discovers_nested_npm_and_python_manifests(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"dependencies":{"root":"1.0.0"}}')
    nested = tmp_path / "backend" / "worker"
    nested.mkdir(parents=True)
    (nested / "package.json").write_text('{"dependencies":{"nested":"2.0.0"}}')
    (nested / "requirements.txt").write_text("httpx==0.28.1\n")
    (nested / "requirements-dev.txt").write_text("pytest==9.0.0\n")

    discovered = inventory._discover_dependency_files(str(tmp_path))

    assert discovered == {
        "npm": ["backend/worker/package.json", "package.json"],
        "PyPI": [
            "backend/worker/requirements-dev.txt",
            "backend/worker/requirements.txt",
        ],
    }


# contract-test: infrastructure
def test_ignores_dependency_caches(tmp_path: Path) -> None:
    cache = tmp_path / "node_modules" / "untrusted"
    cache.mkdir(parents=True)
    (cache / "package.json").write_text('{"dependencies":{"ignored":"1.0.0"}}')

    assert inventory._discover_dependency_files(str(tmp_path)) == {"npm": [], "PyPI": []}


# contract-test: infrastructure
def test_preserves_distinct_versions_of_the_same_package(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "requirements.txt").write_text("example==1.0.0\n")
    (second / "requirements.txt").write_text("example==2.0.0\n")

    dependencies = inventory._collect_all_dependencies(str(tmp_path))

    assert {(item["name"], item["version"]) for item in dependencies} == {
        ("example", "1.0.0"),
        ("example", "2.0.0"),
    }


# contract-test: infrastructure
def test_collects_transitive_versions_from_pnpm_lockfile(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"dependencies":{"direct":"1.0.0"}}')
    (tmp_path / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '9.0'\n\npackages:\n\n  transitive@4.2.0:\n    resolution: {}\n\nsnapshots:\n",
        encoding="utf-8",
    )

    dependencies = inventory._collect_all_dependencies(str(tmp_path))

    assert {
        (item["name"], item["version"], item["source_file"]) for item in dependencies
    } >= {("transitive", "4.2.0", "pnpm-lock.yaml")}


# contract-test: infrastructure
def test_dry_run_does_not_persist_eu_vulnerability_tracking(
    tmp_path: Path, monkeypatch
) -> None:
    tracking = tmp_path / "eu-vuln-processed.json"
    tracking.write_text('{"last_run":"before","processed":[]}\n', encoding="utf-8")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("{{DATE}}\n{{ALERT_SUMMARY}}", encoding="utf-8")
    dependency = {
        "name": "example",
        "version": "1.0.0",
        "ecosystem": "npm",
        "source_file": "package.json",
    }
    vulnerability = {
        "id": "GHSA-test-test-test",
        "database_specific": {"severity": "high"},
        "summary": "Test vulnerability",
    }
    monkeypatch.setenv("TRACKING_FILE_PATH", str(tracking))
    monkeypatch.setenv("DEPENDABOT_TRACKING_PATH", str(tmp_path / "dependabot.json"))
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("SUMMARY_ONLY", "false")
    monkeypatch.setenv("PROMPT_TEMPLATE_PATH", str(prompt))
    monkeypatch.setattr(inventory, "_collect_all_dependencies", lambda _: [dependency])
    monkeypatch.setattr(inventory, "_query_osv_batch", lambda _: [(dependency, [vulnerability])])
    monkeypatch.setattr(inventory, "_check_vuln_in_git", lambda *_: None)
    tracking_before = tracking.read_bytes()

    inventory.check_vulns()

    assert tracking.read_bytes() == tracking_before


# contract-test: infrastructure
def test_summary_clean_scan_does_not_persist_eu_vulnerability_tracking(
    tmp_path: Path, monkeypatch
) -> None:
    tracking = tmp_path / "eu-vuln-processed.json"
    tracking.write_text('{"last_run":"before","processed":[]}\n', encoding="utf-8")
    dependency = {
        "name": "example",
        "version": "1.0.0",
        "ecosystem": "npm",
        "source_file": "package.json",
    }
    monkeypatch.setenv("TRACKING_FILE_PATH", str(tracking))
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("SUMMARY_ONLY", "true")
    monkeypatch.setattr(inventory, "_collect_all_dependencies", lambda _: [dependency])
    monkeypatch.setattr(inventory, "_query_osv_batch", lambda _: [])
    tracking_before = tracking.read_bytes()

    inventory.check_vulns()

    assert tracking.read_bytes() == tracking_before


# contract-test: infrastructure
def test_hosted_scan_resolves_every_requirements_graph() -> None:
    workflow = (ROOT / ".github" / "workflows" / "dependency-security.yml").read_text()

    assert "git ls-files -z '*requirements*.txt'" in workflow
    assert "pip-audit==2.10.1" in workflow
    assert "python -m pip_audit" in workflow
    assert "pnpm install --frozen-lockfile" in workflow
    assert "pnpm audit --audit-level high" in workflow
