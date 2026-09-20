# contract-test-file: tooling

import json
from pathlib import Path

from scripts import ci_artifacts as artifacts
from scripts import ci_runtime_images as runtime_images


SOURCE = "a" * 40
TREE = "b" * 40
HARNESS = "c" * 40


def prepared_root(root: Path) -> None:
    web = root / "frontend/apps/web_app/build"
    cli = root / "frontend/packages/openmates-cli/dist"
    translations = root / "frontend/packages/ui/src/i18n/locales"
    web.mkdir(parents=True, exist_ok=True)
    cli.mkdir(parents=True, exist_ok=True)
    translations.mkdir(parents=True, exist_ok=True)
    (web / "index.html").write_text("prepared web")
    (web / "nested").mkdir(exist_ok=True)
    (web / "nested/app.js").write_text("prepared js")
    (cli / "cli.js").write_text("prepared cli")
    (translations / "en.json").write_text('{"prepared":true}')


def make_bundle(root: Path, output: Path, **kwargs):
    prepared_root(root)
    return artifacts.create_bundle(
        root,
        output,
        SOURCE,
        candidate_tree=TREE,
        harness_commit=HARNESS,
        include_cli=kwargs.pop("include_cli", True),
        include_upload=kwargs.pop("include_upload", False),
        **kwargs,
    )


def test_preparation_key_is_pure_and_invalidates_capabilities_environment_toolchain():
    first = artifacts.preparation_key(SOURCE)
    assert artifacts.preparation_key(SOURCE) == first
    assert artifacts.preparation_key("b" * 40) != first
    assert artifacts.preparation_key(SOURCE, include_cli=False) != first
    assert artifacts.preparation_key(SOURCE, include_upload=True) != first
    assert (
        artifacts.preparation_key(
            SOURCE,
            build_environment={**artifacts.DEFAULT_BUILD_ENVIRONMENT, "VITE_ENV": "other"},
        )
        != first
    )
    assert artifacts.preparation_key(SOURCE, toolchain={"node": "25"}) != first


def test_restore_replaces_stale_outputs_and_verifies_exact_bytes(tmp_path):
    producer = tmp_path / "producer"
    bundle = tmp_path / "bundle"
    make_bundle(producer, bundle)
    consumer = tmp_path / "consumer"
    stale = consumer / "frontend/apps/web_app/build/stale.js"
    stale.parent.mkdir(parents=True)
    stale.write_text("must disappear")
    receipt = artifacts.restore_bundle(
        consumer,
        bundle,
        SOURCE,
        candidate_tree=TREE,
        include_cli=True,
        include_upload=False,
    )
    assert receipt["reused"] is True
    assert not stale.exists()
    assert (
        consumer / "frontend/apps/web_app/build/index.html"
    ).read_text() == "prepared web"
    assert (
        consumer / "frontend/packages/openmates-cli/dist/cli.js"
    ).read_text() == "prepared cli"
    assert (
        consumer / "frontend/packages/ui/src/i18n/locales/en.json"
    ).read_text() == '{"prepared":true}'


def test_corrupt_artifact_is_rejected_without_replacing_existing_output(tmp_path):
    producer = tmp_path / "producer"
    bundle = tmp_path / "bundle"
    make_bundle(producer, bundle)
    with (bundle / "web.tar.gz").open("ab") as handle:
        handle.write(b"corrupt")
    consumer = tmp_path / "consumer"
    existing = consumer / "frontend/apps/web_app/build/index.html"
    existing.parent.mkdir(parents=True)
    existing.write_text("cold output remains")
    receipt = artifacts.restore_bundle(
        consumer,
        bundle,
        SOURCE,
        candidate_tree=TREE,
        include_cli=True,
        include_upload=False,
    )
    assert receipt["reused"] is False
    assert receipt["cold_fallback"] is True
    assert receipt["reason"] == "web_artifact_size_mismatch"
    assert existing.read_text() == "cold output remains"


def test_deleted_artifact_and_build_environment_mismatch_report_cold_fallback(tmp_path):
    producer = tmp_path / "producer"
    bundle = tmp_path / "bundle"
    make_bundle(producer, bundle)
    (bundle / "cli.tar.gz").unlink()
    missing = artifacts.restore_bundle(
        tmp_path / "missing-consumer",
        bundle,
        SOURCE,
        candidate_tree=TREE,
        include_cli=True,
        include_upload=False,
    )
    assert missing["reason"] == "cli_artifact_missing"

    second_bundle = tmp_path / "second-bundle"
    make_bundle(producer, second_bundle)
    changed_env = {
        **artifacts.DEFAULT_BUILD_ENVIRONMENT,
        "VITE_API_URL": "http://different.invalid",
    }
    mismatch = artifacts.restore_bundle(
        tmp_path / "env-consumer",
        second_bundle,
        SOURCE,
        candidate_tree=TREE,
        include_cli=True,
        include_upload=False,
        build_environment=changed_env,
    )
    assert mismatch["reason"] == "preparation_key_mismatch"


