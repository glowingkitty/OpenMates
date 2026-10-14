# contract-test-file: tooling
"""Explicit old-producer runtime seeds; no network, Docker or real queue mutation."""

import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from scripts import ci_preparation_transport as transport, ci_runtime_images as runtime
from scripts.ci_coordinator import Queue, GitHub, enqueue_submission

SOURCE = "a" * 40
KEY = "b" * 64
NOW = dt.datetime(2026, 10, 14, 12, tzinfo=dt.timezone.utc)
KINDS = ["api", "cms", "setup", "schema"]


def ready_producer(queue):
    producer = queue.enqueue(
        "6d3f",
        SOURCE,
        [],
        "prepare",
        preparation={
            "key": KEY,
            "harness_commit": "c" * 40,
            "cli": True,
            "upload": False,
        },
    )
    with queue.connect() as db:
        db.execute(
            "UPDATE jobs SET state='success',run_id=38557114014 WHERE id=?",
            (producer["id"],),
        )
    return producer


def test_explicit_same_owner_ready_seed_only_for_backend_probe(tmp_path):
    queue = Queue(tmp_path / "logs/ci-coordinator/queue.sqlite3")
    seed = ready_producer(queue)
    job = queue.enqueue(
        "6d3f",
        "d" * 40,
        ["cli-recovery-discovery.spec.ts"],
        "backend-probe",
        runtime_seed_job=seed["id"],
    )
    identity = json.loads(job["runtime_seed"])
    assert identity == {
        "producer_id": seed["id"],
        "source": SOURCE,
        "preparation_key": KEY,
        "producer_run_id": "38557114014",
    }
    assert job["preparation_key"] == "" and job["preparation_id"] == ""
    assert "url" not in job["runtime_seed"]
    with pytest.raises(ValueError):
        queue.enqueue(
            "different-owner",
            "d" * 40,
            ["cli-recovery-discovery.spec.ts"],
            "backend-probe",
            runtime_seed_job=seed["id"],
        )
    with pytest.raises(ValueError):
        queue.enqueue(
            "6d3f", "d" * 40, ["first.spec.ts"], "e2e", runtime_seed_job=seed["id"]
        )
    with queue.connect() as db:
        db.execute("UPDATE jobs SET state='failure' WHERE id=?", (seed["id"],))
    with pytest.raises(ValueError):
        queue.enqueue(
            "6d3f",
            "d" * 40,
            ["cli-recovery-discovery.spec.ts"],
            "backend-probe",
            runtime_seed_job=seed["id"],
        )


def test_seed_submission_and_dispatch_pin_old_ticket_without_urls_in_queue(
    tmp_path, monkeypatch
):
    queue = Queue(tmp_path / "logs/ci-coordinator/queue.sqlite3")
    producer = ready_producer(queue)
    job = enqueue_submission(
        queue,
        "6d3f",
        "d" * 40,
        ["cli-recovery-discovery.spec.ts"],
        "backend-probe",
        runtime_seed_job=producer["id"],
    )[0]
    calls = []

    def ticket(root, values):
        calls.append(values)
        return json.dumps({"private": "PRIVATE_CANARY"})

    monkeypatch.setattr(transport, "dispatch_ticket", ticket)
    github = object.__new__(GitHub)
    github.root = tmp_path
    prepared = github.prepare_dispatch(job)
    assert calls == [
        {
            "mode": "backend-probe",
            "source": SOURCE,
            "preparation_key": KEY,
            "preparation_id": producer["id"],
        }
    ]
    assert (
        json.loads(prepared["_runtime_seed_transport"])["seed"]["producer_run_id"]
        == "38557114014"
    )
    assert "PRIVATE_CANARY" not in queue.status(job["id"])[0]["runtime_seed"]
    assert "PRIVATE_CANARY" not in job["runtime_seed"]


def ticket_and_seed(tmp_path):
    producer = "c" * 64

    def sign(objects, expiry):
        return {
            path: {
                verb: f"https://nbg1.your-objectstorage.com/{transport.BUCKET_NAME}/{key}?signature=PRIVATE_CANARY"
                for verb in ["get_url", "put_url"]
            }
            for path, key in objects.items()
        }

    stored = transport.get_or_create_ticket(
        tmp_path, producer, SOURCE, KEY, now=NOW, presign=sign
    )
    ticket = transport._dispatch_view(stored, producer=False)
    seed = {
        "producer_id": producer,
        "source": SOURCE,
        "preparation_key": KEY,
        "producer_run_id": "38557114014",
    }
    return ticket, seed


