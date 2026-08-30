"""Tests for narrated specification demonstration contracts.

Purpose: enforce eligibility, narration outlines, and completion evidence.
Architecture: extend Schema V2 fixtures without changing legacy specifications.
Privacy: fixtures contain synthetic paths, hashes, and identifiers only.
Tests: python3 -m pytest scripts/tests/test_spec_demonstration_workflow.py.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path | None = None):
    module_path = path or ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_spec(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "spec.yml"
    path.write_text(body, encoding="utf-8")
    return path


def schema_v2_spec() -> str:
    fixtures = load_module(
        "spec_workflow_fixture",
        ROOT / "scripts" / "tests" / "test_spec_workflow_validation.py",
    )
    return fixtures.schema_v2_spec()


def required_demonstration(*, evidence: str | None = None) -> str:
    evidence_block = evidence or """  evidence:
    status: pending
    subject_commit: ""
    manifest_path: ""
    manifest_hash: ""
    privacy_status: pending
    audio_status: pending
    review_status: pending
    review_run_id: ""
    review_attempts: 0
    timestamp: ""
    publication_status: pending
"""
    return f"""demonstration:
  eligibility:
    status: required
    surface: visual
    reason: The example changes a visible user flow.
    classified_at: "2026-08-06T00:00:00Z"
  narration_outline:
    - id: NARR-1
      purpose: Explain the successful example flow.
      expected_proof: The completed result is visible after the action.
      scenario_ids: [S-1]
      acceptance_criteria: [AC-1]
{evidence_block}
"""


def with_demonstration(body: str, demonstration: str) -> str:
    return body.replace("implementation_state:\n", f"{demonstration}\nimplementation_state:\n", 1)


def passed_evidence(**overrides: object) -> str:
    values: dict[str, object] = {
        "status": "passed",
        "subject_commit": "abc1234",
        "manifest_path": "test-results/spec-demos/example/run-1/manifest.json",
        "manifest_hash": "sha256:manifest",
        "privacy_status": "passed",
        "review_status": "passed",
        "review_run_id": "review-1",
        "review_attempts": 1,
        "timestamp": "2026-08-06T00:00:00Z",
        "audio_status": "passed",
        "publication_status": "delivered",
    }
    values.update(overrides)
    return """  evidence:
    status: {status}
    subject_commit: {subject_commit}
    manifest_path: {manifest_path}
    manifest_hash: {manifest_hash}
    privacy_status: {privacy_status}
    audio_status: {audio_status}
    review_status: {review_status}
    review_run_id: {review_run_id}
    review_attempts: {review_attempts}
    timestamp: "{timestamp}"
    publication_status: {publication_status}
""".format(**values)


def write_passed_manifest(
    tmp_path: Path,
    *,
    subject_commit: str = "abc1234",
    privacy_status: str = "passed",
) -> tuple[Path, str]:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "subject_commit": subject_commit,
                "privacy": {"status": privacy_status},
                "narration_audio": {"status": "passed", "provider": "elevenlabs", "model": "eleven_flash_v2_5"},
                "video_metadata": {"has_audio": True},
                "review": {"status": "passed", "run_id": "review-1", "attempt_count": 1},
                "publication": {"status": "delivered", "snippet_html": "<video controls></video>"},
            }
        ),
        encoding="utf-8",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("publication")
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return manifest_path, f"sha256:{digest}"


def test_validator_accepts_required_demonstration_outline(tmp_path: Path) -> None:
    spec_validate = load_module("spec_validate")
    path = write_spec(tmp_path, with_demonstration(schema_v2_spec(), required_demonstration()))

    data = spec_validate.validate_spec(path)

    assert data["demonstration"]["narration_outline"][0]["id"] == "NARR-1"


def test_validator_accepts_caption_only_demonstration_audio_status(tmp_path: Path) -> None:
    spec_validate = load_module("spec_validate")
    demonstration = required_demonstration().replace("audio_status: pending", "audio_status: not_required")
    path = write_spec(tmp_path, with_demonstration(schema_v2_spec(), demonstration))

    data = spec_validate.validate_spec(path)

    assert data["demonstration"]["evidence"]["audio_status"] == "not_required"


def test_validator_rejects_required_demonstration_without_outline(tmp_path: Path) -> None:
    spec_validate = load_module("spec_validate")
    demonstration = required_demonstration().replace(
        """  narration_outline:
    - id: NARR-1
      purpose: Explain the successful example flow.
      expected_proof: The completed result is visible after the action.
      scenario_ids: [S-1]
      acceptance_criteria: [AC-1]
