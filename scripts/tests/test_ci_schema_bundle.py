# contract-test-file: tooling

import gzip
import hashlib
import json

import pytest

from scripts import ci_schema_bundle as bundle


def test_schema_bundle_profile_runs_only_canonical_database_initializer():
    profile = bundle.producer_profile("a" * 40)
    assert set(profile["services"]) == set(bundle.SCHEMA_SERVICES)
    assert (
        profile["services"]["cms"]["environment"]["ADMIN_PASSWORD"]
        == bundle.PREPARED_SCHEMA_ADMIN_PASSWORD
    )
    assert not any("ports" in service for service in profile["services"].values())


def test_schema_bundle_rejects_non_github_hosted_runners(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "self-hosted")
    with pytest.raises(RuntimeError, match="GitHub-hosted"):
        bundle.require_runner()


def test_schema_bundle_uses_candidate_root_not_tooling_checkout(tmp_path, monkeypatch):
    candidate = tmp_path / "subject"
    monkeypatch.setenv("OPENMATES_CI_SOURCE_ROOT", str(candidate))
    assert bundle.source_root() == candidate.resolve()


def test_schema_bundle_sanitizes_application_and_transient_rows():
    sql = bundle.SANITIZE_SQL
    assert "tablename NOT LIKE 'directus" in sql
    assert "TRUNCATE TABLE directus_sessions" in sql
    assert "DELETE FROM directus_users" in sql
    assert "runtime@example.com" in sql


def test_schema_carrier_is_readable_by_postgres_entrypoint():
    dockerfile = (bundle.ROOT / "scripts/ci_schema_image.Dockerfile").read_text()
    assert "COPY --chmod=0444 openmates-ci-schema.sql.gz" in dockerfile
    assert "COPY --chmod=0444 openmates-ci-schema-manifest.json" in dockerfile
    assert "postgres:13-alpine@sha256:" in dockerfile
    assert bundle.SCHEMA_BUNDLE_FORMAT in dockerfile
    assert bundle.SCHEMA_RESTORE_SEMANTICS in dockerfile


def test_normalized_dump_ignores_only_pg_presentation_noise():
    first = (
        b"-- generated header\r\n\\restrict FirstRandom123\r\n\r\n"
        b"CREATE TABLE example ();  \r\n\\unrestrict FirstRandom123\r\n"
    )
    second = (
        b"-- other pg version\n\\restrict DifferentRandom456\n"
        b"CREATE TABLE example ();\n\\unrestrict DifferentRandom456\n"
    )
    assert bundle.normalized_dump(first) == (
        b"\\restrict <generated-key>\nCREATE TABLE example ();\n"
        b"\\unrestrict <generated-key>\n"
    )
    assert bundle.normalized_dump_sha256(first) == bundle.normalized_dump_sha256(second)
    copy_data = (
        b"COPY example (value) FROM stdin;\n--not-a-comment\n"
        b"\\restrict PayloadValue123\n\\.\n"
    )
    assert b"--not-a-comment" in bundle.normalized_dump(copy_data)
    assert b"\\restrict PayloadValue123" in bundle.normalized_dump(copy_data)


def test_schema_manifest_binds_dump_format_and_restore_semantics():
    dump = b"CREATE TABLE example ();\n"
    compressed = gzip.compress(dump, mtime=0)
    manifest = bundle.schema_manifest("a" * 40, dump, compressed)
    assert manifest["bundle_format"] == bundle.SCHEMA_BUNDLE_FORMAT
    assert manifest["restore_semantics"] == bundle.SCHEMA_RESTORE_SEMANTICS
    assert manifest["normalized_dump_sha256"] == hashlib.sha256(dump).hexdigest()
    assert manifest["compressed_dump_sha256"] == hashlib.sha256(compressed).hexdigest()


def test_verify_carrier_reads_dump_as_postgres_user(monkeypatch):
    manifest = {
        "bundle_format": bundle.SCHEMA_BUNDLE_FORMAT,
        "restore_semantics": bundle.SCHEMA_RESTORE_SEMANTICS,
        "normalized_dump_sha256": "a" * 64,
        "compressed_dump_sha256": "b" * 64,
    }
    calls = []

    class Result:
        stdout = (
            manifest["compressed_dump_sha256"].encode()
            + b"  /docker-entrypoint-initdb.d/20-openmates-schema.sql.gz\n"
            + json.dumps(manifest).encode()
        )

    monkeypatch.setattr(
        bundle,
        "run",
        lambda *args, **kwargs: calls.append(args) or Result(),
    )
    assert bundle.carrier_manifest("schema:test") == manifest
    assert "--user" in calls[0]
    assert "postgres" in calls[0]
    assert "gzip -t" in calls[0][-1]


def test_consumer_profiles_use_independent_projects_volumes_and_credentials():
    first = bundle.consumer_profile("a" * 40, "schema:test", "schema-one")
    second = bundle.consumer_profile("a" * 40, "schema:test", "schema-two")
    assert first["name"] != second["name"]
    assert first["volumes"] == second["volumes"]
    assert (
        first["services"]["cms-database"]["environment"]["POSTGRES_PASSWORD"]
        != second["services"]["cms-database"]["environment"]["POSTGRES_PASSWORD"]
    )
    for profile in (first, second):
        assert profile["services"]["cms-database"]["image"] == "schema:test"
        assert profile["services"]["cms-setup"]["environment"]["CI_PREPARED_SCHEMA"] == "1"


def test_verify_image_uses_two_fresh_consumers_and_cleans_each(tmp_path, monkeypatch):
    source = "a" * 40
    dump = b"CREATE TABLE example ();\n"
    manifest = bundle.schema_manifest(source, dump, gzip.compress(dump, mtime=0))
    profiles = []
    compose_calls = []

    class Result:
        stdout = source.encode()

    monkeypatch.setattr(bundle, "PRIVATE", tmp_path)
    monkeypatch.setattr(bundle, "require_runner", lambda: None)
    monkeypatch.setattr(bundle, "run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(bundle, "carrier_manifest", lambda image: manifest)
    monkeypatch.setattr(bundle, "write_profile", profiles.append)
    monkeypatch.setattr(bundle, "wait_for_restored_schema", lambda: None)
    monkeypatch.setattr(bundle, "database_dump", lambda: dump)
    monkeypatch.setattr(
        bundle,
        "compose",
        lambda *args, **kwargs: compose_calls.append(args),
    )

    evidence = bundle.verify_image("schema:test")

    assert len(profiles) == 2
    assert [profile["name"] for profile in profiles] == [
        "openmates-schema-verify-local-1",
        "openmates-schema-verify-local-2",
    ]
    passwords = {
        profile["services"]["cms"]["environment"]["ADMIN_PASSWORD"]
        for profile in profiles
    }
    assert len(passwords) == 2
    assert bundle.PREPARED_SCHEMA_ADMIN_PASSWORD not in passwords
    assert sum(call[:2] == ("down", "--volumes") for call in compose_calls) == 2
    assert len(evidence["consumers"]) == 2
