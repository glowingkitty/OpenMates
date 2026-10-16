# contract-test-file: infrastructure
"""Capacity dispatch preserves exact calibration and the isolated runner gate."""
import io
import json
import urllib.request
import zipfile

import pytest

from scripts.ci_capacity_config import (
    ArtifactRedirect, CALIBRATION_FILES, CALIBRATION_SPEC, TARGET_SPEC,
    calibration_bytes, configuration_for_submission, validate_configuration,
)
from scripts.ci_coordinator import GitHub, Queue, enqueue_submission
from scripts import ci_environment, ci_results


def config(**changed):
    return dict(source="a" * 40, profile="accelerated", duration_seconds=900,
                timeout_seconds=10000, calibration_run_id=7) | changed


def test_target_configuration_binds_successful_same_source_calibration(tmp_path):
    queue = Queue(tmp_path / "queue.db")
    pilot = queue.enqueue("owner", "a" * 40, [CALIBRATION_SPEC])
    options = dict(source="a" * 40, specs=[TARGET_SPEC], mode="e2e",
                   calibration_job=pilot["id"], profile="accelerated",
                   duration_seconds=900, timeout_seconds=10000)
    with pytest.raises(ValueError, match="successful same-source"):
        configuration_for_submission(queue, **options)
    with queue.connect() as database:
        database.execute("UPDATE jobs SET state='success',run_id=7 WHERE id=?", (pilot["id"],))
    assert configuration_for_submission(queue, **options) == config()
    with pytest.raises(ValueError, match="same-source"):
        configuration_for_submission(queue, **(options | {"source": "b" * 40}))
    with pytest.raises(ValueError, match="one dedicated"):
        configuration_for_submission(queue, **(options | {"specs": [TARGET_SPEC, "tasks-flow.spec.ts"]}))


def test_configuration_is_persisted_dispatched_and_part_of_queue_identity(tmp_path):
    queue = Queue(tmp_path / "queue.db")
    with pytest.raises(ValueError, match="calibration configuration"):
        queue.enqueue("owner", "a" * 40, [TARGET_SPEC])
    job = enqueue_submission(queue, "owner", "a" * 40, [TARGET_SPEC], "e2e",
                             capacity_configuration=config())[0]
    different = enqueue_submission(queue, "owner", "a" * 40, [TARGET_SPEC], "e2e",
                                   capacity_configuration=config(profile="burst"))[0]
    assert job["id"] != different["id"]
    assert json.loads(queue.status(job["id"])[0]["capacity_configuration"]) == config()
    remote = GitHub.__new__(GitHub)
    remote.repo = "example/repo"
    calls = []
    remote.request = lambda endpoint, payload: calls.append((endpoint, payload))
    remote.dispatch(job)
    assert json.loads(calls[0][1]["inputs"]["capacity_configuration"]) == config()
    assert calls[0][0].endswith("isolated-tests.yml/dispatches")


def test_paced_representative_does_not_require_a_calendar_day(tmp_path):
    queue = Queue(tmp_path / "queue.db")
    value = configuration_for_submission(queue, source="a" * 40, specs=[CALIBRATION_SPEC],
        mode="e2e", calibration_job="", profile="sustained", duration_seconds=900,
        timeout_seconds=3600)
    assert value == config(profile="sustained", timeout_seconds=3600, calibration_run_id=0)
    with pytest.raises(ValueError, match="duration and cleanup"):
        validate_configuration(config(profile="sustained", timeout_seconds=1000),
                               source="a" * 40, target=True)


def artifact(**extra):
    value = io.BytesIO()
    with zipfile.ZipFile(value, "w") as bundle:
        for name in CALIBRATION_FILES:
            bundle.writestr(name, '{"synthetic":true}')
        for name, text in extra.items():
            bundle.writestr(name, text)
    return value.getvalue()


def test_private_artifact_admits_only_three_calibration_objects():
    found = calibration_bytes(artifact(**{"ci-capacity-private/capacity-failure-rows.jsonl": "private"}))
    assert set(found) == set(CALIBRATION_FILES.values())
    assert all(content == b'{"synthetic":true}' for content in found.values())
    with pytest.raises(RuntimeError, match="Unsafe"):
        calibration_bytes(artifact(**{"../escape": "private"}))
    with pytest.raises(RuntimeError, match="duplicate"):
        calibration_bytes(artifact(**{"nested/ci-storage-capacity.json": "{}"}))
    with pytest.raises(RuntimeError, match="download limit"):
        calibration_bytes(b"x" * (2 * 1024**2 + 1))


def test_signed_artifact_redirect_never_receives_repository_token():
    request = urllib.request.Request("https://api.github.com/artifact", headers={"Authorization": "secret"})
    redirected = ArtifactRedirect().redirect_request(request, None, 302, "redirect", {},
                                                     "https://signed.example.test/archive?signature=test")
    assert redirected.get_header("Authorization") is None
    with pytest.raises(RuntimeError, match="Unsafe"):
        ArtifactRedirect().redirect_request(request, None, 302, "redirect", {}, "http://example.test/archive")


def test_dedicated_runner_exception_applies_only_to_capacity_target(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "self-hosted")
    monkeypatch.setenv("OPENMATES_CI_CAPACITY_DEDICATED", "1")
    monkeypatch.setenv("CI_SPECS_JSON", json.dumps([TARGET_SPEC]))
    ci_environment.require_runner()
    monkeypatch.setenv("CI_SPECS_JSON", json.dumps([CALIBRATION_SPEC]))
    with pytest.raises(RuntimeError, match="dedicated capacity"):
        ci_environment.require_runner()


def test_unconfigured_selfhosted_evidence_remains_rejected(tmp_path):
    class Remote:
        repo = "example/repo"
        def request(self, endpoint):
            if endpoint.endswith("/jobs?per_page=100"):
                return {"jobs": [{"labels": ["self-hosted", "Linux", "X64", "openmates-capacity"]}]}
            return {}
    job = {"id": "job", "run_id": 7, "state": "success", "source": "a" * 40,
           "specs": json.dumps([CALIBRATION_SPEC])}
    with pytest.raises(RuntimeError, match="admitted isolated"):
        ci_results.fetch(Remote(), job, tmp_path)