""",
        "",
    )
    path = write_spec(tmp_path, with_demonstration(schema_v2_spec(), demonstration))

    with pytest.raises(spec_validate.SpecError, match="narration_outline"):
        spec_validate.validate_spec(path)


def test_validator_accepts_reasoned_non_visual_not_applicable(tmp_path: Path) -> None:
    spec_validate = load_module("spec_validate")
    demonstration = """demonstration:
  eligibility:
    status: not_applicable
    surface: non_visual
    reason: The change only updates a deterministic repository audit message.
    classified_at: "2026-08-06T00:00:00Z"
    verification_ids: [T-PYTEST-EXAMPLE]
"""
    path = write_spec(tmp_path, with_demonstration(schema_v2_spec(), demonstration))

    assert spec_validate.validate_spec(path)["demonstration"]["eligibility"]["status"] == "not_applicable"


@pytest.mark.parametrize("surface", ["visual", "cli", "native"])
def test_validator_rejects_not_applicable_for_observable_surfaces(tmp_path: Path, surface: str) -> None:
    spec_validate = load_module("spec_validate")
    demonstration = f"""demonstration:
  eligibility:
    status: not_applicable
    surface: {surface}
    reason: Incorrectly skipped observable behavior.
    classified_at: "2026-08-06T00:00:00Z"
    verification_ids: [T-PYTEST-EXAMPLE]
"""
    path = write_spec(tmp_path, with_demonstration(schema_v2_spec(), demonstration))

    with pytest.raises(spec_validate.SpecError, match="non_visual"):
        spec_validate.validate_spec(path)


def test_verifier_rejects_missing_required_demonstration_evidence(tmp_path: Path) -> None:
    spec_verify = load_module("spec_verify")
    path = write_spec(tmp_path, with_demonstration(schema_v2_spec(), required_demonstration()))

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert any("demonstration" in failure and "passing" in failure for failure in failures)


def test_verifier_accepts_reasoned_non_visual_not_applicable(tmp_path: Path) -> None:
    spec_verify = load_module("spec_verify")
    demonstration = """demonstration:
  eligibility:
    status: not_applicable
    surface: non_visual
    reason: The change only updates a deterministic repository audit message.
    classified_at: "2026-08-06T00:00:00Z"
    verification_ids: [T-PYTEST-EXAMPLE]
  status: not_applicable
  evidence:
    status: not_applicable
    reason: No user-visible product surface changed.
"""
    path = write_spec(tmp_path, with_demonstration(schema_v2_spec(), demonstration))

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert not [failure for failure in failures if failure.startswith("demonstration:")]


def test_verifier_rejects_user_waived_required_demonstration(tmp_path: Path) -> None:
    spec_verify = load_module("spec_verify")
    evidence = """  evidence:
    status: waived
    subject_commit: abc1234
    manifest_path: not_applicable
    manifest_hash: not_applicable
    privacy_status: waived
    audio_status: not_required
    review_status: waived
    review_run_id: not_applicable
    review_attempts: 0
    timestamp: "2026-08-06T00:00:00Z"
    publication_status: not_configured
    actor: user
    reason: User waived proof video after deployed tests succeeded.