@pytest.mark.parametrize(
    "invalid", [None, "mode", "source", "run", "write-capability", "expired"]
)
def test_runtime_seed_event_is_exact_old_producer_read_only_and_redacted(
    tmp_path, invalid
):
    ticket, seed = ticket_and_seed(tmp_path)
    mode = "backend-probe"
    if invalid == "mode":
        mode = "prepare"
    if invalid == "source":
        seed["source"] = "d" * 40
    if invalid == "run":
        seed["producer_run_id"] = "-1"
    if invalid == "write-capability":
        ticket["objects"]["manifest.json"]["put_url"] = ticket["objects"][
            "manifest.json"
        ]["get_url"]
    if invalid == "expired":
        ticket["expires_at"] = (NOW - dt.timedelta(seconds=1)).isoformat()
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "inputs": {
                    "mode": mode,
                    "source_commit": "d" * 40,
                    "runtime_seed": json.dumps({"seed": seed, "ticket": ticket}),
                }
            }
        )
    )
    masked = []
    if invalid:
        with pytest.raises(transport.PreparationTransportError) as error:
            transport.runtime_seed_event(event_path=event, mask=masked.append, now=NOW)
        assert "PRIVATE_CANARY" not in str(error.value)
    else:
        loaded_ticket, loaded_seed = transport.runtime_seed_event(
            event_path=event, mask=masked.append, now=NOW
        )
        assert loaded_seed == seed and loaded_ticket == ticket
        assert masked


def runtime_bundle(ticket, seed):
    content = {
        name: b"web-output-must-not-download"
        for name in ["web.tar.gz", "web-preview.tar.gz", "translations.tar.gz"]
    }
    content.update({f"images/{kind}.tar": f"exact-{kind}".encode() for kind in KINDS})
    entries = [
        {
            "kind": kind,
            "runtime_key": hashlib.sha256(kind.encode()).hexdigest(),
            "archive_path": f"images/{kind}.tar",
            "archive_sha256": hashlib.sha256(content[f"images/{kind}.tar"]).hexdigest(),
            "archive_size": len(content[f"images/{kind}.tar"]),
            "image_ref": runtime.IMAGES[kind][1],
        }
        for kind in KINDS
    ]
    entries[-1].update(
        bundle_format=runtime.SCHEMA_BUNDLE_FORMAT,
        restore_semantics=runtime.SCHEMA_RESTORE_SEMANTICS,
    )
    manifest = {
        "source_commit": SOURCE,
        "preparation_key": KEY,
        "producer_run_id": seed["producer_run_id"],
        "artifacts": {
            name: {
                "path": name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for name, data in content.items()
            if not name.startswith("images/")
        },
        "runtime_images": {
            "format_version": runtime.MANIFEST_FORMAT_VERSION,
            "images": entries,
        },
    }
    content["manifest.json"] = json.dumps(manifest).encode()
    return content, manifest


@pytest.mark.parametrize(
    "invalid", [None, "current-key", "checksum", "schema-contract", "producer-run"]
)
def test_runtime_download_never_fetches_web_and_checks_new_keys_before_images(
    tmp_path, monkeypatch, invalid
):
    ticket, seed = ticket_and_seed(tmp_path)
    contents, manifest = runtime_bundle(ticket, seed)
    if invalid == "schema-contract":
        manifest["runtime_images"]["images"][-1]["restore_semantics"] = "wrong"
    if invalid == "producer-run":
        manifest["producer_run_id"] = "wrong"
    contents["manifest.json"] = json.dumps(manifest).encode()
    monkeypatch.setattr(
        runtime,
        "runtime_key",
        lambda root, kind: (
            "0" * 64
            if invalid == "current-key"
            else hashlib.sha256(kind.encode()).hexdigest()
        ),
    )
    fetched = []

    def get(url, path, max_bytes, **kwargs):
        name = next(
            name for name, value in ticket["objects"].items() if value["get_url"] == url
        )
        fetched.append(name)
        data = contents[name]
        if invalid == "checksum" and name == "images/cms.tar":
            data = b"corruption"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return len(data)

    destination = tmp_path / "download"
    if invalid:
        with pytest.raises((transport.PreparationTransportError, RuntimeError)):
            transport.download_directory(
                destination,
                ticket,
                source=SOURCE,
                preparation_key=KEY,
                prepared_run_id=seed["producer_run_id"],
                get=get,
                runtime_only=True,
                current_root=tmp_path,
            )
        if invalid != "checksum":
            assert fetched == ["manifest.json"]
    else:
        transport.download_directory(
            destination,
            ticket,
            source=SOURCE,
            preparation_key=KEY,
            prepared_run_id=seed["producer_run_id"],
            get=get,
            runtime_only=True,
            current_root=tmp_path,
        )
        assert set(fetched) == {
            "manifest.json",
            *[f"images/{kind}.tar" for kind in KINDS],
        }
        assert not (destination / "web.tar.gz").exists()
        assert (
            runtime.load_manifest(destination / "manifest.json")["images"]
            == manifest["runtime_images"]["images"]
        )


def test_workflow_seed_is_opt_in_backend_only_and_uses_existing_restore():
    path = Path(__file__).parents[2] / ".github/workflows/isolated-tests.yml"
    data = yaml.safe_load(path.read_text())
    inputs = data.get("on", data.get(True))["workflow_dispatch"]["inputs"]
    assert inputs["runtime_seed"]["default"] == ""
    steps = data["jobs"]["test"]["steps"]
    seed = next(
        step
        for step in steps
        if step.get("name") == "Download exact private backend runtime seed"
    )
    assert seed["if"] == "inputs.mode == 'backend-probe' && inputs.runtime_seed != ''"
    assert seed["timeout-minutes"] == 4
    images = next(step for step in steps if step.get("id") == "images")
    assert "--manifest test-results/ci-runtime-seed/manifest.json" in images["run"]
    assert "download-runtime" in seed["run"]
