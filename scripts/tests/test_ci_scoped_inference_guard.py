import importlib.util
from pathlib import Path
import subprocess

import pytest


path = Path(__file__).parents[1] / "ci_scoped_inference_guard.py"
spec = importlib.util.spec_from_file_location("ci_scoped_guard", path)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


# contract-test: supporting surface=cli assertions=daily-ai-tests.real.semantic-signal
def test_exact_approved_source_on_dev_is_required():
    source = "a" * 40
    guard.authorize(source, f'["{source}"]', "refs/heads/dev", "b" * 40)
    for approved, ref in [
        ("[]", "refs/heads/dev"), ('["a"]', "refs/heads/dev"),
        (f'["{source}"]', "refs/tags/dev"), (f'["{source}garbage"]', "refs/heads/dev"),
    ]:
        with pytest.raises(ValueError):
            guard.authorize(source, approved, ref, "b" * 40)


# contract-test: supporting surface=cli assertions=daily-ai-tests.real.semantic-signal
def test_current_protected_dev_commit_is_eligible_without_candidate_registration():
    source = "a" * 40
    guard.authorize(source, "[]", "refs/heads/dev", source)
    with pytest.raises(ValueError):
        guard.authorize(source, "[]", "refs/heads/feature", source)
    with pytest.raises(ValueError):
        guard.authorize(source, "[]", "refs/heads/dev", "b" * 40)


# contract-test: supporting surface=cli assertions=daily-ai-tests.real.semantic-signal
def test_tooling_reads_only_committed_bytes_and_excludes_python_shadows(tmp_path):
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    real = scripts / "ci_environment.py"
    real.write_text("ORIGIN = 'reviewed'\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "scripts"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=CI", "-c", "user.email=ci@localhost",
                    "commit", "-qm", "Fixture"], check=True)
    head = guard.git(repo, "rev-parse", "HEAD").decode().strip()
    real.write_text("ORIGIN = 'local'\n")
    (scripts / "json.py").write_text("# Local shadow must never enter the seed process.\n")
    cache = scripts / "__pycache__"
    cache.mkdir()
    (cache / "ci_environment.pyc").write_bytes(b"fixture")
    fresh = guard.materialize(repo, head, tmp_path)
    assert (fresh / "scripts/ci_environment.py").read_text() == "ORIGIN = 'reviewed'\n"
    assert not (fresh / "scripts/json.py").exists() and not (fresh / "scripts/__pycache__").exists()
    assert fresh.stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError):
        guard.materialize(repo, "f" * 40, tmp_path)
