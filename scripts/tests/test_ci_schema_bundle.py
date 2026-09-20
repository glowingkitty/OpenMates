# contract-test-file: tooling

import gzip
import hashlib
import json
import sys
import subprocess

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
    assert "chmod 0755 /docker-entrypoint-initdb.d" in dockerfile
    assert "/usr/local/share/openmates" in dockerfile
    assert "chmod 0444 /docker-entrypoint-initdb.d/20-openmates-schema.sql.gz" in dockerfile
    assert "postgres:13-alpine@sha256:" in dockerfile
    assert bundle.SCHEMA_BUNDLE_FORMAT in dockerfile
    assert bundle.SCHEMA_RESTORE_SEMANTICS in dockerfile


def test_normalized_dump_ignores_only_pg_presentation_noise():
    first = (
        b"\\restrict FirstRandom123\n\n"
        b"CREATE TABLE example ();\n\\unrestrict FirstRandom123\n"
    )
    second = (
        b"\\restrict DifferentRandom456\n\n"
        b"CREATE TABLE example ();\n\\unrestrict DifferentRandom456\n"
    )
    assert bundle.normalized_dump(first) == (
        b"\\restrict <generated-key>\n\nCREATE TABLE example ();\n"
        b"\\unrestrict <generated-key>\n"
    )
    assert bundle.normalized_dump_sha256(first) == bundle.normalized_dump_sha256(second)
    copy_data = (
        b"COPY example (value) FROM stdin;\n--not-a-comment\n"
        b"\\restrict PayloadValue123\n\\.\n"
    )
    assert b"--not-a-comment" in bundle.normalized_dump(copy_data)
    assert b"\\restrict PayloadValue123" in bundle.normalized_dump(copy_data)


def test_normalized_dump_sorts_only_copy_rows_and_preserves_exact_payload_bytes():
    prefix = b"SET statement_timeout = 0;\nCOPY public.items (value) FROM stdin;\n"
    first = prefix + b"second\t \nfirst\t\t\nfirst\t\n\\.\nSELECT 1;\n"
    reordered = prefix + b"first\t\nsecond\t \nfirst\t\t\n\\.\nSELECT 1;\n"
    assert bundle.normalized_dump(first) == bundle.normalized_dump(reordered)
    normalized = bundle.normalized_dump(first)
    assert b"first\t\n" in normalized
    assert b"first\t\t\n" in normalized
    assert b"second\t \n" in normalized

    missing_duplicate = prefix + b"first\t\nsecond\t \n\\.\nSELECT 1;\n"
    assert bundle.normalized_dump_sha256(first) != bundle.normalized_dump_sha256(
        missing_duplicate
    )
    reordered_sql = b"SELECT 1;\nSET statement_timeout = 0;\n"
    assert bundle.normalized_dump(b"SET statement_timeout = 0;\nSELECT 1;\n") != (
        bundle.normalized_dump(reordered_sql)
    )
    assert bundle.normalized_dump(b"SELECT 'value ';\n") != bundle.normalized_dump(
        b"SELECT 'value '; \n"
    )
    assert b"-- function-body comment" in bundle.normalized_dump(
        b"CREATE FUNCTION example() RETURNS void AS $$\n"
        b"-- function-body comment\nBEGIN NULL; END;\n$$ LANGUAGE plpgsql;\n"
    )


def test_normalized_dump_preserves_multiline_blank_and_control_whitespace():
    dump = (
        b"CREATE FUNCTION example() RETURNS text AS $$\n"
        b"first line\n\n \t\nsecond\vline\fform\rcarriage\n"
        b"$$ LANGUAGE sql;\n"
    )
    assert bundle.normalized_dump(dump) == dump


def test_dump_difference_reports_hashes_and_counts_without_payload_values():
    reference = (
        b"COPY public.directus_users (password) FROM stdin;\n"
        b"private-admin-hash-one\n\\.\n"
    )
    actual = (
        b"COPY public.directus_users (password) FROM stdin;\n"
        b"private-admin-hash-two\n\\.\n"
    )
    difference = bundle.first_dump_difference(reference, actual)
    serialized = json.dumps(difference)
    assert difference["expected"]["kind"] == "copy"
    assert difference["expected"]["row_count"] == 1
    assert "rows_sha256" in difference["actual"]
    assert "private-admin" not in serialized
    assert "directus_users" not in serialized


