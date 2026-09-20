#!/usr/bin/env python3
"""Build a synthetic Directus schema dump for fresh isolated CI databases.

The producer runs the canonical initializer against an empty database, removes
all application data and transient Directus rows, and writes a plain SQL gzip
consumed by the standard Postgres entrypoint. The published image is only an
artifact carrier: every test still creates its own database volume and rotates
the retained synthetic administrator password before API/worker startup.
"""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import select
import subprocess
import tempfile
import time

try:
    from scripts.ci_environment import (
        PREPARED_SCHEMA_ADMIN_PASSWORD,
        SCHEMA_BUNDLE_FORMAT,
        SCHEMA_RESTORE_SEMANTICS,
        compose_profile,
    )
except ModuleNotFoundError:  # Direct script execution puts scripts/ on sys.path.
    from ci_environment import (
        PREPARED_SCHEMA_ADMIN_PASSWORD,
        SCHEMA_BUNDLE_FORMAT,
        SCHEMA_RESTORE_SEMANTICS,
        compose_profile,
    )


def source_root() -> Path:
    return Path(
        os.environ.get(
            "OPENMATES_CI_SOURCE_ROOT", Path(__file__).resolve().parent.parent
        )
    ).resolve()


ROOT = source_root()
PRIVATE = ROOT / "test-results/ci-private"
COMPOSE_PATH = PRIVATE / "schema-compose.json"
OUTPUT = PRIVATE / "openmates-ci-schema.sql.gz"
MANIFEST = PRIVATE / "openmates-ci-schema-manifest.json"
SCHEMA_SERVICES = ("cms-database", "cms", "cms-setup")
SCHEMA_MANIFEST_PATH = "/usr/local/share/openmates/schema-manifest.json"
SCHEMA_DUMP_PATH = "/docker-entrypoint-initdb.d/20-openmates-schema.sql.gz"
MAX_CARRIER_DUMP_BYTES = 128 * 1024 * 1024
MAX_CARRIER_MANIFEST_BYTES = 64 * 1024
MAX_UNCOMPRESSED_SCHEMA_BYTES = 512 * 1024 * 1024
MAX_RESTORE_DIAGNOSTIC_BYTES = 128 * 1024
MAX_DIAGNOSTIC_SQL_LINE_BYTES = 4 * 1024
MAX_DIAGNOSTIC_MISMATCH_PAIRS = 8
MAX_DIAGNOSTIC_CROSS_LOCATIONS = 16
CARRIER_READ_TIMEOUT_SECONDS = 120
PG_DUMP_ARGS = (
    "pg_dump",
    "--no-owner",
    "--no-privileges",
    "--no-comments",
    "-U",
    "openmates",
    "-d",
    "openmates",
)
PG_DUMP_RESTRICT_GUARD = re.compile(br"^(\\(?:un)?restrict) [A-Za-z0-9]+$")


SANITIZE_SQL = r"""
DO $$
DECLARE item record;
BEGIN
  FOR item IN
    SELECT schemaname, tablename
    FROM pg_tables
    WHERE schemaname = 'public' AND tablename NOT LIKE 'directus\_%' ESCAPE '\'
  LOOP
    EXECUTE format('TRUNCATE TABLE %I.%I CASCADE', item.schemaname, item.tablename);
  END LOOP;
END $$;
TRUNCATE TABLE directus_sessions, directus_activity, directus_revisions,
  directus_notifications, directus_shares CASCADE;
DELETE FROM directus_users WHERE email <> 'runtime@example.com';
UPDATE directus_users
SET token = NULL, external_identifier = NULL, last_access = NULL, last_page = NULL
WHERE email = 'runtime@example.com';
"""


def require_runner() -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
    ):
        raise RuntimeError(
            "Schema bundles may only be produced on GitHub-hosted Actions runners"
        )


def schema_profile(source: str, *, prepared_admin: bool) -> dict:
    overrides = {"admin": PREPARED_SCHEMA_ADMIN_PASSWORD} if prepared_admin else None
    profile = compose_profile(source, credential_overrides=overrides)
    profile["services"] = {name: profile["services"][name] for name in SCHEMA_SERVICES}
    for service in profile["services"].values():
        service.pop("ports", None)
    return profile


