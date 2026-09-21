# contract-test-file: tooling
"""Validate private CI preparation transport without Docker or network access."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from scripts import ci_preparation_transport as transport


SOURCE = "a" * 40
KEY = "b" * 64
PRODUCER = "c" * 64
NOW = dt.datetime(2026, 9, 20, 12, tzinfo=dt.timezone.utc)


def object_url(object_key: str, operation: str = "get") -> str:
    return (
        f"https://nbg1.your-objectstorage.com/{transport.BUCKET_NAME}/"
        f"{object_key}?X-Amz-Operation={operation}&X-Amz-Signature=secret"
    )


def signer(objects, expires_seconds):
    assert expires_seconds == 48 * 60 * 60
    return {
        relative: {
            "put_url": object_url(key, "put"),
            "get_url": object_url(key, "get"),
        }
        for relative, key in objects.items()
    }


def producer_job():
    return {
        "id": PRODUCER,
        "mode": "prepare",
        "source": SOURCE,
        "preparation_key": KEY,
    }


def consumer_job():
    return {
        "id": "d" * 64,
        "mode": "e2e",
        "source": SOURCE,
        "preparation_key": KEY,
        "preparation_id": PRODUCER,
    }


def ticket(root: Path) -> dict:
    return transport.get_or_create_ticket(
        root, PRODUCER, SOURCE, KEY, now=NOW, presign=signer
    )


def write_bundle(directory: Path, run_id: str = "123") -> tuple[dict, dict[str, bytes]]:
    content = {
        "web.tar.gz": b"web bytes",
        "web-preview.tar.gz": b"web preview bytes",
        "translations.tar.gz": b"translation bytes",
        "cli.tar.gz": b"cli bytes",
        "images/api.tar": b"api image bytes",
    }
    artifacts = {}
    for name in (
        "web.tar.gz",
        "web-preview.tar.gz",
        "translations.tar.gz",
        "cli.tar.gz",
    ):
        value = content[name]
        artifacts[name] = {
            "path": name,
            "size": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
    api = content["images/api.tar"]
    manifest = {
        "source_commit": SOURCE,
        "preparation_key": KEY,
        "producer_run_id": run_id,
        "artifacts": artifacts,
        "runtime_images": {
            "format_version": 2,
            "images": [
                {
                    "kind": "api",
                    "archive_path": "images/api.tar",
                    "archive_size": len(api),
                    "archive_sha256": hashlib.sha256(api).hexdigest(),
                }
            ],
        },
    }
    directory.mkdir(parents=True)
    for relative, value in content.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return manifest, content


def write_schema_diagnostic(path: Path, run_id: str = "123") -> dict:
    report = {
        "format_version": 1,
        "source_commit": SOURCE,
        "preparation_key": KEY,
        "producer_run_id": run_id,
        "failure": {"phase": "fresh-restore", "detail": "sanitized"},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report))
    return report


def dispatch_view(value: dict, producer: bool) -> dict:
    return json.loads(
        json.dumps(transport._dispatch_view(value, producer=producer))
    )


def test_ticket_is_durable_owner_only_fixed_and_idempotent(tmp_path):
    calls = []

    def tracked_signer(objects, expires):
        calls.append(dict(objects))
        return signer(objects, expires)

    first = transport.get_or_create_ticket(
        tmp_path, PRODUCER, SOURCE, KEY, now=NOW, presign=tracked_signer
    )
    second = transport.get_or_create_ticket(
        tmp_path,
        PRODUCER,
        SOURCE,
        KEY,
        now=NOW + dt.timedelta(minutes=1),
        presign=tracked_signer,
    )
    assert first == second
    assert len(calls) == 1
    assert set(first["objects"]) == set(transport.TICKET_PATHS)
    prefix = f"{transport.OBJECT_PREFIX}/{SOURCE}/{KEY}/{PRODUCER}/"
    assert all(item["object_key"].startswith(prefix) for item in first["objects"].values())
    directory = tmp_path / transport.TICKET_DIR
    path = directory / f"{PRODUCER}.json"
    lock = directory / f"{PRODUCER}.lock"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(lock.stat().st_mode) == 0o600


def test_dispatch_producer_gets_put_consumer_get_only_and_missing_fails(tmp_path):
    producer = json.loads(
        transport.dispatch_ticket(
            tmp_path, producer_job(), now=NOW, presign=signer
        )
    )
    consumer = json.loads(
        transport.dispatch_ticket(tmp_path, consumer_job(), now=NOW)
    )
    assert all("put_url" in item for item in producer["objects"].values())
    assert all("put_url" not in item for item in consumer["objects"].values())
    assert all("get_url" in item for item in consumer["objects"].values())
    assert set(consumer["objects"]) == set(transport.ALLOWED_PATHS)
    assert set(producer["objects"]) == set(transport.TICKET_PATHS)
    assert set(producer["objects"][transport.SCHEMA_DIAGNOSTIC_PATH]) == {"put_url"}
    with pytest.raises(
        transport.PreparationTransportError, match="ticket is unavailable"
    ):
        transport.dispatch_ticket(tmp_path / "missing", consumer_job(), now=NOW)


def test_expired_consumer_ticket_fails_and_only_producer_can_refresh(tmp_path):
    transport.dispatch_ticket(tmp_path, producer_job(), now=NOW, presign=signer)
    expired = NOW + dt.timedelta(hours=49)
    with pytest.raises(transport.PreparationTransportError, match="unavailable"):
        transport.dispatch_ticket(tmp_path, consumer_job(), now=expired)
    refreshed = json.loads(
        transport.dispatch_ticket(
            tmp_path, producer_job(), now=expired, presign=signer
        )
    )
    assert dt.datetime.fromisoformat(refreshed["expires_at"]) > expired


def test_expired_but_corrupted_ticket_is_not_silently_replaced(tmp_path):
    ticket(tmp_path)
    ticket_path = tmp_path / transport.TICKET_DIR / f"{PRODUCER}.json"
    stored = json.loads(ticket_path.read_text())
    stored["objects"]["manifest.json"]["get_url"] = object_url(
        f"{transport.OBJECT_PREFIX}/{SOURCE}/{KEY}/{PRODUCER}/web.tar.gz"
    )
    ticket_path.write_text(json.dumps(stored))
    with pytest.raises(transport.PreparationTransportError, match="URL is invalid"):
        transport.get_or_create_ticket(
            tmp_path,
            PRODUCER,
            SOURCE,
            KEY,
            now=NOW + dt.timedelta(hours=49),
            presign=signer,
        )


def test_legacy_ticket_format_fails_closed_without_resigning(tmp_path):
    ticket(tmp_path)
    ticket_path = tmp_path / transport.TICKET_DIR / f"{PRODUCER}.json"
    stored = json.loads(ticket_path.read_text())
    stored["format_version"] = 1
    ticket_path.write_text(json.dumps(stored))
    calls = []
    with pytest.raises(transport.PreparationTransportError, match="unavailable"):
        transport.get_or_create_ticket(
            tmp_path,
            PRODUCER,
            SOURCE,
            KEY,
            now=NOW,
            presign=lambda *args: calls.append(args),
        )
    assert calls == []


def test_consumer_rejects_ticket_with_non_owner_permissions(tmp_path):
    ticket_path = (
        tmp_path / transport.TICKET_DIR / f"{PRODUCER}.json"
    )
    ticket(tmp_path)
    ticket_path.chmod(0o644)
    with pytest.raises(transport.PreparationTransportError, match="unavailable"):
        transport.dispatch_ticket(tmp_path, consumer_job(), now=NOW)


def test_presigner_reuses_private_bucket_without_lifecycle_or_urls_in_argv(monkeypatch):
    calls = []

    def run(command, *, env=None, **kwargs):
        assert kwargs["timeout"] == transport.PRESIGN_TIMEOUT_SECONDS
        calls.append((command, env))
        request = json.loads(env["OPENMATES_CI_PREPARATION_REQUEST"])
        output = signer(request["objects"], request["expires_in"])
        return subprocess.CompletedProcess(
            command, 0, json.dumps(output) + "\n", ""
        )

    monkeypatch.setattr(transport.subprocess, "run", run)
    objects = {"manifest.json": f"{transport.OBJECT_PREFIX}/x/manifest.json"}
    result = transport._presign_objects(objects, transport.EXPIRES_SECONDS)
    command, environment = calls[0]
    assert not any("X-Amz" in value for value in command)
    request = json.loads(environment["OPENMATES_CI_PREPARATION_REQUEST"])
    assert request["bucket"] == transport.BUCKET_NAME
    assert request["objects"] == objects
    assert result["manifest.json"]["put_url"].startswith("https://")
    assert "put_bucket_lifecycle" not in transport.INNER_PRESIGN_CODE
    assert "put_bucket_acl" not in transport.INNER_PRESIGN_CODE
    assert '"ACL": "private"' in transport.INNER_PRESIGN_CODE
    assert '"ContentType": "application/octet-stream"' in transport.INNER_PRESIGN_CODE


def test_presigner_error_never_returns_stderr_or_presigned_url(monkeypatch):
    secret = object_url("candidates/preparations/secret")
    monkeypatch.setattr(
        transport.subprocess,
        "run",
        lambda command, env=None, **kwargs: subprocess.CompletedProcess(
            command, 1, "", f"failed {secret}"
        ),
    )
    with pytest.raises(transport.PreparationTransportError) as captured:
        transport._presign_objects({"manifest.json": "key"}, 10)
    assert secret not in str(captured.value)


def test_presigner_timeout_is_bounded_and_redacted(monkeypatch):
    def timeout(command, **kwargs):
        assert kwargs["timeout"] == transport.PRESIGN_TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(transport.subprocess, "run", timeout)
    with pytest.raises(
        transport.PreparationTransportError,
        match="Failed to create preparation transport ticket",
    ):
        transport._presign_objects({"manifest.json": "key"}, 10)


def test_event_input_masks_urls_and_requires_exact_identity(tmp_path):
    stored = ticket(tmp_path)
    compact = dispatch_view(stored, producer=False)
    event = {
        "inputs": {
            "source_commit": SOURCE,
            "preparation_key": KEY,
            "preparation_transport": json.dumps(compact),
        }
    }
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event))
    masked = []
    loaded, _ = transport.event_ticket(
        event_path=path,
        environment={"BUILD_COMMIT_SHA": SOURCE},
        mask=masked.append,
        now=NOW,
    )
    urls = [item["get_url"] for item in loaded["objects"].values()]
    assert set(masked) == {f"::add-mask::{url}" for url in urls}
    event["inputs"]["preparation_key"] = "d" * 64
    path.write_text(json.dumps(event))
    with pytest.raises(transport.PreparationTransportError, match="identity mismatch"):
        transport.event_ticket(
            event_path=path,
            environment={"BUILD_COMMIT_SHA": SOURCE},
            mask=lambda _: None,
            now=NOW,
        )


def test_invalid_url_is_rejected_without_emitting_or_echoing_secret(tmp_path):
    stored = dispatch_view(ticket(tmp_path), producer=False)
    secret = "https://example.com/private?token=very-secret"
    stored["objects"]["manifest.json"]["get_url"] = secret
    path = tmp_path / "event.json"
    path.write_text(
        json.dumps(
            {
                "inputs": {
                    "source_commit": SOURCE,
                    "preparation_key": KEY,
                    "preparation_transport": json.dumps(stored),
                }
            }
        )
    )
    masked = []
    with pytest.raises(transport.PreparationTransportError) as captured:
        transport.event_ticket(
            event_path=path,
            environment={"BUILD_COMMIT_SHA": SOURCE},
            mask=masked.append,
            now=NOW,
        )
    assert masked == []
    assert "very-secret" not in str(captured.value)


@pytest.mark.parametrize("mutation", ["wrong-path", "swapped"])
def test_runner_ticket_binds_each_url_to_its_exact_object_path(tmp_path, mutation):
    stored = dispatch_view(ticket(tmp_path), producer=False)
    if mutation == "wrong-path":
        stored["objects"]["manifest.json"]["get_url"] = object_url(
            f"{transport.OBJECT_PREFIX}/{SOURCE}/{KEY}/{PRODUCER}/web.tar.gz"
        )
    else:
        manifest_url = stored["objects"]["manifest.json"]["get_url"]
        stored["objects"]["manifest.json"]["get_url"] = stored["objects"][
            "web.tar.gz"
        ]["get_url"]
        stored["objects"]["web.tar.gz"]["get_url"] = manifest_url
    event_path = tmp_path / f"{mutation}.json"
    event_path.write_text(
        json.dumps(
            {
                "inputs": {
                    "mode": "e2e",
                    "source_commit": SOURCE,
                    "preparation_key": KEY,
                    "preparation_transport": json.dumps(stored),
                }
            }
        )
    )
    with pytest.raises(transport.PreparationTransportError, match="URL is invalid"):
        transport.event_ticket(
            event_path=event_path,
            environment={},
            mask=lambda _: None,
            now=NOW,
        )


def test_runner_ticket_rejects_raw_control_characters_before_masking(tmp_path):
    stored = dispatch_view(ticket(tmp_path), producer=False)
    stored["objects"]["manifest.json"]["get_url"] += "\n::warning::injected"
    event_path = tmp_path / "control.json"
    event_path.write_text(
        json.dumps(
            {
                "inputs": {
                    "mode": "e2e",
                    "source_commit": SOURCE,
                    "preparation_key": KEY,
                    "preparation_transport": json.dumps(stored),
                }
            }
        )
    )
    masked = []
    with pytest.raises(transport.PreparationTransportError, match="URL is invalid"):
        transport.event_ticket(
            event_path=event_path,
            environment={},
            mask=masked.append,
            now=NOW,
        )
    assert masked == []


def test_cli_error_boundary_hides_capability_text_in_non_url_input(
    tmp_path, monkeypatch, capsys
):
    marker = "CAPABILITY-NOT-IN-A-URL-92aa"
    stored = dispatch_view(ticket(tmp_path), producer=False)
    stored["expires_at"] = marker
    stored["diagnostic"] = marker
    event_path = tmp_path / "unsafe-cause.json"
    event_path.write_text(
        json.dumps(
            {
                "inputs": {
                    "mode": "e2e",
                    "source_commit": SOURCE,
                    "preparation_key": KEY,
                    "preparation_transport": json.dumps(stored),
                }
            }
        )
    )
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.delenv("BUILD_COMMIT_SHA", raising=False)
    monkeypatch.setattr(sys, "argv", ["ci_preparation_transport.py", "validate"])
    assert transport.entrypoint() == 1
    captured = capsys.readouterr()
    assert captured.err == "Preparation transport failed\n"
    assert marker not in captured.out
    assert marker not in captured.err


@pytest.mark.parametrize(
    ("producer", "mode", "expected_role"),
    [(True, "prepare", "producer"), (False, "e2e", "consumer")],
)
def test_validate_cli_masks_and_checks_role_before_build_without_run_ids(
    tmp_path, monkeypatch, capsys, producer, mode, expected_role
):
    stored = dispatch_view(ticket(tmp_path), producer=producer)
    event_path = tmp_path / f"{mode}.json"
    event_path.write_text(
        json.dumps(
            {
                "inputs": {
                    "mode": mode,
                    "source_commit": SOURCE,
                    "preparation_key": KEY,
                    "preparation_transport": json.dumps(stored),
                }
            }
        )
    )
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.delenv("BUILD_COMMIT_SHA", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.setattr(sys, "argv", ["ci_preparation_transport.py", "validate"])
    assert transport.main() == 0
    output = capsys.readouterr().out.splitlines()
    assert json.loads(output[-1]) == {"role": expected_role, "validated": True}
    assert sum(line.startswith("::add-mask::") for line in output) == (
        len(transport.ALLOWED_PATHS) * (2 if producer else 1)
        + (1 if producer else 0)
    )


def test_validate_rejects_wrong_role_capabilities(tmp_path):
    producer_view = dispatch_view(ticket(tmp_path), producer=True)
    with pytest.raises(transport.PreparationTransportError, match="role is invalid"):
        transport.validate_event_role(
            producer_view, {"mode": "e2e"}, command="validate"
        )


def test_consumer_role_cannot_upload_schema_diagnostic(tmp_path):
    consumer_view = dispatch_view(ticket(tmp_path), producer=False)
    assert transport.SCHEMA_DIAGNOSTIC_PATH not in consumer_view["objects"]
    with pytest.raises(transport.PreparationTransportError, match="role is invalid"):
        transport.validate_event_role(
            consumer_view,
            {"mode": "e2e"},
            command="upload-schema-diagnostic",
        )


def test_schema_diagnostic_upload_is_bound_and_has_safe_receipt(tmp_path):
    report_path = tmp_path / "schema-restore.json"
    write_schema_diagnostic(report_path)
    producer_view = dispatch_view(ticket(tmp_path), producer=True)
    uploads = []

    def put(url, path, size):
        uploads.append((url, path, size))

    result = transport.upload_schema_diagnostic(
        report_path,
        producer_view,
        source=SOURCE,
        preparation_key=KEY,
        producer_run_id="123",
        put=put,
    )
    assert result == {"diagnostic": "schema-restore", "uploaded": 1}
    assert len(uploads) == 1
    assert uploads[0][1:] == (report_path, report_path.stat().st_size)
    assert f"/{transport.SCHEMA_DIAGNOSTIC_PATH}?" in uploads[0][0]
    assert "failure" not in json.dumps(result)
    assert "url" not in json.dumps(result).lower()

    producer_view["objects"][transport.SCHEMA_DIAGNOSTIC_PATH]["put_url"] = (
        producer_view["objects"]["web.tar.gz"]["put_url"]
    )
    with pytest.raises(transport.PreparationTransportError, match="URL is invalid"):
        transport.upload_schema_diagnostic(
            report_path,
            producer_view,
            source=SOURCE,
            preparation_key=KEY,
            producer_run_id="123",
            put=lambda *args: pytest.fail("misbound diagnostic must not upload"),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_commit", "d" * 40),
        ("preparation_key", "e" * 64),
        ("producer_run_id", "999"),
        ("format_version", 2),
    ],
)
def test_schema_diagnostic_rejects_wrong_identity(tmp_path, field, value):
    report_path = tmp_path / "schema-restore.json"
    report = write_schema_diagnostic(report_path)
    report[field] = value
    report_path.write_text(json.dumps(report))
    with pytest.raises(transport.PreparationTransportError, match="identity mismatch"):
        transport.upload_schema_diagnostic(
            report_path,
            dispatch_view(ticket(tmp_path), producer=True),
            source=SOURCE,
            preparation_key=KEY,
            producer_run_id="123",
            put=lambda *args: pytest.fail("invalid diagnostic must not upload"),
        )


def test_schema_diagnostic_rejects_oversize_and_manifest_reference(tmp_path):
    report_path = tmp_path / "schema-restore.json"
    report_path.write_bytes(b"x" * (transport.MAX_SCHEMA_DIAGNOSTIC_BYTES + 1))
    with pytest.raises(transport.PreparationTransportError, match="unavailable"):
        transport.upload_schema_diagnostic(
            report_path,
            dispatch_view(ticket(tmp_path), producer=True),
            source=SOURCE,
            preparation_key=KEY,
            producer_run_id="123",
            put=lambda *args: pytest.fail("oversize diagnostic must not upload"),
        )

    manifest = {
        "artifacts": {
            "web": {
                "path": "web.tar.gz",
                "size": 1,
                "sha256": "0" * 64,
            },
            "translations": {
                "path": "translations.tar.gz",
                "size": 1,
                "sha256": "0" * 64,
            },
            "diagnostic": {
                "path": transport.SCHEMA_DIAGNOSTIC_PATH,
                "size": 1,
                "sha256": "0" * 64,
            },
        },
        "runtime_images": {"format_version": 2, "images": []},
    }
    with pytest.raises(transport.PreparationTransportError, match="path is invalid"):
        transport._manifest_references(manifest)


def test_owner_can_read_bound_schema_diagnostic_without_capability_receipt(tmp_path):
    expected = write_schema_diagnostic(tmp_path / "source.json")
    ticket(tmp_path)
    requested = []

    def get(url, path, max_bytes):
        requested.append(url)
        payload = json.dumps(expected).encode()
        assert len(payload) <= max_bytes
        path.write_bytes(payload)
        return len(payload)

    report = transport.read_schema_diagnostic(
        tmp_path,
        PRODUCER,
        SOURCE,
        KEY,
        "123",
        now=NOW,
        get=get,
    )
    assert report == expected
    assert len(requested) == 1
    assert f"/{transport.SCHEMA_DIAGNOSTIC_PATH}?" in requested[0]


def test_upload_checks_every_hash_rejects_extras_and_publishes_manifest_last(tmp_path):
    bundle = tmp_path / "bundle"
    _, content = write_bundle(bundle)
    full_ticket = dispatch_view(ticket(tmp_path), producer=True)
    uploaded = []

    def put(url, path, size):
        assert size == path.stat().st_size
        uploaded.append(path.relative_to(bundle).as_posix())

    result = transport.upload_directory(
        bundle,
        full_ticket,
        source=SOURCE,
        preparation_key=KEY,
        producer_run_id="123",
        put=put,
    )
    assert uploaded[-1] == "manifest.json"
    assert set(uploaded[:-1]) == set(content)
    assert result["uploaded"] == len(content) + 1

    (bundle / "unexpected.txt").write_text("must not upload")
    with pytest.raises(transport.PreparationTransportError, match="unexpected files"):
        transport.upload_directory(
            bundle,
            full_ticket,
            source=SOURCE,
            preparation_key=KEY,
            producer_run_id="123",
            put=put,
        )


def test_upload_rejects_hash_path_run_and_size_tampering(tmp_path):
    bundle = tmp_path / "bundle"
    manifest, _ = write_bundle(bundle)
    full_ticket = dispatch_view(ticket(tmp_path), producer=True)
    (bundle / "web.tar.gz").write_bytes(b"tampered")
    with pytest.raises(transport.PreparationTransportError, match="identity mismatch"):
        transport.upload_directory(
            bundle,
            full_ticket,
            source=SOURCE,
            preparation_key=KEY,
            producer_run_id="123",
            put=lambda *args: None,
        )
    manifest["artifacts"]["web.tar.gz"]["path"] = "../web.tar.gz"
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(transport.PreparationTransportError, match="path is invalid"):
        transport.upload_directory(
            bundle,
            full_ticket,
            source=SOURCE,
            preparation_key=KEY,
            producer_run_id="123",
            put=lambda *args: None,
        )
    manifest["artifacts"]["web.tar.gz"]["path"] = "web.tar.gz"
    manifest["producer_run_id"] = "wrong"
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(transport.PreparationTransportError, match="identity mismatch"):
        transport.upload_directory(
            bundle,
            full_ticket,
            source=SOURCE,
            preparation_key=KEY,
            producer_run_id="123",
            put=lambda *args: None,
        )

    manifest["producer_run_id"] = "123"
    manifest["artifacts"]["web.tar.gz"]["size"] = transport.MAX_OBJECT_BYTES + 1
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(transport.PreparationTransportError, match="manifest is invalid"):
        transport.upload_directory(
            bundle,
            full_ticket,
            source=SOURCE,
            preparation_key=KEY,
            producer_run_id="123",
            put=lambda *args: None,
        )


def test_manifest_rejects_declared_total_above_nine_gibibytes():
    digest = "0" * 64
    almost_four_gib = transport.MAX_OBJECT_BYTES - 1
    manifest = {
        "artifacts": {
            name: {"path": name, "size": almost_four_gib, "sha256": digest}
            for name in ("web.tar.gz", "translations.tar.gz", "cli.tar.gz")
        },
        "runtime_images": {"format_version": 2, "images": []},
    }
    with pytest.raises(
        transport.PreparationTransportError, match="exceeds transport limits"
    ):
        transport._manifest_references(manifest)


def test_download_fetches_manifest_first_then_verifies_bytes_and_run(tmp_path):
    producer_dir = tmp_path / "producer"
    manifest, content = write_bundle(producer_dir)
    objects = {**content, "manifest.json": json.dumps(manifest).encode()}
    compact = dispatch_view(ticket(tmp_path), producer=False)
    url_to_path = {
        record["get_url"]: relative for relative, record in compact["objects"].items()
    }
    requested = []

    def get(url, path, max_bytes, expected_size=None):
        relative = url_to_path[url]
        requested.append(relative)
        value = objects[relative]
        assert len(value) <= max_bytes
        if expected_size is not None:
            assert expected_size == len(value)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return len(value)

    destination = tmp_path / "download"
    result = transport.download_directory(
        destination,
        compact,
        source=SOURCE,
        preparation_key=KEY,
        prepared_run_id="123",
        get=get,
    )
    assert requested[0] == "manifest.json"
    assert result["downloaded"] == len(content) + 1
    assert "url" not in json.dumps(result).lower()
    assert (destination / "web.tar.gz").read_bytes() == content["web.tar.gz"]
    assert json.loads((destination / "manifest.json").read_text()) == manifest

    with pytest.raises(transport.PreparationTransportError, match="identity mismatch"):
        transport.download_directory(
            tmp_path / "wrong-run",
            compact,
            source=SOURCE,
            preparation_key=KEY,
            prepared_run_id="999",
            get=get,
        )

    altered = dict(objects)
    altered["web.tar.gz"] = b"bad bytes"

    def get_tampered(url, path, max_bytes, expected_size=None):
        value = altered[url_to_path[url]]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return len(value)

    with pytest.raises(transport.PreparationTransportError, match="digest mismatch"):
        transport.download_directory(
            tmp_path / "wrong-hash",
            compact,
            source=SOURCE,
            preparation_key=KEY,
            prepared_run_id="123",
            get=get_tampered,
        )


class FakeResponse:
    def __init__(self, status=302, body=b"redirected"):
        self.status = status
        self.body = body

    def read(self, size=-1):
        if not self.body:
            return b""
        if size < 0:
            value, self.body = self.body, b""
        else:
            value, self.body = self.body[:size], self.body[size:]
        return value

    def getheader(self, name):
        return None


class FakeConnection:
    instances = []

    def __init__(self, *args, **kwargs):
        self.headers = {}
        self.response = FakeResponse()
        self.__class__.instances.append(self)

    def putrequest(self, method, target):
        self.method = method

    def putheader(self, name, value):
        self.headers[name] = value

    def endheaders(self):
        pass

    def send(self, value):
        pass

    def request(self, method, target):
        self.method = method

    def getresponse(self):
        return self.response

    def close(self):
        pass


def test_http_transport_rejects_redirects_and_put_sends_private_acl(tmp_path):
    FakeConnection.instances.clear()
    source = tmp_path / "data"
    source.write_bytes(b"payload")
    secret_url = object_url("candidates/preparations/data", "put")
    with pytest.raises(transport.PreparationTransportError) as upload_error:
        transport.put_file(
            secret_url,
            source,
            source.stat().st_size,
            connection_factory=FakeConnection,
        )
    sent = FakeConnection.instances[-1]
    assert sent.headers["Content-Type"] == "application/octet-stream"
    assert sent.headers["x-amz-acl"] == "private"
    assert "X-Amz" not in str(upload_error.value)

    with pytest.raises(transport.PreparationTransportError) as download_error:
        transport.get_file(
            object_url("candidates/preparations/data", "get"),
            tmp_path / "output",
            100,
            connection_factory=FakeConnection,
        )
    assert not (tmp_path / "output").exists()
    assert "X-Amz" not in str(download_error.value)