def test_schema_manifest_binds_dump_format_and_restore_semantics():
    dump = b"CREATE TABLE example ();\n"
    compressed = gzip.compress(dump, mtime=0)
    manifest = bundle.schema_manifest("a" * 40, dump, compressed)
    assert manifest["bundle_format"] == bundle.SCHEMA_BUNDLE_FORMAT
    assert manifest["restore_semantics"] == bundle.SCHEMA_RESTORE_SEMANTICS
    assert manifest["normalized_dump_sha256"] == hashlib.sha256(dump).hexdigest()
    assert manifest["compressed_dump_sha256"] == hashlib.sha256(compressed).hexdigest()


def test_verify_carrier_reads_dump_as_postgres_user(monkeypatch):
    compressed = gzip.compress(b"SELECT 1;\n", mtime=0)
    manifest = {
        "bundle_format": bundle.SCHEMA_BUNDLE_FORMAT,
        "restore_semantics": bundle.SCHEMA_RESTORE_SEMANTICS,
        "normalized_dump_sha256": "a" * 64,
        "compressed_dump_sha256": hashlib.sha256(compressed).hexdigest(),
    }
    calls = []
    monkeypatch.setattr(
        bundle,
        "read_carrier_file",
        lambda image, path, name, limit: calls.append((image, path, name, limit))
        or (
            compressed
            if path == bundle.SCHEMA_DUMP_PATH
            else json.dumps(manifest).encode()
        ),
    )
    assert bundle.carrier_manifest("schema:test") == manifest
    assert [call[2] for call in calls] == ["schema dump", "schema manifest"]
    command = bundle.carrier_cat_command("schema:test", bundle.SCHEMA_DUMP_PATH)
    assert command[command.index("--user") + 1] == "postgres"
    assert command[command.index("--entrypoint") + 1] == "cat"
    assert "--network" in command and "--read-only" in command


def test_carrier_file_read_is_bounded_and_names_failed_probe(monkeypatch):
    monkeypatch.setattr(
        bundle,
        "carrier_cat_command",
        lambda image, path: [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'x' * 5)",
        ],
    )
    with pytest.raises(RuntimeError, match="schema dump exceeds its 4-byte limit"):
        bundle.read_carrier_file("schema:test", "/dump", "schema dump", 4)

    monkeypatch.setattr(
        bundle,
        "carrier_cat_command",
        lambda image, path: [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('permission denied token=private-value'); sys.exit(3)",
        ],
    )
    with pytest.raises(RuntimeError, match="schema manifest is not readable") as error:
        bundle.read_carrier_file("schema:test", "/manifest", "schema manifest", 64)
    assert "permission denied" in str(error.value)
    assert "private-value" not in str(error.value)


def test_carrier_gzip_validation_is_host_side_and_bounded():
    with pytest.raises(RuntimeError, match="not a valid gzip"):
        bundle.verify_gzip_payload(b"not-gzip")


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


def test_restore_readiness_rejects_temporary_socket_only_server(monkeypatch):
    calls = []
    tcp_attempts = 0

    class Result:
        stdout = b"t\n"

    def compose(*args, **kwargs):
        nonlocal tcp_attempts
        calls.append(args)
        if "pg_isready" in args:
            tcp_attempts += 1
            if tcp_attempts == 1:
                raise subprocess.CalledProcessError(2, args)
            return Result()
        assert "psql" in args
        return Result()

    delays = []
    monkeypatch.setattr(bundle, "compose", compose)
    monkeypatch.setattr(bundle.time, "sleep", delays.append)

    bundle.wait_for_restored_schema()

    assert calls[0][3:] == (
        "pg_isready",
        "-h",
        "127.0.0.1",
        "-U",
        "openmates",
    )
    assert "psql" not in calls[0]
    assert "pg_isready" in calls[1]
    assert "psql" in calls[2]
    assert delays == [1]
    assert all("PGPASSWORD" not in argument for call in calls for argument in call)


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
    monkeypatch.setattr(
        bundle, "carrier_payload", lambda image: (manifest, dump)
    )
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


def test_verify_image_rejects_manifest_normalized_fingerprint_mismatch(monkeypatch):
    source = "a" * 40
    dump = b"SELECT 1;\n"
    manifest = bundle.schema_manifest(source, dump, gzip.compress(dump, mtime=0))
    manifest["normalized_dump_sha256"] = "0" * 64

    class Result:
        stdout = source.encode()

    monkeypatch.setattr(bundle, "require_runner", lambda: None)
    monkeypatch.setattr(bundle, "run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(bundle, "carrier_payload", lambda image: (manifest, dump))
    with pytest.raises(RuntimeError, match="manifest normalized fingerprint mismatch"):
        bundle.verify_image("schema:test")