def test_runtime_archive_corruption_is_rejected_before_web_restore(tmp_path):
    producer = tmp_path / "producer"
    bundle = tmp_path / "bundle"
    image = bundle / "images/api.tar"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"docker archive")
    runtime = tmp_path / "runtime.json"
    runtime.write_text(
        json.dumps(
            {
                "format_version": 2,
                "images": [
                    {
                        "kind": "api",
                        "runtime_key": "d" * 64,
                        "archive_path": "images/api.tar",
                        "archive_sha256": artifacts.sha256_file(image),
                        "archive_size": image.stat().st_size,
                        "image_ref": "openmates-ci-api:local",
                    }
                ],
            }
        )
    )
    make_bundle(producer, bundle, runtime_receipt=runtime)
    image.write_bytes(b"tampered")
    consumer = tmp_path / "consumer"
    receipt = artifacts.restore_bundle(
        consumer,
        bundle,
        SOURCE,
        candidate_tree=TREE,
        include_cli=True,
        include_upload=False,
    )
    assert receipt["reused"] is False
    assert receipt["reason"] == "api_image_archive_mismatch"
    assert not (consumer / "frontend/apps/web_app/build").exists()


def test_harness_mismatch_is_an_explicit_cold_fallback(tmp_path):
    producer = tmp_path / "producer"
    bundle = tmp_path / "bundle"
    make_bundle(producer, bundle)
    receipt = artifacts.restore_bundle(
        tmp_path / "consumer",
        bundle,
        SOURCE,
        candidate_tree=TREE,
        include_cli=True,
        include_upload=False,
        harness_commit="d" * 40,
    )
    assert receipt["reused"] is False
    assert receipt["reason"] == "harness_commit_mismatch"


def test_create_command_receipt_has_source_bound_result_identity(tmp_path, monkeypatch):
    root = tmp_path / "producer"
    bundle = tmp_path / "bundle"
    make_bundle(root, bundle)
    manifest = json.loads((bundle / artifacts.MANIFEST_NAME).read_text())
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    artifacts.write_producer_results(root, manifest, bundle / artifacts.MANIFEST_NAME)
    report = json.loads((root / "test-results/ci-results.json").read_text())
    assert report["success"] is True
    assert report["source_commit"] == SOURCE
    assert report["harness_commit"] == HARNESS
    assert report["run_id"] == "12345"
    assert report["results"][0]["preparation_key"] == manifest["preparation_key"]


def test_cold_image_export_rejects_wrong_compatibility_label_before_save(
    tmp_path, monkeypatch
):
    receipt = tmp_path / "runtime.json"
    receipt.write_text(
        json.dumps(
            {
                "format_version": 2,
                "images": [
                    {"kind": kind, "reused": False, "reason": "miss"}
                    for kind in ("api", "cms", "setup", "schema")
                ],
            }
        )
    )
    monkeypatch.setattr(runtime_images, "runtime_key", lambda root, kind: "e" * 64)
    monkeypatch.setattr(
        artifacts,
        "_docker_inspect",
        lambda image: {
            "Size": 1,
            "Config": {"Labels": {runtime_images.LABEL: "f" * 64}},
        },
    )
    calls = []
    monkeypatch.setattr(artifacts.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    try:
        artifacts.export_runtime_images(tmp_path, receipt, tmp_path / "bundle")
    except RuntimeError as exc:
        assert "wrong compatibility label" in str(exc)
    else:
        raise AssertionError("Wrong-label image was exported")
    assert calls == []


def test_runtime_rejection_is_retained_as_explicit_cold_fallback(tmp_path):
    results = tmp_path / "test-results"
    results.mkdir()
    (results / artifacts.RECEIPT_NAME).write_text(
        json.dumps({"reused": True, "preparation_key": "a" * 64})
    )
    receipt = artifacts.record_runtime_fallback(
        tmp_path, "runtime_manifest_rejected"
    )
    assert receipt["reused"] is True  # Web/CLI bytes remain verified and reusable.
    assert receipt["runtime_reused"] is False
    assert receipt["runtime_cold_fallback"] is True
    assert receipt["runtime_fallback_reason"] == "runtime_manifest_rejected"