def producer_profile(source: str) -> dict:
    return schema_profile(source, prepared_admin=True)


def consumer_profile(source: str, image: str, project_name: str) -> dict:
    """Return a fresh restore profile with a unique project and credentials."""
    profile = schema_profile(source, prepared_admin=False)
    profile["name"] = project_name
    profile["services"]["cms-database"]["image"] = image
    profile["services"]["cms-setup"]["environment"].update(
        CI_PREPARED_SCHEMA="1",
        CI_PREPARED_SCHEMA_ADMIN_PASSWORD=PREPARED_SCHEMA_ADMIN_PASSWORD,
    )
    return profile


def run(*args: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args),
        cwd=ROOT,
        input=input_bytes,
        capture_output=True,
        check=True,
        timeout=900,
    )


def compose(
    *args: str, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess:
    return run(
        "docker",
        "compose",
        "-f",
        str(COMPOSE_PATH),
        *args,
        input_bytes=input_bytes,
    )


def normalized_dump(dump: bytes) -> bytes:
    """Canonicalize random guards and unordered COPY rows without losing bytes."""
    lines = []
    copy_rows: list[bytes] | None = None
    # Split only on pg_dump's record delimiter. bytes.splitlines() would also
    # split CR/VT/FF bytes that can be meaningful inside multiline SQL bodies.
    for raw_line in dump.split(b"\n"):
        if copy_rows is not None:
            line = raw_line
            if line == b"\\.":
                # COPY TO has no ORDER BY for ordinary tables. Row order can
                # change with physical layout and is not database semantics;
                # sort exact encoded rows while retaining duplicates.
                lines.extend(sorted(copy_rows))
                lines.append(line)
                copy_rows = None
            else:
                copy_rows.append(line)
            continue
        line = raw_line
        guard = PG_DUMP_RESTRICT_GUARD.fullmatch(line)
        if guard:
            # Patched pg_dump versions generate a fresh random guard key for
            # each plain-text dump. Preserve the meta-command while removing
            # only that presentation-only randomness from equivalence hashes.
            line = guard.group(1) + b" <generated-key>"
        lines.append(line)
        if line.startswith(b"COPY ") and line.endswith(b" FROM stdin;"):
            copy_rows = []
    if copy_rows is not None:
        raise RuntimeError("Schema dump contains an unterminated COPY block")
    return b"\n".join(lines)


def normalized_dump_sha256(dump: bytes) -> str:
    return hashlib.sha256(normalized_dump(dump)).hexdigest()


def dump_units(dump: bytes) -> list[dict[str, str | int]]:
    """Return privacy-safe canonical units for structural diagnostics."""
    lines = normalized_dump(dump).split(b"\n")
    units: list[dict[str, str | int]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith(b"COPY ") and line.endswith(b" FROM stdin;"):
            rows = []
            index += 1
            while index < len(lines) and lines[index] != b"\\.":
                rows.append(lines[index])
                index += 1
            if index >= len(lines):  # normalized_dump already guards this.
                raise RuntimeError("Schema dump contains an unterminated COPY block")
            units.append(
                {
                    "kind": "copy",
                    "header_sha256": hashlib.sha256(line).hexdigest(),
                    "row_count": len(rows),
                    "rows_sha256": hashlib.sha256(b"\n".join(rows)).hexdigest(),
                }
            )
        else:
            first = line.split(maxsplit=1)[0].upper() if line else b""
            if first.startswith(b"\\"):
                category = "psql-meta"
            elif first in {
                b"ALTER",
                b"CREATE",
                b"DROP",
                b"GRANT",
                b"REVOKE",
                b"SELECT",
                b"SET",
            }:
                category = first.decode().lower()
            else:
                category = "sql"
            units.append(
                {
                    "kind": "sql",
                    "category": category,
                    "line_sha256": hashlib.sha256(line).hexdigest(),
                }
            )
        index += 1
    return units


def first_dump_difference(reference: bytes, actual: bytes) -> dict:
    expected_units = dump_units(reference)
    actual_units = dump_units(actual)
    for index, (expected, observed) in enumerate(
        zip(expected_units, actual_units, strict=False)
    ):
        if expected != observed:
            return {
                "unit_index": index,
                "expected": expected,
                "actual": observed,
            }
    return {
        "unit_index": min(len(expected_units), len(actual_units)),
        "expected_unit_count": len(expected_units),
        "actual_unit_count": len(actual_units),
    }


def _diagnostic_line(line: bytes, limit: int) -> dict[str, str | int | bool]:
    visible = line[:limit]
    return {
        "text": visible.decode("utf-8", errors="replace"),
        "sha256": hashlib.sha256(line).hexdigest(),
        "byte_length": len(line),
        "truncated": len(visible) != len(line),
    }


def _diagnostic_units(dump: bytes, line_limit: int) -> list[dict[str, object]]:
    """Pair safe unit summaries with raw SQL lines, never COPY row payloads."""
    lines = normalized_dump(dump).split(b"\n")
    summaries = dump_units(dump)
    units: list[dict[str, object]] = []
    line_index = 0
    summary_index = 0
    while line_index < len(lines):
        line = lines[line_index]
        summary = summaries[summary_index]
        if line.startswith(b"COPY ") and line.endswith(b" FROM stdin;"):
            # The summary contains only hashes/counts. Do not retain the COPY
            # header or inspect/serialize any payload row in the diagnostic.
            units.append({"summary": summary})
            line_index += 1
            while line_index < len(lines) and lines[line_index] != b"\\.":
                line_index += 1
        else:
            units.append(
                {"summary": summary, "sql": _diagnostic_line(line, line_limit)}
            )
        line_index += 1
        summary_index += 1
    return units


def _context_lines(
    units: list[dict[str, object]], center: int
) -> list[dict[str, object]]:
    sql_indexes = [index for index, unit in enumerate(units) if "sql" in unit]
    before = [index for index in sql_indexes if index < center][-2:]
    at = [center] if center < len(units) and "sql" in units[center] else []
    after = [index for index in sql_indexes if index > center][:2]
    return [
        {"unit_index": index, "line": units[index]["sql"]}
        for index in before + at + after
    ]


def _cross_locations(
    needle: dict[str, str | int] | None,
    units: list[dict[str, object]],
) -> dict[str, object]:
    if needle is None:
        return {"indexes": [], "truncated": False}
    matches = [
        index for index, unit in enumerate(units) if unit["summary"] == needle
    ]
    return {
        "indexes": matches[:MAX_DIAGNOSTIC_CROSS_LOCATIONS],
        "truncated": len(matches) > MAX_DIAGNOSTIC_CROSS_LOCATIONS,
    }


def restore_diagnostic(
    reference: bytes,
    actual: bytes,
    *,
    source_commit: str,
    consumer: int,
    line_limit: int = MAX_DIAGNOSTIC_SQL_LINE_BYTES,
) -> dict:
    """Build a private structural report with bounded non-COPY SQL context."""
    expected_units = _diagnostic_units(reference, line_limit)
    actual_units = _diagnostic_units(actual, line_limit)
    expected_summaries = [unit["summary"] for unit in expected_units]
    actual_summaries = [unit["summary"] for unit in actual_units]
    difference = first_dump_difference(reference, actual)
    first_index = int(difference["unit_index"])
    expected_first = (
        expected_summaries[first_index]
        if first_index < len(expected_summaries)
        else None
    )
    actual_first = (
        actual_summaries[first_index] if first_index < len(actual_summaries) else None
    )

    mismatched_sql_lines = []
    mismatch_sql_pair_count = 0
    for index in range(max(len(expected_units), len(actual_units))):
        expected = expected_units[index] if index < len(expected_units) else None
        observed = actual_units[index] if index < len(actual_units) else None
        if (expected or {}).get("summary") == (observed or {}).get("summary"):
            continue
        expected_sql = expected.get("sql") if expected else None
        actual_sql = observed.get("sql") if observed else None
        if expected_sql is None and actual_sql is None:
            continue
        mismatch_sql_pair_count += 1
        if len(mismatched_sql_lines) < MAX_DIAGNOSTIC_MISMATCH_PAIRS:
            mismatched_sql_lines.append(
                {
                    "unit_index": index,
                    "expected": expected_sql,
                    "actual": actual_sql,
                }
            )

    def multiset(units: list[dict[str, str | int]]) -> Counter[str]:
        return Counter(
            json.dumps(unit, sort_keys=True, separators=(",", ":")) for unit in units
        )

    return {
        "format_version": 1,
        "source_commit": source_commit,
        "preparation_key": os.environ.get("CI_PREPARATION_KEY", ""),
        "producer_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "consumer": consumer,
        "first_difference": difference,
        "unordered_unit_multiset_equal": multiset(expected_summaries)
        == multiset(actual_summaries),
        "first_unit_cross_locations": {
            "expected_in_actual": _cross_locations(expected_first, actual_units),
            "actual_in_expected": _cross_locations(actual_first, expected_units),
        },
        "sql_context": {
            "expected": _context_lines(expected_units, first_index),
            "actual": _context_lines(actual_units, first_index),
        },
        # Eight pairs are at most sixteen raw SQL lines. COPY units never have
        # an `sql` member and therefore cannot enter this list.
        "mismatched_sql_lines": mismatched_sql_lines,
        "mismatched_sql_lines_truncated": mismatch_sql_pair_count
        > MAX_DIAGNOSTIC_MISMATCH_PAIRS,
        "sql_line_byte_limit": line_limit,
        "size_truncated": line_limit < MAX_DIAGNOSTIC_SQL_LINE_BYTES,
    }


def write_restore_diagnostic(
    reference: bytes, actual: bytes, *, source_commit: str, consumer: int
) -> Path:
    """Write a mode-0600 diagnostic, reducing SQL excerpts to stay under 128 KiB."""
    line_limit = MAX_DIAGNOSTIC_SQL_LINE_BYTES
    while True:
        diagnostic = restore_diagnostic(
            reference,
            actual,
            source_commit=source_commit,
            consumer=consumer,
            line_limit=line_limit,
        )
        payload = json.dumps(
            diagnostic, indent=2, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        if len(payload) <= MAX_RESTORE_DIAGNOSTIC_BYTES:
            break
        if line_limit <= 64:
            raise RuntimeError("Schema restore diagnostic metadata exceeds size limit")
        line_limit = max(64, line_limit // 2)

    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    PRIVATE.chmod(0o700)
    path = PRIVATE / "schema-restore-diagnostic.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
    return path


def schema_manifest(source: str, dump: bytes, compressed: bytes) -> dict:
    return {
        "bundle_format": SCHEMA_BUNDLE_FORMAT,
        "restore_semantics": SCHEMA_RESTORE_SEMANTICS,
        "normalized_dump_sha256": normalized_dump_sha256(dump),
        "compressed_dump_sha256": hashlib.sha256(compressed).hexdigest(),
        "source_commit": source,
    }


def write_profile(profile: dict) -> None:
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    COMPOSE_PATH.write_text(json.dumps(profile))
    COMPOSE_PATH.chmod(0o600)


def database_dump() -> bytes:
    return compose("exec", "-T", "cms-database", *PG_DUMP_ARGS).stdout


def wait_for_restored_schema() -> None:
    """Wait past the entrypoint's temporary server until the schema is queryable."""
    for _ in range(90):
        try:
            # The official entrypoint's temporary initialization server listens
            # only on its Unix socket. TCP readiness proves init scripts have
            # finished and the final server has started; pg_isready needs no
            # database password and therefore keeps credentials out of argv.
            compose(
                "exec",
                "-T",
                "cms-database",
                "pg_isready",
                "-h",
                "127.0.0.1",
                "-U",
                "openmates",
            )
            result = compose(
                "exec",
                "-T",
                "cms-database",
                "psql",
                "-At",
                "-U",
                "openmates",
                "-d",
                "openmates",
                "-c",
                "SELECT to_regclass('public.directus_users') IS NOT NULL",
            )
        except subprocess.CalledProcessError:
            time.sleep(1)
            continue
        if result.stdout.decode().strip() == "t":
            return
        time.sleep(1)
    raise RuntimeError("Prepared schema did not become queryable")


def generate(output: Path = OUTPUT) -> Path:
    require_runner()
    source = run("git", "rev-parse", "HEAD").stdout.decode().strip()
    write_profile(producer_profile(source))
    try:
        compose(
            "up",
            "-d",
            "--no-build",
            "--wait",
            "--wait-timeout",
            "600",
            "cms-setup",
        )
        compose(
            "exec",
            "-T",
            "cms-database",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "openmates",
            "-d",
            "openmates",
            input_bytes=SANITIZE_SQL.encode(),
        )
        users = (
            compose(
                "exec",
                "-T",
                "cms-database",
                "psql",
                "-At",
                "-U",
                "openmates",
                "-d",
                "openmates",
                "-c",
                "SELECT email FROM directus_users ORDER BY email",
            )
            .stdout.decode()
            .splitlines()
        )
        if users != ["runtime@example.com"]:
            raise RuntimeError("Prepared schema contains unexpected Directus users")
        dump = database_dump()
        if b"ci-" in dump or b"@example.com" in dump.replace(
            b"runtime@example.com", b""
        ):
            raise RuntimeError("Prepared schema contains non-bootstrap account data")
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        compressed = gzip.compress(dump, compresslevel=9, mtime=0)
        output.write_bytes(compressed)
        output.chmod(0o600)
        MANIFEST.write_text(
            json.dumps(schema_manifest(source, dump, compressed), sort_keys=True)
        )
        MANIFEST.chmod(0o600)
        return output
    finally:
        compose("down", "--volumes", "--remove-orphans")


def carrier_cat_command(image: str, path: str) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--user",
        "postgres",
        "--entrypoint",
        "cat",
        image,
        path,
    ]


def safe_docker_diagnostic(error_output) -> str:
    error_output.seek(0)
    raw = error_output.read(513)
    truncated = len(raw) > 512
    text = " ".join(raw[:512].decode(errors="replace").split())
    text = re.sub(
        r"(?i)\b(password|token|secret)=\S+",
        r"\1=<redacted>",
        text,
    )
    if not text:
        return ""
    return f"; diagnostic={text}{'…' if truncated else ''}"


def read_carrier_file(image: str, path: str, name: str, max_bytes: int) -> bytes:
    """Read one carrier file as postgres with bounded output and diagnostics."""
    command = carrier_cat_command(image, path)
    with tempfile.TemporaryFile() as error_output:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=error_output,
        )
        if process.stdout is None:  # pragma: no cover - guaranteed by PIPE.
            process.kill()
            raise RuntimeError(f"Schema carrier {name} probe could not capture output")
        output = bytearray()
        deadline = time.monotonic() + CARRIER_READ_TIMEOUT_SECONDS
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    process.wait()
                    raise RuntimeError(f"Schema carrier {name} read timed out")
                readable, _, _ = select.select(
                    [process.stdout.fileno()], [], [], remaining
                )
                if not readable:
                    continue
                chunk = os.read(
                    process.stdout.fileno(),
                    min(64 * 1024, max_bytes + 1 - len(output)),
                )
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > max_bytes:
                    process.kill()
                    process.wait()
                    raise RuntimeError(
                        f"Schema carrier {name} exceeds its {max_bytes}-byte limit"
                    )
            returncode = process.wait(timeout=10)
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.kill()
                process.wait()
        if returncode:
            raise RuntimeError(
                f"Schema carrier {name} is not readable as postgres "
                f"(docker exit {returncode}{safe_docker_diagnostic(error_output)})"
            )
    return bytes(output)


def decompress_gzip_payload(compressed: bytes) -> bytes:
    output = bytearray()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as archive:
            while chunk := archive.read(1024 * 1024):
                output.extend(chunk)
                if len(output) > MAX_UNCOMPRESSED_SCHEMA_BYTES:
                    raise RuntimeError(
                        "Schema carrier dump exceeds its uncompressed verification limit"
                    )
    except (EOFError, gzip.BadGzipFile, OSError) as exc:
        raise RuntimeError("Schema carrier dump is not a valid gzip stream") from exc
    return bytes(output)


def verify_gzip_payload(compressed: bytes) -> None:
    decompress_gzip_payload(compressed)


def carrier_payload(image: str) -> tuple[dict, bytes]:
    compressed = read_carrier_file(
        image, SCHEMA_DUMP_PATH, "schema dump", MAX_CARRIER_DUMP_BYTES
    )
    dump = decompress_gzip_payload(compressed)
    manifest_json = read_carrier_file(
        image,
        SCHEMA_MANIFEST_PATH,
        "schema manifest",
        MAX_CARRIER_MANIFEST_BYTES,
    )
    try:
        manifest = json.loads(manifest_json)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Schema carrier manifest is not valid JSON") from exc
    compressed_sha256 = hashlib.sha256(compressed).hexdigest()
    if manifest.get("compressed_dump_sha256") != compressed_sha256:
        raise RuntimeError("Schema carrier compressed dump checksum mismatch")
    return manifest, dump


def carrier_manifest(image: str) -> dict:
    manifest, _ = carrier_payload(image)
    return manifest


def verify_manifest(manifest: dict) -> None:
    expected = {
        "bundle_format": SCHEMA_BUNDLE_FORMAT,
        "restore_semantics": SCHEMA_RESTORE_SEMANTICS,
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            raise RuntimeError(
                f"Schema carrier {field} mismatch: {manifest.get(field)!r} != {value!r}"
            )
    for field in ("normalized_dump_sha256", "compressed_dump_sha256"):
        value = manifest.get(field, "")
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise RuntimeError(f"Schema carrier has invalid {field}")


def verify_image(image: str) -> dict:
    """Restore-test a carrier twice without sharing volumes or credentials."""
    require_runner()
    source = run("git", "rev-parse", "HEAD").stdout.decode().strip()
    manifest, reference_dump = carrier_payload(image)
    verify_manifest(manifest)
    if normalized_dump_sha256(reference_dump) != manifest["normalized_dump_sha256"]:
        raise RuntimeError("Schema carrier manifest normalized fingerprint mismatch")
    if manifest.get("source_commit") != source:
        raise RuntimeError("Schema carrier was not built from the current producer source")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    credentials: set[str] = set()
    consumers = []
    for index in range(2):
        project = f"openmates-schema-verify-{run_id}-{index + 1}".lower()
        profile = consumer_profile(source, image, project)
        fresh_password = profile["services"]["cms"]["environment"]["ADMIN_PASSWORD"]
        if fresh_password == PREPARED_SCHEMA_ADMIN_PASSWORD or fresh_password in credentials:
            raise RuntimeError("Prepared schema consumer credentials are not fresh")
        credentials.add(fresh_password)
        write_profile(profile)
        try:
            compose(
                "up",
                "-d",
                "--no-build",
                "--wait",
                "--wait-timeout",
                "300",
                "cms-database",
            )
            wait_for_restored_schema()
            actual_dump = database_dump()
            actual = normalized_dump_sha256(actual_dump)
            if actual != manifest["normalized_dump_sha256"]:
                difference = first_dump_difference(reference_dump, actual_dump)
                write_restore_diagnostic(
                    reference_dump,
                    actual_dump,
                    source_commit=source,
                    consumer=index + 1,
                )
                raise RuntimeError(
                    "Prepared schema restore differs from the normalized cold initializer; "
                    "first_structural_difference="
                    + json.dumps(difference, sort_keys=True, separators=(",", ":"))
                )
            compose(
                "up",
                "-d",
                "--no-build",
                "--wait",
                "--wait-timeout",
                "600",
                "cms-setup",
            )
            consumers.append(
                {
                    "consumer": index + 1,
                    "fresh_volume": True,
                    "normalized_equivalent": True,
                    "fresh_auth_ready": True,
                }
            )
        finally:
            compose("down", "--volumes", "--remove-orphans")
    evidence = {
        "image": image,
        "bundle_format": SCHEMA_BUNDLE_FORMAT,
        "restore_semantics": SCHEMA_RESTORE_SEMANTICS,
        "consumers": consumers,
    }
    evidence_path = PRIVATE / "schema-image-verification.json"
    evidence_path.write_text(json.dumps(evidence, indent=2))
    evidence_path.chmod(0o600)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--output", type=Path, default=OUTPUT)
    verify_parser = subparsers.add_parser("verify-image")
    verify_parser.add_argument("image")
    # Preserve the original no-subcommand producer invocation during workflow cutover.
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.command == "verify-image":
        print(json.dumps(verify_image(args.image)))
        return 0
    print(generate(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