"""
    path = write_spec(tmp_path, with_demonstration(schema_v2_spec(), required_demonstration(evidence=evidence)))

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert any("cannot waive" in failure for failure in failures)


def test_verifier_rejects_user_waived_demonstration_without_actor(tmp_path: Path) -> None:
    spec_verify = load_module("spec_verify")
    evidence = """  evidence:
    status: waived
    subject_commit: abc1234
    manifest_path: not_applicable
    manifest_hash: not_applicable
    privacy_status: waived
    audio_status: not_required
    review_status: waived
    review_run_id: not_applicable
    review_attempts: 0
    publication_status: not_configured
    timestamp: "2026-08-06T00:00:00Z"
    reason: User waived proof video after deployed tests succeeded.
"""
    path = write_spec(tmp_path, with_demonstration(schema_v2_spec(), required_demonstration(evidence=evidence)))

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert any("cannot waive" in failure for failure in failures)


def test_verifier_rejects_implemented_spec_without_demonstration(tmp_path: Path) -> None:
    spec_verify = load_module("spec_verify")
    path = write_spec(tmp_path, schema_v2_spec())

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert any("every implemented executable spec" in failure for failure in failures)


def test_verifier_rejects_publication_without_embeddable_snippet(tmp_path: Path) -> None:
    spec_verify = load_module("spec_verify")
    manifest_path, _ = write_passed_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["publication"] = {"status": "delivered"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    immutable = dict(manifest)
    immutable.pop("publication")
    manifest_hash = "sha256:" + hashlib.sha256(
        json.dumps(immutable, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path = write_spec(
        tmp_path,
        with_demonstration(
            schema_v2_spec(),
            required_demonstration(
                evidence=passed_evidence(manifest_path=manifest_path, manifest_hash=manifest_hash)
            ),
        ),
    )

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert any("embeddable response-media snippet" in failure for failure in failures)


def test_verifier_accepts_current_review_with_delivered_discord_publication(tmp_path: Path) -> None:
    spec_verify = load_module("spec_verify")
    manifest_path, manifest_hash = write_passed_manifest(tmp_path)
    path = write_spec(
        tmp_path,
        with_demonstration(
            schema_v2_spec(),
            required_demonstration(
                evidence=passed_evidence(manifest_path=manifest_path, manifest_hash=manifest_hash)
            ),
        ),
    )

    assert spec_verify.verify_spec(path, require_red=False, require_green=True) == []


def test_verifier_rejects_pending_discord_publication(tmp_path: Path) -> None:
    spec_verify = load_module("spec_verify")
    manifest_path, manifest_hash = write_passed_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["publication"] = {"status": "publication_pending"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_without_publication = dict(manifest)
    manifest_without_publication.pop("publication")
    manifest_hash = "sha256:" + hashlib.sha256(
        json.dumps(manifest_without_publication, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path = write_spec(
        tmp_path,
        with_demonstration(
            schema_v2_spec(),
            required_demonstration(
                evidence=passed_evidence(
                    manifest_path=manifest_path,
                    manifest_hash=manifest_hash,
                    publication_status="publication_pending",
                )
            ),
        ),
    )

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert any("response-media proof embed" in failure for failure in failures)


def test_verifier_rejects_stale_demonstration_evidence(tmp_path: Path) -> None:
    spec_verify = load_module("spec_verify")
    manifest_path, manifest_hash = write_passed_manifest(tmp_path, subject_commit="stale123")
    path = write_spec(
        tmp_path,
        with_demonstration(
            schema_v2_spec(),
            required_demonstration(
                evidence=passed_evidence(
                    subject_commit="stale123", manifest_path=manifest_path, manifest_hash=manifest_hash
                )
            ),
        ),
    )

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert any("demonstration" in failure and "stale" in failure for failure in failures)


def test_verifier_normalizes_decorated_commits_but_requires_exact_match(tmp_path: Path) -> None:
    spec_verify = load_module("spec_verify")
    manifest_path, manifest_hash = write_passed_manifest(tmp_path, subject_commit="working-tree@abc1234")
    body = schema_v2_spec().replace("subject_commit: abc1234", "subject_commit: draft@abc1234", 1)
    path = write_spec(
        tmp_path,
        with_demonstration(
            body,
            required_demonstration(
                evidence=passed_evidence(
                    subject_commit="working-tree@abc1234",
                    manifest_path=manifest_path,
                    manifest_hash=manifest_hash,
                )
            ),
        ),
    )

    assert spec_verify.verify_spec(path, require_red=False, require_green=True) == []


def test_verifier_accepts_disabled_proof_privacy_scan(tmp_path: Path) -> None:
    spec_verify = load_module("spec_verify")
    manifest_path, manifest_hash = write_passed_manifest(tmp_path, privacy_status="not_applicable")
    path = write_spec(
        tmp_path,
        with_demonstration(
            schema_v2_spec(),
            required_demonstration(
                evidence=passed_evidence(
                    privacy_status="not_applicable",
                    manifest_path=manifest_path,
                    manifest_hash=manifest_hash,
                )
            ),
        ),
    )

    assert spec_verify.verify_spec(path, require_red=False, require_green=True) == []


def test_verifier_requires_user_blocker_after_initial_review_and_three_retries(tmp_path: Path) -> None:
    spec_verify = load_module("spec_verify")
    evidence = passed_evidence(
        status="failed",
        privacy_status="passed",
        review_status="failed",
        review_attempts=4,
    )
    path = write_spec(
        tmp_path,
        with_demonstration(schema_v2_spec(), required_demonstration(evidence=evidence)),
    )

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert any("structured user blocker" in failure for failure in failures)


def test_verifier_rejects_fabricated_or_changed_demonstration_manifest(tmp_path: Path) -> None:
    spec_verify = load_module("spec_verify")
    manifest_path, manifest_hash = write_passed_manifest(tmp_path)
    manifest_path.write_text('{"subject_commit":"abc1234"}', encoding="utf-8")
    path = write_spec(
        tmp_path,
        with_demonstration(
            schema_v2_spec(),
            required_demonstration(
                evidence=passed_evidence(manifest_path=manifest_path, manifest_hash=manifest_hash)
            ),
        ),
    )

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert any("manifest hash" in failure for failure in failures)


def test_verifier_rejects_recorded_publication_status_that_differs_from_manifest(tmp_path: Path) -> None:
    spec_verify = load_module("spec_verify")
    manifest_path, manifest_hash = write_passed_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["publication"] = {"status": "delivered", "snippet_html": "<video controls></video>"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    path = write_spec(
        tmp_path,
        with_demonstration(
            schema_v2_spec(),
            required_demonstration(
                evidence=passed_evidence(
                    manifest_path=manifest_path,
                    manifest_hash=manifest_hash,
                    publication_status="publication_pending",
                )
            ),
        ),
    )

    failures = spec_verify.verify_spec(path, require_red=False, require_green=True)

    assert not any("manifest hash" in failure for failure in failures)
    assert any("publication_status" in failure or "response-media proof embed" in failure for failure in failures)


def test_demonstration_recorder_derives_evidence_from_manifest(tmp_path: Path) -> None:
    recorder = load_module("spec_evidence")
    manifest_path, manifest_hash = write_passed_manifest(tmp_path)
    data = {"demonstration": {"evidence": {}}}
    payload = {"status": "passed", "subject_commit": "abc1234", "command": "demo", "run_id": "run-1", "timestamp": "now"}

    recorder.record_demonstration(
        data,
        payload,
        SimpleNamespace(manifest_path=str(manifest_path)),
    )

    assert data["demonstration"]["evidence"]["manifest_hash"] == manifest_hash
    assert data["demonstration"]["evidence"]["audio_status"] == "passed"
    assert data["demonstration"]["evidence"]["review_run_id"] == "review-1"
