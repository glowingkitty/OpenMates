#!/usr/bin/env python3
"""Fail SDK publication on untracked APIs, unsupported parity, or failed real fixtures.

The matrix describes reviewed semantics; source inventory and executable library
runners independently verify its API coverage and conformance. Migration checks
report honest gaps. --release never waives them. No account or network is used.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("rust", "npm", "python")
MATRIX = "config/sdk-capabilities.json"
SCHEMA = "config/sdk-capabilities.schema.json"
RUNNERS = {
    "npm": ["node", "tests/sdk-conformance/runners/npm.mjs"],
    "python": [sys.executable, "tests/sdk-conformance/runners/python.py"],
    "rust": [
        "cargo",
        "run",
        "--quiet",
        "--locked",
        "--manifest-path",
        "packages/openmates-rust/Cargo.toml",
        "--example",
        "sdk-conformance",
        "--",
    ],
}
RUST_SESSION_RUNNER = [
    "cargo",
    "run",
    "--quiet",
    "--locked",
    "--manifest-path",
    "packages/openmates-session-bindings/Cargo.toml",
    "--example",
    "sdk-conformance",
    "--",
]
ADAPTER_OVERRIDES = {
    ("rust", "session.project-source-authoring.v1"): [
        *RUST_SESSION_RUNNER[:-2], "session-project-sources-conformance", "--",
    ],
    ("npm", "session.project-source-authoring.v1"): [
        "node", "tests/sdk-conformance/runners/session-project-sources.mjs",
    ],
    ("python", "session.project-source-authoring.v1"): [
        sys.executable, "tests/sdk-conformance/runners/session-project-sources.py",
    ],
    ("rust", "session.project-task-watch.v1"): [
        *RUST_SESSION_RUNNER[:-2],
        "session-project-task-watch-conformance",
        "--",
    ],
    ("npm", "session.project-task-watch.v1"): [
        "node", "tests/sdk-conformance/runners/session-project-task-watch.mjs",
    ],
    ("python", "session.project-task-watch.v1"): [
        sys.executable, "tests/sdk-conformance/runners/session-project-task-watch.py",
    ],
    ("rust", "local.privacy.v1"): [
        *RUST_SESSION_RUNNER[:-2],
        "privacy-conformance",
        "--",
    ],
    ("npm", "local.privacy.v1"): [
        "node",
        "tests/sdk-conformance/runners/privacy.mjs",
    ],
    ("python", "local.privacy.v1"): [
        sys.executable,
        "tests/sdk-conformance/runners/privacy.py",
    ],
    ("rust", "local.task-order.v1"): [
        *RUST_SESSION_RUNNER[:-2],
        "task-order-conformance",
        "--",
    ],
    ("npm", "local.task-order.v1"): [
        "node",
        "tests/sdk-conformance/runners/task-order.mjs",
    ],
    ("python", "local.task-order.v1"): [
        sys.executable,
        "tests/sdk-conformance/runners/task-order.py",
    ],
    ("rust", "session.anonymous-stream.v1"): [
        *RUST_SESSION_RUNNER[:-2],
        "session-anonymous-conformance",
        "--",
    ],
    ("npm", "session.anonymous-stream.v1"): [
        "node",
        "tests/sdk-conformance/runners/session-anonymous.mjs",
    ],
    ("python", "session.anonymous-stream.v1"): [
        sys.executable,
        "tests/sdk-conformance/runners/session-anonymous.py",
    ],
    ("rust", "session.plans-workflows.v1"): [
        *RUST_SESSION_RUNNER[:-2],
        "session-plans-workflows-conformance",
        "--",
    ],
    ("npm", "session.plans-workflows.v1"): [
        "node",
        "tests/sdk-conformance/runners/session-plans-workflows.mjs",
    ],
    ("python", "session.plans-workflows.v1"): [
        sys.executable,
        "tests/sdk-conformance/runners/session-plans-workflows.py",
    ],
    ("rust", "session.work-crud.v1"): [
        *RUST_SESSION_RUNNER[:-2],
        "session-work-conformance",
        "--",
    ],
    ("npm", "session.work-crud.v1"): [
        "node",
        "tests/sdk-conformance/runners/session-work.mjs",
    ],
    ("python", "session.work-crud.v1"): [
        sys.executable,
        "tests/sdk-conformance/runners/session-work.py",
    ],
    ("rust", "session.project-items.v1"): [
        *RUST_SESSION_RUNNER[:-2],
        "session-project-items-conformance",
        "--",
    ],
    ("npm", "session.project-items.v1"): [
        "node",
        "tests/sdk-conformance/runners/session-project-items.mjs",
    ],
    ("python", "session.project-items.v1"): [
        sys.executable,
        "tests/sdk-conformance/runners/session-project-items.py",
    ],
    ("rust", "protocol.project-create.v1"): [
        *RUNNERS["rust"][:-2],
        "project-create-conformance",
        "--",
    ],
    ("npm", "protocol.project-create.v1"): [
        "node",
        "tests/sdk-conformance/runners/project-create.mjs",
    ],
    ("python", "protocol.project-create.v1"): [
        sys.executable,
        "tests/sdk-conformance/runners/project-create.py",
    ],
    ("rust", "session.native-boundary.v1"): RUST_SESSION_RUNNER,
    ("rust", "session.password-totp-rotation.v1"): [
        *RUST_SESSION_RUNNER[:-2],
        "session-auth-conformance",
        "--",
    ],
    ("npm", "session.password-totp-rotation.v1"): [
        "node",
        "tests/sdk-conformance/runners/session-auth.mjs",
    ],
    ("python", "session.password-totp-rotation.v1"): [
        sys.executable,
        "tests/sdk-conformance/runners/session-auth.py",
    ],
    ("rust", "session.recovery-replay.v1"): [
        *RUST_SESSION_RUNNER[:-2],
        "session-recovery-conformance",
        "--",
    ],
    ("npm", "session.recovery-replay.v1"): [
        "node",
        "tests/sdk-conformance/runners/session-recovery.mjs",
    ],
    ("python", "session.recovery-replay.v1"): [
        sys.executable,
        "tests/sdk-conformance/runners/session-recovery.py",
    ],
}

ADAPTER_OVERRIDES[("rust", "session.chat-change-monitor.v1")] = [*RUST_SESSION_RUNNER[:-2], "session-chat-change-monitor-conformance", "--"]
ADAPTER_OVERRIDES[("npm", "session.chat-change-monitor.v1")] = ["node", "tests/sdk-conformance/runners/session-chat-change-monitor.mjs"]
ADAPTER_OVERRIDES[("python", "session.chat-change-monitor.v1")] = [sys.executable, "tests/sdk-conformance/runners/session-chat-change-monitor.py"]
ADAPTER_OVERRIDES[("rust", "session.foreground-completion-recovery.v1")] = [*RUST_SESSION_RUNNER[:-2], "session-foreground-completion-recovery-conformance", "--"]
ADAPTER_OVERRIDES[("npm", "session.foreground-completion-recovery.v1")] = ["node", "tests/sdk-conformance/runners/session-foreground-completion-recovery.mjs"]
ADAPTER_OVERRIDES[("python", "session.foreground-completion-recovery.v1")] = [sys.executable, "tests/sdk-conformance/runners/session-foreground-completion-recovery.py"]


ADAPTER_OVERRIDES[("rust", "session.message-window.v1")] = [*RUST_SESSION_RUNNER[:-2], "session-message-window-conformance", "--"]
ADAPTER_OVERRIDES[("npm", "session.message-window.v1")] = ["node", "tests/sdk-conformance/runners/session-message-window.mjs"]
ADAPTER_OVERRIDES[("python", "session.message-window.v1")] = [sys.executable, "tests/sdk-conformance/runners/session-message-window.py"]


ADAPTER_OVERRIDES[("rust", "session.saved-chat-read.v1")] = [*RUST_SESSION_RUNNER[:-2], "session-saved-chat-read-conformance", "--"]
ADAPTER_OVERRIDES[("npm", "session.saved-chat-read.v1")] = ["node", "tests/sdk-conformance/runners/session-saved-chat-read.mjs"]
ADAPTER_OVERRIDES[("python", "session.saved-chat-read.v1")] = [sys.executable, "tests/sdk-conformance/runners/session-saved-chat-read.py"]

ADAPTER_OVERRIDES[("rust", "session.embeds.version-content.v1")] = [*RUST_SESSION_RUNNER[:-2], "session-embed-version-content-conformance", "--"]
ADAPTER_OVERRIDES[("npm", "session.embeds.version-content.v1")] = ["node", "tests/sdk-conformance/runners/session-embed-version-content.mjs"]
ADAPTER_OVERRIDES[("python", "session.embeds.version-content.v1")] = [sys.executable, "tests/sdk-conformance/runners/session-embed-version-content.py"]

# Cookie Personal draft reads use fixed native-backed library adapters.
ADAPTER_OVERRIDES[("rust", "session.drafts.v1")] = [*RUST_SESSION_RUNNER[:-2], "session-drafts-conformance", "--"]
ADAPTER_OVERRIDES[("npm", "session.drafts.v1")] = ["node", "tests/sdk-conformance/runners/session-drafts.mjs"]
ADAPTER_OVERRIDES[("python", "session.drafts.v1")] = [sys.executable, "tests/sdk-conformance/runners/session-drafts.py"]

# Fixed direct-library adapters; matrix metadata never supplies commands.
for _identity, _stem, _npm in (
    ("sdk.history", "sdk-api-key-history", "sdk-api-key-history"),
    ("sdk.drafts", "sdk-api-key-drafts", "api-key-drafts"),
    ("sdk.docs", "sdk-api-key-docs", "sdk-api-key-docs"),
    ("sdk.wikipedia", "sdk-api-key-wikipedia", "sdk-api-key-wikipedia"),
    ("sdk.embeds", "sdk-api-key-embeds", "sdk-api-key-embeds"),
    ("sdk.embeds.family", "sdk-api-key-embeds-family", "sdk-api-key-embeds-family"),
    ("sdk.embeds.version-content", "sdk-embed-version-content", "sdk-embed-version-content"),
):
    ADAPTER_OVERRIDES[("rust", _identity)] = [
        *RUNNERS["rust"][:-2], _stem + "-conformance", "--",
    ]
    ADAPTER_OVERRIDES[("npm", _identity)] = [
        "node", "--experimental-strip-types", "tests/sdk-conformance/runners/" + _npm + ".mjs",
    ]
    ADAPTER_OVERRIDES[("python", _identity)] = [
        sys.executable, "tests/sdk-conformance/runners/" + _npm + ".py",
    ]

# Required direct-library cache adapters; conformance schedules checks, while
# partial support and remaining gaps continue to block SDK publication.
ADAPTER_OVERRIDES[("rust", "session.cache-preferred-settlement.v1")] = [*RUST_SESSION_RUNNER[:-2], "session-cache-preferred-settlement-conformance", "--"]
ADAPTER_OVERRIDES[("npm", "session.cache-preferred-settlement.v1")] = ["node", "tests/sdk-conformance/runners/session-cache-preferred-settlement.mjs"]
ADAPTER_OVERRIDES[("python", "session.cache-preferred-settlement.v1")] = [sys.executable, "tests/sdk-conformance/runners/session-cache-preferred-settlement.py"]

# Explicit fixed adapters for the required-partial first-page family only.
ADAPTER_OVERRIDES[("rust", "session.chat-first-page-continuation.v1")] = [*RUST_SESSION_RUNNER[:-2], "session-chat-first-page-continuation-conformance", "--"]
ADAPTER_OVERRIDES[("npm", "session.chat-first-page-continuation.v1")] = ["node", "tests/sdk-conformance/runners/session-chat-first-page-continuation.mjs"]
ADAPTER_OVERRIDES[("python", "session.chat-first-page-continuation.v1")] = [sys.executable, "tests/sdk-conformance/runners/session-chat-first-page-continuation.py"]

FIXTURE_SCHEMAS = {
    "tests/sdk-conformance/fixtures/session-work.json":
        "tests/sdk-conformance/schemas/session-work.schema.json",
    "tests/sdk-conformance/fixtures/session-foreground-completion-recovery.json":
        "tests/sdk-conformance/schemas/session-foreground-completion-recovery.schema.json",
    "tests/sdk-conformance/fixtures/session-chat-first-page-continuation.json":
        "tests/sdk-conformance/schemas/session-chat-first-page-continuation.schema.json",
    "tests/sdk-conformance/fixtures/session-cache-preferred-settlement.json":
        "tests/sdk-conformance/schemas/session-cache-preferred-settlement.schema.json",
    "tests/sdk-conformance/fixtures/session-embed-version-content.json":
        "tests/sdk-conformance/schemas/session-embed-version-content.schema.json",
    "tests/sdk-conformance/fixtures/sdk-embed-version-content.json":
        "tests/sdk-conformance/schemas/sdk-embed-version-content.schema.json",
    "tests/sdk-conformance/fixtures/session-drafts.json":
        "tests/sdk-conformance/schemas/session-drafts.schema.json",
    "tests/sdk-conformance/fixtures/sdk-api-key-docs.json":
        "tests/sdk-conformance/schemas/sdk-api-key-docs-fixture.schema.json",
    "tests/sdk-conformance/fixtures/sdk-api-key-wikipedia.json":
        "tests/sdk-conformance/schemas/sdk-api-key-wikipedia-fixture.schema.json",
    "tests/sdk-conformance/fixtures/sdk-api-key-embeds.json":
        "tests/sdk-conformance/fixtures/sdk-api-key-embeds.schema.json",
    "tests/sdk-conformance/fixtures/sdk-api-key-embeds-family.json":
        "tests/sdk-conformance/fixtures/sdk-api-key-embeds-family.schema.json",
    "tests/sdk-conformance/fixtures/sdk-api-key-history.json":
        "tests/sdk-conformance/fixtures/sdk-api-key-history.schema.json",
    "tests/sdk-conformance/fixtures/sdk-api-key-drafts.json":
        "tests/sdk-conformance/schemas/sdk-api-key-drafts-fixture.schema.json",
}


def validate_fixture_document(name: str, document: dict, root: Path = ROOT) -> None:
    schema_name = FIXTURE_SCHEMAS.get(name)
    if schema_name is not None:
        schema = json.loads(repo_file(schema_name, root).read_bytes())
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(document)


def repo_file(value: str, root: Path = ROOT) -> Path:
    candidate = (root / value).resolve()
    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
        raise ValueError("Missing or non-repository evidence: " + value)
    return candidate


def validate_matrix(matrix: dict, inventory: dict, root: Path = ROOT) -> list[str]:
    """API inventory is discovered independently of matrix support declarations."""
    schema = json.loads((root / SCHEMA).read_text())
    jsonschema.Draft202012Validator(schema).validate(matrix)
    if set(inventory) != set(LANGUAGES):
        raise ValueError(
            "Inventory must independently discover exactly Rust, npm and Python APIs"
        )
    seen_ids: set[str] = set()
    covered = {language: set() for language in LANGUAGES}
    gaps = []
    for capability in matrix["capabilities"]:
        identity = capability["id"]
        if identity in seen_ids:
            raise ValueError("Duplicate capability: " + identity)
        seen_ids.add(identity)
        for language in LANGUAGES:
            support = capability["languages"][language]
            for api in support["api"]:
                if api in covered[language]:
                    raise ValueError(f"API classified twice: {language}:{api}")
                covered[language].add(api)
            for evidence in support["evidence"]:
                file = repo_file(evidence.split("::", 1)[0], root)
                executable_runner = file.relative_to(root).as_posix() in {
                    "packages/openmates-rust/examples/sdk-conformance.rs",
                    "packages/openmates-rust/src/client/cached_view_tests.rs",
                    "packages/openmates-rust/src/client/browser_local_read_glue_tests.rs",
                    "frontend/packages/openmates-tui-native/src/runtime_live_tests.rs",
                    "frontend/packages/openmates-tui-native/src/runtime_store.rs",
                    "packages/openmates-rust/examples/sdk-api-key-history-conformance.rs",
                    "packages/openmates-rust/examples/sdk-api-key-drafts-conformance.rs",
                    "packages/openmates-rust/examples/sdk-api-key-docs-conformance.rs",
                    "packages/openmates-rust/examples/sdk-api-key-wikipedia-conformance.rs",
                    "packages/openmates-rust/examples/sdk-api-key-embeds-conformance.rs",
                    "packages/openmates-rust/examples/sdk-api-key-embeds-family-conformance.rs",
                    "packages/openmates-rust/examples/sdk-embed-version-content-conformance.rs",
                    "packages/openmates-rust/examples/project-create-conformance.rs",
                    "packages/openmates-session-bindings/examples/sdk-conformance.rs",
                    "packages/openmates-session-bindings/examples/session-auth-conformance.rs",
                    "packages/openmates-session-bindings/examples/session-message-window-conformance.rs",
                    "packages/openmates-session-bindings/examples/session-saved-chat-read-conformance.rs",
                    "packages/openmates-session-bindings/examples/session-cache-preferred-settlement-conformance.rs",
                    "packages/openmates-session-bindings/examples/session-chat-first-page-continuation-conformance.rs",
                    "packages/openmates-session-bindings/examples/session-drafts-conformance.rs",
                    "packages/openmates-session-bindings/examples/session-embed-version-content-conformance.rs",
                    "packages/openmates-session-bindings/examples/session-recovery-conformance.rs",
                    "packages/openmates-session-bindings/examples/session-chat-change-monitor-conformance.rs",
                    "packages/openmates-session-bindings/examples/session-foreground-completion-recovery-conformance.rs",
                    "packages/openmates-session-bindings/examples/session-work-conformance.rs",
                    "packages/openmates-session-bindings/examples/session-project-items-conformance.rs",
                    "packages/openmates-session-bindings/examples/task-order-conformance.rs",
                    "packages/openmates-session-bindings/examples/privacy-conformance.rs",
                    "packages/openmates-session-bindings/examples/session-project-task-watch-conformance.rs",
                    "packages/openmates-session-bindings/examples/session-project-sources-conformance.rs",
                    "packages/openmates-session-bindings/examples/session-plans-workflows-conformance.rs",
                    "packages/openmates-session-bindings/examples/session-anonymous-conformance.rs",
                }
                if (
                    "tests" not in file.relative_to(root).parts
                    and not executable_runner
                ) or file.suffix not in {
                    ".py",
                    ".rs",
                    ".ts",
                    ".mjs",
                }:
                    raise ValueError(
                        "Conformance evidence must be executable test code: " + evidence
                    )
            if support["status"] != "implemented":
                gaps.append(
                    f"{identity} [{language}] {support['status']}: "
                    + "; ".join(support["gaps"])
                )
    for language in LANGUAGES:
        actual = inventory.get(language)
        if (
            not isinstance(actual, list)
            or len(set(actual)) != len(actual)
            or not all(isinstance(name, str) and name for name in actual)
        ):
            raise ValueError("Invalid discovered inventory: " + language)
        missing = set(actual) - covered[language]
        stale = covered[language] - set(actual)
        if missing or stale:
            raise ValueError(
                f"Public API inventory drift for {language}: unclassified={sorted(missing)}, removed={sorted(stale)}"
            )
    return gaps


def discover_inventory(root: Path = ROOT) -> dict:
    command = [sys.executable, "tests/sdk-conformance/inventory.py"]
    result = subprocess.run(
        command, cwd=root, check=True, capture_output=True, text=True, timeout=120
    )
    return json.loads(result.stdout)


def validate_result(
    result: dict,
    identity: str,
    language: str,
    fixture_hash: str,
    expected_ids: set[str] | None = None,
) -> None:
    expected = {
        "capability": identity,
        "language": language,
        "status": "passed",
        "fixtureSha256": fixture_hash,
    }
    for key, value in expected.items():
        if result.get(key) != value:
            raise ValueError(
                f"Conformance runner mismatch {identity}/{language}: {key}"
            )
    assertions = result.get("results")
    if not isinstance(assertions, list) or not assertions:
        raise ValueError(
            f"No implementation assertions executed: {identity}/{language}"
        )
    if not all(
        isinstance(assertion, dict)
        and assertion.get("status") == "passed"
        and assertion.get("id")
        for assertion in assertions
    ):
        raise ValueError(
            f"Failed or unclassified implementation assertion: {identity}/{language}"
        )

    actual_ids = [assertion["id"] for assertion in assertions]
    if len(actual_ids) != len(set(actual_ids)):
        raise ValueError(f"Duplicate implementation assertions: {identity}/{language}")
    if expected_ids is not None and set(actual_ids) != expected_ids:
        raise ValueError(
            f"Shared fixture cases not fully executed: {identity}/{language}"
        )


def validate_fixture_error_oracles(suites: dict) -> None:
    """Check typed expectation fields, never arbitrary input/metadata payloads."""
    # BindingError uses invalid_argument; the direct Rust SDK uses invalid.
    # Stable public error vocabulary; operation-specific unavailable
    # reasons remain assertions owned by their actual library runners.
    codes = {
        "invalid_argument", "invalid", "crypto", "authentication", "two_factor_required",
        "signup_required", "unavailable", "locked", "offline", "forbidden",
        "expired", "cancelled", "io", "protocol", "conflict",
    }
    for identity, suite in suites.items():
        for vector in suite.get("vectors", []):
            expectations = [vector, *vector.get("cases", [])]
            for expected in expectations:
                for key in ("expected_error", "expected_first_error"):
                    if key not in expected:
                        continue
                    value = expected[key]
                    if value is None and key == "expected_error":
                        continue
                    # These existing direct-facade reasons are not core/binding error codes.
                    facade_codes = {"key-unavailable", "preview-timeout"} if identity == "sdk.embeds.family" else set()
                    if not isinstance(value, str) or value not in codes | facade_codes:
                        raise ValueError("Invalid typed error fixture oracle: " + key)
            if (
                identity == "session.work-crud.v1"
                and vector.get("mode") == "cancel"
                and vector.get("expected_first_error") != "cancelled"
            ):
                raise ValueError("Work cancellation requires expected_first_error cancelled")


def conformance(matrix: dict, root: Path = ROOT) -> list[dict]:
    fixtures = {}
    known_ids = {capability["id"] for capability in matrix["capabilities"]}
    for name in {matrix["fixture"]} | {
        capability.get("fixture", matrix["fixture"])
        for capability in matrix["capabilities"]
    }:
        file = repo_file(name, root)
        raw = file.read_bytes()
        document = json.loads(raw)
        validate_fixture_document(name, document, root)
        suites = document["capabilities"]
        validate_fixture_error_oracles(suites)
        unregistered = set(suites) - known_ids
        if unregistered:
            raise ValueError(
                "Fixture capabilities missing from reviewed matrix: "
                + ", ".join(sorted(unregistered))
            )
        fixtures[name] = (file, hashlib.sha256(raw).hexdigest(), suites)
    results = []
    for capability in matrix["capabilities"]:
        fixture, fixture_hash, fixture_suites = fixtures[
            capability.get("fixture", matrix["fixture"])
        ]
        for language in LANGUAGES:
            if not capability["languages"][language]["conformance"]:
                continue
            suite = fixture_suites.get(capability["id"], {})
            vectors = suite.get("vectors", [])
            expected_ids = {vector.get("id", vector.get("name")) for vector in vectors}
            if not vectors or None in expected_ids or len(expected_ids) != len(vectors):
                raise ValueError(
                    "Missing or duplicate independent fixture vectors: "
                    + capability["id"]
                )
            adapter = ADAPTER_OVERRIDES.get(
                (language, capability["id"]), RUNNERS[language]
            )
            command = adapter + [
                "--fixture",
                str(fixture),
                "--capability",
                capability["id"],
            ]
            process = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=600,
                env={
                    **os.environ,
                    "OPENMATES_SDK_CONFORMANCE_PYTHON": sys.executable,
                    "CARGO_INCREMENTAL": "0",
                },
            )
            if process.returncode:
                signal_name = "none"
                if process.returncode < 0:
                    try:
                        signal_name = signal.Signals(-process.returncode).name
                    except ValueError:
                        signal_name = "unknown"
                raise ValueError(
                    f"Library conformance failed {capability['id']}/{language} "
                    f"(returncode={process.returncode}, signal={signal_name}): "
                    f"{process.stderr[-2000:]}"
                )
            result = json.loads(process.stdout)
            validate_result(
                result, capability["id"], language, fixture_hash, expected_ids
            )
            results.append(result)
    if not results:
        raise ValueError("No real library conformance was executed")
    return results


def check_generated(root: Path = ROOT) -> None:
    """Canonical App additions must update all three actual generated SDKs."""

    def module(name, relative):
        specification = importlib.util.spec_from_file_location(name, root / relative)
        if not specification or not specification.loader:
            raise ValueError("Cannot load SDK generator: " + relative)
        loaded = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(loaded)
        return loaded

    canonical = module(
        "sdk_gate_canonical_generator", "scripts/generate_sdk_app_skills.py"
    )
    skills = canonical.load_skills()
    expected = {
        canonical.NPM_GENERATED: canonical.generate_ts(skills),
        canonical.PY_GENERATED: canonical.generate_py(skills),
    }
    rust = module("sdk_gate_rust_generator", "scripts/generate_rust_sdk_apps.py")
    expected.update(rust.outputs())
    stale = [
        str(path.relative_to(root))
        for path, content in expected.items()
        if not path.is_file() or path.read_text() != content
    ]
    if stale:
        raise ValueError(
            "Generated SDK methods differ from canonical App metadata: "
            + ", ".join(stale)
        )


def run(*, release: bool = False, execute: bool = False, root: Path = ROOT) -> dict:
    check_generated(root)
    matrix_bytes = (root / MATRIX).read_bytes()
    matrix = json.loads(matrix_bytes)
    inventory = discover_inventory(root)
    gaps = validate_matrix(matrix, inventory, root)
    results = conformance(matrix, root) if execute or release else []
    if release and gaps:
        raise ValueError(
            "SDK publication blocked by unsynchronized capabilities:\n"
            + "\n".join(gaps)
        )
    return {
        "status": "migration-gaps" if gaps else "synchronized",
        "matrixSha256": hashlib.sha256(matrix_bytes).hexdigest(),
        "publicApiInventorySha256": hashlib.sha256(
            json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "fixtureSha256": results[0].get("fixtureSha256") if results else None,
        "fixtureSha256ByCapability": {
            result["capability"]: result["fixtureSha256"]
            for result in results
            if "capability" in result
        },
        "publicApis": {key: len(value) for key, value in inventory.items()},
        "openGaps": gaps,
        "conformance": results,
        "releaseEligible": not gaps and bool(results),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release",
        action="store_true",
        help="Run real conformance and reject every declared parity gap",
    )
    parser.add_argument(
        "--conformance",
        action="store_true",
        help="Run real library fixtures while retaining explicit migration gaps",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = run(release=args.release, execute=args.conformance)
    except (
        ValueError,
        jsonschema.ValidationError,
        subprocess.SubprocessError,
        OSError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        f"SDK capability audit: {result['status']}; "
        + ", ".join(
            f"{key}={value} APIs" for key, value in result["publicApis"].items()
        )
        + f"; {len(result['conformance'])} real conformance runs; {len(result['openGaps'])} open gaps"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
