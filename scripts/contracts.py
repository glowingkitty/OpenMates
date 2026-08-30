#!/usr/bin/env python3
"""Validate and trace OpenMates contract bundles.

Contracts are concise, approved sources of product truth. This CLI keeps bundle
validation, fingerprints, registries, coverage, approvals, test links, docs,
release traces, and archive policy behind one discoverable command surface.
Architecture: docs/specs/contract-driven-development/spec.yml
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACTS_ROOT = REPO_ROOT / "contracts"


def _control_plane_root(repo_root: Path) -> Path:
    if repo_root.parent.name in {".openmates-agent-worktrees", ".agent-worktrees"}:
        return repo_root.parent.parent
    return repo_root


CONTROL_PLANE_ROOT = _control_plane_root(REPO_ROOT)
DEFAULT_APPROVALS_PATH = CONTROL_PLANE_ROOT / "scripts" / ".contracts-approvals-state.json"
CONTRACT_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9][a-z0-9-]*)+$")
ASSERTION_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9][a-z0-9-]*)+$")
VALID_CONTRACT_STATUSES = {"draft", "approved", "superseded"}
VALID_ASSERTION_TYPES = {
    "behavior",
    "failure",
    "invariant",
    "parity",
    "privacy",
    "security",
    "validation",
}
REQUIRED_SURFACES = ("rest_api", "cli", "sdks", "gui")
CONTRACT_GENERATED_PATHS = {
    "contracts/generated/assertion-index.yml",
    "contracts/generated/coverage.yml",
    "contracts/generated/registry.yml",
}
SPEC_EVIDENCE_PATH = re.compile(r"^docs/specs/[^/]+/(?:spec\.yml|evidence/[^/]+\.(?:json|ya?ml))$")


class ContractError(ValueError):
    """Raised when contract metadata is incomplete or contradictory."""


@dataclass(frozen=True)
class ContractBundle:
    path: Path
    contract_id: str
    version: int
    status: str
    contract: dict[str, Any]
    examples: dict[str, Any]
    fingerprint: str

    @property
    def versioned_id(self) -> str:
        return f"{self.contract_id}@{self.version}"


@dataclass(frozen=True)
class TestContractRecord:
    path: Path
    line: int
    name: str
    classification: str
    surface: str | None
    assertions: tuple[str, ...]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ContractError(f"missing required file: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ContractError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{path} must contain a YAML mapping")
    return value


def _non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    return value.strip()


def _non_empty_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ContractError(f"{field} must be a non-empty list")
    return value


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{field} must be a mapping")
    return value


def _canonical_hash(*values: dict[str, Any]) -> str:
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_models(models: Any) -> None:
    models = _mapping(models, "models")
    for model_name, fields in models.items():
        _non_empty_string(model_name, "model name")
        fields = _mapping(fields, f"models.{model_name}")
        for field_name, definition in fields.items():
            _non_empty_string(field_name, f"models.{model_name} field name")
            definition = _mapping(definition, f"models.{model_name}.{field_name}")
            _non_empty_string(definition.get("type"), f"models.{model_name}.{field_name}.type")
            constraints = definition.get("constraints")
            if constraints is not None and not isinstance(constraints, dict):
                raise ContractError(f"models.{model_name}.{field_name}.constraints must be a mapping")


def _validate_assertions(assertions: Any) -> None:
    seen: set[str] = set()
    for index, assertion in enumerate(_non_empty_list(assertions, "assertions"), start=1):
        assertion = _mapping(assertion, f"assertions[{index}]")
        assertion_id = _non_empty_string(assertion.get("id"), f"assertions[{index}].id")
        if not ASSERTION_ID.fullmatch(assertion_id):
            raise ContractError(f"invalid assertion id: {assertion_id}")
        if assertion_id in seen:
            raise ContractError(f"duplicate assertion id in bundle: {assertion_id}")
        seen.add(assertion_id)
        assertion_type = _non_empty_string(assertion.get("type"), f"{assertion_id}.type")
        if assertion_type not in VALID_ASSERTION_TYPES:
            raise ContractError(f"{assertion_id}.type must be one of {', '.join(sorted(VALID_ASSERTION_TYPES))}")
        _non_empty_string(assertion.get("must"), f"{assertion_id}.must")
        depends_on = assertion.get("depends_on")
        if depends_on is not None and (
            not isinstance(depends_on, list)
            or not depends_on
            or not all(isinstance(item, str) and item.strip() for item in depends_on)
        ):
            raise ContractError(f"{assertion_id}.depends_on must be a non-empty string list")


def _validate_surfaces(surfaces: Any) -> None:
    surfaces = _mapping(surfaces, "surfaces")
    missing = [surface for surface in REQUIRED_SURFACES if surface not in surfaces]
    if missing:
        raise ContractError(f"surfaces missing required entries: {', '.join(missing)}")
    for name in REQUIRED_SURFACES:
        surface = _mapping(surfaces[name], f"surfaces.{name}")
        if not isinstance(surface.get("required"), bool):
            raise ContractError(f"surfaces.{name}.required must be boolean")
    for surface_name, implementations in (
        ("sdks", ("npm", "pip")),
        ("gui", ("web", "apple")),
    ):
        surface = surfaces[surface_name]
        mapped = _mapping(surface.get("implementations"), f"surfaces.{surface_name}.implementations")
        for implementation in implementations:
            item = _mapping(mapped.get(implementation), f"surfaces.{surface_name}.implementations.{implementation}")
            if not isinstance(item.get("required"), bool):
                raise ContractError(f"surfaces.{surface_name}.implementations.{implementation}.required must be boolean")
    exceptions = surfaces["gui"].get("exceptions", [])
    if not isinstance(exceptions, list):
        raise ContractError("surfaces.gui.exceptions must be a list")
    for index, exception in enumerate(exceptions, start=1):
        exception = _mapping(exception, f"surfaces.gui.exceptions[{index}]")
        for field in ("id", "implementation", "reason", "equivalent_outcome"):
            _non_empty_string(exception.get(field), f"surfaces.gui.exceptions[{index}].{field}")


def validate_bundle(path: Path) -> ContractBundle:
    """Load and validate one contract.yml/examples.yml bundle."""
    bundle_path = Path(path)
    if bundle_path.name == "contract.yml":
        bundle_path = bundle_path.parent
    contract = _load_yaml(bundle_path / "contract.yml")
    if contract.get("schema_version") != 1:
        raise ContractError("contract.schema_version must be 1")
    contract_id = _non_empty_string(contract.get("id"), "id")
    if not CONTRACT_ID.fullmatch(contract_id):
        raise ContractError(f"invalid contract id: {contract_id}")
    version = contract.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ContractError("version must be a positive integer")
    status = _non_empty_string(contract.get("status"), "status")
    if status not in VALID_CONTRACT_STATUSES:
        raise ContractError(f"status must be one of {', '.join(sorted(VALID_CONTRACT_STATUSES))}")
    _non_empty_string(contract.get("title"), "title")
    _non_empty_string(contract.get("summary"), "summary")
    scope = _mapping(contract.get("scope"), "scope")
    _non_empty_list(scope.get("includes"), "scope.includes")
    _non_empty_list(scope.get("excludes"), "scope.excludes")
    _validate_models(contract.get("models"))
    _validate_assertions(contract.get("assertions"))
    _validate_surfaces(contract.get("surfaces"))

    examples_ref = _mapping(contract.get("examples"), "examples")
    examples_file = _non_empty_string(examples_ref.get("file"), "examples.file")
    required_groups = _non_empty_list(examples_ref.get("required_groups"), "examples.required_groups")
    if not all(isinstance(group, str) and group.strip() for group in required_groups):
        raise ContractError("examples.required_groups must contain non-empty strings")
    examples = _load_yaml(bundle_path / examples_file)
    if examples.get("schema_version") != 1:
        raise ContractError("examples.schema_version must be 1")
    expected_ref = f"{contract_id}@{version}"
    if examples.get("contract") != expected_ref:
        raise ContractError(f"examples.contract must be {expected_ref}")
    for group in required_groups:
        _non_empty_list(examples.get(group), f"examples.{group}")

    return ContractBundle(
        path=bundle_path,
        contract_id=contract_id,
        version=version,
        status=status,
        contract=contract,
        examples=examples,
        fingerprint=_canonical_hash(contract, examples),
    )


def discover_bundles(contracts_root: Path) -> list[ContractBundle]:
    root = Path(contracts_root)
    if not root.exists():
        return []
    return [validate_bundle(path.parent) for path in sorted(root.rglob("contract.yml")) if "generated" not in path.parts]


def _required_surface_paths(bundle: ContractBundle) -> list[str]:
    surfaces = bundle.contract["surfaces"]
    required = [name for name in ("rest_api", "cli") if surfaces[name]["required"]]
    for group in ("sdks", "gui"):
        if not surfaces[group]["required"]:
            continue
        for implementation, metadata in surfaces[group]["implementations"].items():
            if metadata["required"]:
                required.append(f"{group}.{implementation}")
    return required


def build_registry(contracts_root: Path) -> dict[str, Any]:
    contracts: dict[str, Any] = {}
    assertions: dict[str, Any] = {}
    for bundle in discover_bundles(contracts_root):
        if bundle.contract_id in contracts:
            raise ContractError(f"duplicate contract id: {bundle.contract_id}")
        contracts[bundle.contract_id] = {
            "version": bundle.version,
            "status": bundle.status,
            "path": str(bundle.path.relative_to(Path(contracts_root))),
            "fingerprint": bundle.fingerprint,
            "required_surfaces": _required_surface_paths(bundle),
        }
        for assertion in bundle.contract["assertions"]:
            assertion_id = assertion["id"]
            if assertion_id in assertions:
                raise ContractError(f"duplicate assertion id: {assertion_id}")
            dependencies = assertion.get("depends_on") or ["models", "examples", "surfaces"]
            dependency_values = {
                dependency: _resolve_bundle_dependency(bundle, dependency)
                for dependency in dependencies
            }
            assertions[assertion_id] = {
                "contract": bundle.versioned_id,
                "contract_id": bundle.contract_id,
                "type": assertion["type"],
                "fingerprint": _canonical_hash(assertion, dependency_values),
                "required_surfaces": _required_surface_paths(bundle),
            }
    return {"schema_version": 1, "contracts": contracts, "assertions": assertions}


def _resolve_bundle_dependency(bundle: ContractBundle, dependency: str) -> Any:
    if dependency == "models":
        return bundle.contract.get("models", {})
    if dependency == "examples":
        return bundle.examples
    if dependency == "surfaces":
        return bundle.contract.get("surfaces", {})
    if dependency.startswith("models."):
        value: Any = bundle.contract.get("models", {})
        parts = dependency.split(".")[1:]
    elif dependency.startswith("examples."):
        value = bundle.examples
        parts = dependency.split(".")[1:]
    elif dependency.startswith("surfaces."):
        value = bundle.contract.get("surfaces", {})
        parts = dependency.split(".")[1:]
    else:
        raise ContractError(f"unsupported assertion dependency {dependency!r}")
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
            continue
        if isinstance(value, list):
            match = next((item for item in value if isinstance(item, dict) and item.get("id") == part), None)
            if match is not None:
                value = match
                continue
        raise ContractError(f"assertion dependency {dependency!r} does not resolve")
    return value


def build_coverage(registry: dict[str, Any], test_index: dict[str, Any]) -> dict[str, Any]:
    assertions = registry.get("assertions", {})
    indexed = test_index.get("assertions", {}) if isinstance(test_index, dict) else {}
    surface_names = ("rest_api", "cli", "sdks.npm", "sdks.pip", "gui.web", "gui.apple")
    surface_parity: dict[str, dict[str, int]] = {}
    for surface in surface_names:
        required = sum(surface in record.get("required_surfaces", []) for record in assertions.values())
        proven = sum(
            bool(indexed.get(assertion_id, {}).get("surfaces", {}).get(surface, {}).get("current_direct_proof"))
            for assertion_id in assertions
            if surface in assertions[assertion_id].get("required_surfaces", [])
        )
        surface_parity[surface] = {"required": required, "proven": proven}
    return {
        "schema_version": 1,
        "approved_contracts": sum(record.get("status") == "approved" for record in registry.get("contracts", {}).values()),
        "assertions_total": len(assertions),
        "assertions_with_tests": sum(bool(indexed.get(assertion_id, {}).get("tests")) for assertion_id in assertions),
        "assertions_with_current_proof": sum(bool(indexed.get(assertion_id, {}).get("current_direct_proof")) for assertion_id in assertions),
        "surface_parity": surface_parity,
    }


def check_required_proof(
    registry: dict[str, Any],
    test_index: dict[str, Any],
    assertion_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    assertions = registry.get("assertions", {})
    indexed = test_index.get("assertions", {})
    for assertion_id in sorted(assertion_ids):
        if assertion_id not in assertions:
            continue
        record = indexed.get(assertion_id, {})
        for surface in assertions[assertion_id].get("required_surfaces", []):
            if not record.get("surfaces", {}).get(surface, {}).get("current_direct_proof"):
                errors.append(f"{assertion_id} lacks current direct proof on required surface {surface}")
    return errors


_MARKER = re.compile(r"^\s*(?:#|//)\s*contract-test:\s*([a-z_]+)(.*)$")
_FILE_MARKER = re.compile(r"^\s*(?:#|//)\s*contract-test-file:\s*(infrastructure|tooling)\s*$", re.MULTILINE)
_PYTHON_TEST = re.compile(r"^\s*(?:async\s+)?def\s+(test_[A-Za-z0-9_]+)\s*\(", re.DOTALL)
_SWIFT_TEST = re.compile(r"^\s*func\s+(test[A-Za-z0-9_]+)\s*\(", re.DOTALL)
_SWIFT_MACRO_TEST = re.compile(r"^\s*@Test(?:\s*\(.*?\))?\s*(?:async\s+)?func\s+([A-Za-z0-9_]+)\s*\(", re.DOTALL)
_TYPESCRIPT_TEST = re.compile(
    r"^\s*(?:test|it)(?:\.(?:only|skip|fixme|concurrent))*"
    r"(?:\.each\s*\(.*?\))?\s*\(\s*['\"`]([^'\"`]+)",
    re.DOTALL,
)
_VALID_TEST_CLASSIFICATIONS = {"direct", "supporting", "infrastructure", "tooling", "legacy_unmapped"}
_VALID_TEST_SURFACES = {"rest_api", "cli", "sdks.npm", "sdks.pip", "gui.web", "gui.apple", "tooling"}


def _test_name(source: str, path: Path) -> str | None:
    name = path.name
    if name.endswith(".py"):
        patterns = (_PYTHON_TEST,)
    elif name.endswith(".swift"):
        patterns = (_SWIFT_TEST, _SWIFT_MACRO_TEST)
    else:
        patterns = (_TYPESCRIPT_TEST,)
    for pattern in patterns:
        match = pattern.search(source)
        if match:
            return match.group(1)
    return None


def _could_start_test(line: str, path: Path) -> bool:
    stripped = line.lstrip()
    if path.name.endswith(".py"):
        return stripped.startswith(("def test_", "async def test_"))
    if path.name.endswith(".swift"):
        return stripped.startswith(("func test", "@Test"))
    return stripped.startswith(("test(", "test.", "it(", "it."))


def _parse_marker(line: str) -> tuple[str, str | None, tuple[str, ...]] | None:
    match = _MARKER.search(line)
    if not match:
        return None
    classification = match.group(1)
    attributes: dict[str, str] = {}
    for token in match.group(2).strip().split():
        if "=" in token:
            key, value = token.split("=", 1)
            attributes[key] = value
    assertions = tuple(item for item in attributes.get("assertions", "").split(",") if item)
    return classification, attributes.get("surface"), assertions


def parse_test_metadata(path: Path) -> list[TestContractRecord]:
    """Parse framework-neutral contract-test comments attached to test cases."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    records: list[TestContractRecord] = []
    pending: tuple[int, tuple[str, str | None, tuple[str, ...]]] | None = None
    file_classification = next(
        (match.group(1) for line in lines if (match := _FILE_MARKER.search(line))),
        None,
    )
    for line_number, line in enumerate(lines, start=1):
        marker = _parse_marker(line)
        if marker:
            pending = (line_number, marker)
            continue
        test_path = Path(path)
        name = (
            _test_name("\n".join(lines[line_number - 1 :]), test_path)
            if _could_start_test(line, test_path)
            else None
        )
        if not name:
            if pending and line.strip() and line_number - pending[0] > 8:
                pending = None
            continue
        if pending:
            _, (classification, surface, assertions) = pending
        elif file_classification:
            classification, surface, assertions = file_classification, None, ()
        else:
            classification, surface, assertions = "unmapped", None, ()
        records.append(
            TestContractRecord(
                path=Path(path),
                line=line_number,
                name=name,
                classification=classification,
                surface=surface,
                assertions=assertions,
            )
        )
        pending = None
    return records


def check_test_file(path: Path, registry: dict[str, Any], *, changed: bool) -> list[str]:
    errors: list[str] = []
    assertions = registry.get("assertions", {})
    records = parse_test_metadata(path)
    text = Path(path).read_text(encoding="utf-8")
    if changed and not records and not _FILE_MARKER.search(text):
        errors.append(f"{path}: no recognized test cases; add parser support or a contract-test-file classification")
    for record in records:
        prefix = f"{record.path}:{record.line} {record.name}"
        if record.classification == "unmapped":
            if changed:
                errors.append(f"{prefix}: missing contract-test metadata")
            continue
        if record.classification not in _VALID_TEST_CLASSIFICATIONS:
            errors.append(f"{prefix}: invalid contract-test classification {record.classification}")
            continue
        if record.classification == "legacy_unmapped":
            if changed:
                errors.append(f"{prefix}: legacy_unmapped is forbidden for changed tests")
            continue
        if record.classification in {"infrastructure", "tooling"}:
            if record.assertions or record.surface:
                errors.append(f"{prefix}: {record.classification} metadata must not claim product assertions or surfaces")
            continue
        if not record.surface:
            errors.append(f"{prefix}: direct/supporting proof requires a surface")
        elif record.surface not in _VALID_TEST_SURFACES:
            errors.append(f"{prefix}: unknown surface {record.surface}")
        if not record.assertions:
            errors.append(f"{prefix}: direct/supporting proof requires assertions")
        for assertion_id in record.assertions:
            if assertion_id not in assertions:
                errors.append(f"{prefix}: unknown assertion {assertion_id}")
    return errors


def build_test_index(
    paths: list[Path],
    registry: dict[str, Any],
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    index: dict[str, Any] = {"schema_version": 1, "assertions": {}}
    for assertion_id, metadata in registry.get("assertions", {}).items():
        index["assertions"][assertion_id] = {
            "contract": metadata.get("contract"),
            "fingerprint": metadata.get("fingerprint"),
            "direct_tests": [],
            "supporting_tests": [],
            "tests": [],
            "surfaces": {},
            "current_direct_proof": False,
        }
    for path in sorted(Path(item) for item in paths):
        for record in parse_test_metadata(path):
            if record.classification not in {"direct", "supporting"}:
                continue
            for assertion_id in record.assertions:
                if assertion_id not in index["assertions"]:
                    raise ContractError(f"unknown assertion {assertion_id} in {record.path}:{record.line}")
                reference = {
                    "path": _repository_display_path(record.path, repo_root=repo_root),
                    "line": record.line,
                    "name": record.name,
                    "surface": record.surface,
                }
                target = index["assertions"][assertion_id]
                target[f"{record.classification}_tests"].append(reference)
                target["tests"].append(reference)
                if record.surface:
                    surface = target["surfaces"].setdefault(record.surface, {"direct_tests": [], "supporting_tests": []})
                    surface[f"{record.classification}_tests"].append(reference)
    return index


def _repository_display_path(path: Path, *, repo_root: Path | None = None) -> str:
    resolved = Path(path).resolve()
    root = (repo_root or REPO_ROOT).resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        if repo_root is not None:
            raise ContractError(f"test path is outside repository root: {resolved}")
        return str(resolved)


def apply_evidence(
    registry: dict[str, Any],
    test_index: dict[str, Any],
    evidence_records: list[dict[str, Any]],
    *,
    repo_root: Path | None = None,
    expected_subject_commit: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Attach run history and mark only matching direct evidence as current."""
    result = copy.deepcopy(test_index)
    errors: list[str] = []
    assertions = registry.get("assertions", {})
    indexed = result.setdefault("assertions", {})
    for record in evidence_records:
        assertion_id = record.get("assertion")
        if assertion_id not in assertions:
            errors.append(f"unknown assertion in evidence: {assertion_id}")
            continue
        target = indexed.setdefault(assertion_id, {})
        target.setdefault("evidence_history", []).append(copy.deepcopy(record))
        current_fingerprint = assertions[assertion_id].get("fingerprint")
        if record.get("assertion_fingerprint") != current_fingerprint:
            errors.append(f"stale evidence for {assertion_id}: assertion fingerprint changed")
            continue
        if record.get("status") != "passed":
            continue
        classification = record.get("classification")
        if classification not in {"direct", "supporting"}:
            errors.append(f"invalid evidence classification for {assertion_id}: {classification}")
            continue
        surface_name = record.get("surface")
        if not isinstance(surface_name, str) or not surface_name:
            errors.append(f"evidence for {assertion_id} requires a surface")
            continue
        surface = target.setdefault("surfaces", {}).setdefault(
            surface_name,
            {"direct_tests": [], "supporting_tests": []},
        )
        mapped_tests = surface.get(f"{classification}_tests", [])
        if not mapped_tests:
            errors.append(f"evidence for {assertion_id} has no mapped {classification} test on {surface_name}")
            continue
        if repo_root is not None:
            attestation_error = _validate_evidence_attestation(
                record,
                mapped_tests,
                repo_root=repo_root,
                expected_subject_commit=expected_subject_commit,
            )
            if attestation_error:
                errors.append(f"evidence for {assertion_id}: {attestation_error}")
                continue
        surface.setdefault("evidence_history", []).append(copy.deepcopy(record))
        if classification == "direct":
            target["current_direct_proof"] = True
            surface["current_direct_proof"] = True
    return result, errors


def _validate_evidence_attestation(
    record: dict[str, Any],
    mapped_tests: list[dict[str, Any]],
    *,
    repo_root: Path,
    expected_subject_commit: str | None,
) -> str | None:
    test_path = record.get("test_path")
    test_name = record.get("test_name")
    if not any(test.get("path") == test_path and test.get("name") == test_name for test in mapped_tests):
        return "test_path and test_name must identify a mapped test"
    subject_commit = record.get("subject_commit")
    if expected_subject_commit and subject_commit != expected_subject_commit:
        if not _evidence_subject_commit_is_current_enough(
            repo_root,
            str(subject_commit or ""),
            expected_subject_commit,
        ):
            return f"tested subject commit must be {expected_subject_commit}"
    artifact_ref = record.get("run_artifact")
    artifact_hash = record.get("run_artifact_sha256")
    if not isinstance(artifact_ref, str) or not artifact_ref or not isinstance(artifact_hash, str) or not artifact_hash:
        return "run_artifact and run_artifact_sha256 are required"
    root = Path(repo_root).resolve()
    artifact = (root / artifact_ref).resolve()
    if root not in artifact.parents or not artifact.is_file():
        return "run_artifact must be an existing repository-relative file"
    if hashlib.sha256(artifact.read_bytes()).hexdigest() != artifact_hash:
        return "run_artifact_sha256 does not match the report"
    try:
        report = json.loads(artifact.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return f"run_artifact must be valid JSON: {exc}"
    if not isinstance(report, dict):
        return "run_artifact must contain a JSON object"
    if report.get("run_id") != record.get("run_id") or report.get("subject_commit") != record.get("subject_commit"):
        return "run artifact identity does not match run_id and subject_commit"
    tests = report.get("tests")
    if not isinstance(tests, list) or not any(
        isinstance(test, dict)
        and test.get("path") == test_path
        and test.get("name") == test_name
        and test.get("status") == "passed"
        for test in tests
    ):
        return "run artifact does not contain the mapped passing test"
    return None


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise ContractError(result.stderr.strip() or "cannot resolve tested subject commit")
    return result.stdout.strip()


def _git_dirty_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ContractError(result.stderr.strip() or "cannot inspect checkout state")
    return [line for line in result.stdout.splitlines() if line.strip()]


def _merged_session_worktree_error(repo_root: Path) -> str | None:
    """Reject evidence writes from stale session worktrees after deploy merge."""
    root = repo_root.resolve()
    if root.parent.name not in {".openmates-agent-worktrees", ".agent-worktrees"}:
        return None
    if not root.name.startswith("agent-"):
        return None
    session_id = root.name.removeprefix("agent-")
    sessions_path = CONTROL_PLANE_ROOT / ".claude" / "sessions.json"
    if not sessions_path.exists():
        return None
    try:
        sessions = json.loads(sessions_path.read_text(encoding="utf-8")).get("sessions", {})
    except json.JSONDecodeError as exc:
        raise ContractError(f"cannot inspect session worktree state: {exc}") from exc
    session = sessions.get(session_id)
    if not isinstance(session, dict):
        return None
    metadata = session.get("worktree")
    if not isinstance(metadata, dict) or metadata.get("status") != "merged":
        return None
    merged_commit = str(metadata.get("merged_commit") or "")
    head = _git_head(root)
    dirty = _git_dirty_files(root)
    if merged_commit and head == merged_commit and not dirty:
        return None
    details = []
    if merged_commit and head != merged_commit:
        details.append(f"HEAD {head[:9]} does not match merged commit {merged_commit[:9]}")
    if dirty:
        details.append(f"checkout has {len(dirty)} dirty file(s)")
    detail_text = "; ".join(details) or "checkout state is not clean"
    return (
        f"refusing to apply evidence from stale merged session worktree {session_id}: {detail_text}. "
        "Start a clean aligned session/worktree and rerun the proof so subject_commit-bound evidence is trustworthy."
    )


def _is_test_file(path: str) -> bool:
    name = Path(path).name
    return (
        name.endswith((".spec.ts", ".test.ts", ".spec.tsx", ".test.tsx", ".spec.js", ".test.js", "Tests.swift"))
        or (name.startswith("test_") and name.endswith(".py"))
        or name.endswith("_test.py")
    )


def _evidence_subject_commit_is_current_enough(repo_root: Path, subject_commit: str, expected_commit: str) -> bool:
    """Allow evidence-only commits to store proof for the product commit they prove."""

    if not subject_commit or not expected_commit:
        return False
    changed_paths = _metadata_only_evidence_paths_since(repo_root, subject_commit, expected_commit)
    if changed_paths is None:
        return False
    return all(_is_evidence_metadata_path(path) or _is_contract_test_metadata_only_change(repo_root, subject_commit, expected_commit, path) for path in changed_paths)


def _metadata_only_evidence_paths_since(repo_root: Path, subject_commit: str, expected_commit: str) -> list[str] | None:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{subject_commit}..{expected_commit}"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _is_evidence_metadata_path(path: str) -> bool:
    return path in CONTRACT_GENERATED_PATHS or bool(SPEC_EVIDENCE_PATH.fullmatch(path))


def _is_contract_test_metadata_only_change(repo_root: Path, subject_commit: str, expected_commit: str, path: str) -> bool:
    if not _is_test_file(path):
        return False
    result = subprocess.run(
        ["git", "diff", "--unified=0", f"{subject_commit}..{expected_commit}", "--", path],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    return _diff_only_changes_contract_test_markers(result.stdout)


def _diff_only_changes_contract_test_markers(diff_text: str) -> bool:
    changed_lines = []
    for line in diff_text.splitlines():
        if not line or line.startswith(("diff --git", "index ", "@@ ", "--- ", "+++ ")):
            continue
        if line[0] not in {"+", "-"}:
            continue
        changed_lines.append(line[1:])
    return bool(changed_lines) and all(_MARKER.search(line) or _FILE_MARKER.search(line) for line in changed_lines)


def _bundle_for_changed_contract_path(path: Path, contracts_root: Path) -> Path | None:
    root = contracts_root.resolve()
    current = path.resolve().parent
    while current == root or root in current.parents:
        if (current / "contract.yml").exists():
            return current
        if current == root:
            break
        current = current.parent
    return None


def _repository_test_files(repo_root: Path) -> list[Path]:
    excluded = {
        ".agent-worktrees",
        ".git",
        ".openmates-agent-worktrees",
        ".svelte-kit",
        ".venv",
        "build",
        "dist",
        "node_modules",
        "test-results",
    }
    files: list[Path] = []
    for current, directories, names in os.walk(repo_root):
        directories[:] = [name for name in directories if name not in excluded]
        current_path = Path(current)
        files.extend(current_path / name for name in names if _is_test_file(name))
    return files


def _evidence_records(test_index: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for assertion in test_index.get("assertions", {}).values():
        records.extend(copy.deepcopy(assertion.get("evidence_history", [])))
    return records


def check_generated_integrity(repo_root: Path, *, contracts_root: Path | None = None) -> list[str]:
    root = Path(repo_root).resolve()
    contract_root = (contracts_root or root / "contracts").resolve()
    generated = contract_root / "generated"
    expected_registry = build_registry(contract_root)
    paths = {
        "registry.yml": generated / "registry.yml",
        "assertion-index.yml": generated / "assertion-index.yml",
        "coverage.yml": generated / "coverage.yml",
    }
    errors: list[str] = []
    actual: dict[str, dict[str, Any]] = {}
    for name, path in paths.items():
        try:
            actual[name] = _load_yaml(path)
        except ContractError as exc:
            errors.append(str(exc))
    if errors:
        return errors
    if actual["registry.yml"] != expected_registry:
        return ["contracts/generated/registry.yml is stale; regenerate contract artifacts"]
    expected_index = build_test_index(_repository_test_files(root), expected_registry, repo_root=root)
    expected_index, evidence_errors = apply_evidence(
        expected_registry,
        expected_index,
        _evidence_records(actual["assertion-index.yml"]),
        repo_root=root,
        expected_subject_commit=_git_head(root),
    )
    errors.extend(evidence_errors)
    expected = {
        "registry.yml": expected_registry,
        "assertion-index.yml": expected_index,
        "coverage.yml": build_coverage(expected_registry, expected_index),
    }
    for name, value in expected.items():
        if actual[name] != value:
            errors.append(f"contracts/generated/{name} is stale; regenerate contract artifacts")
    return errors


def generate_contract_artifacts(repo_root: Path, *, contracts_root: Path | None = None) -> None:
    root = Path(repo_root).resolve()
    contract_root = (contracts_root or root / "contracts").resolve()
    generated = contract_root / "generated"
    registry = build_registry(contract_root)
    existing_index_path = generated / "assertion-index.yml"
    existing_index = _load_yaml(existing_index_path) if existing_index_path.exists() else {}
    test_index = build_test_index(_repository_test_files(root), registry, repo_root=root)
    test_index, evidence_errors = apply_evidence(
        registry,
        test_index,
        _evidence_records(existing_index),
        repo_root=root,
        expected_subject_commit=_git_head(root),
    )
    if evidence_errors:
        raise ContractError("\n".join(evidence_errors))
    _write_output(registry, generated / "registry.yml", False)
    _write_output(test_index, generated / "assertion-index.yml", False)
    _write_output(build_coverage(registry, test_index), generated / "coverage.yml", False)


def check_changed_files(
    repo_root: Path,
    changed_paths: list[str],
    *,
    session_id: str,
    approvals_path: Path,
) -> list[str]:
    """Return blocking contract errors for changed tests and bundles only."""
    root = Path(repo_root)
    contracts_root = root / "contracts"
    try:
        registry = build_registry(contracts_root)
    except ContractError as exc:
        return [str(exc)]
    errors: list[str] = []
    bundles: set[Path] = set()
    verify_generated = False
    for relative in sorted(set(changed_paths)):
        path = root / relative
        if _is_test_file(relative) and path.exists():
            errors.extend(check_test_file(path, registry, changed=True))
            verify_generated = True
        if relative.startswith("docs/specs/") and Path(relative).name == "spec.yml" and path.exists():
            verify_generated = True
            errors.extend(
                verify_spec_contracts(
                    path,
                    contracts_root=contracts_root,
                    session_id=session_id,
                    approvals_path=approvals_path,
                )
            )
        if relative.startswith("contracts/"):
            verify_generated = True
            bundle_path = _bundle_for_changed_contract_path(path, contracts_root)
            if bundle_path:
                bundles.add(bundle_path)
            elif Path(relative).name == "contract.yml" and not path.exists():
                errors.append(f"{relative}: permanent contracts cannot be deleted; supersede the contract instead")
    for bundle_path in sorted(bundles):
        try:
            bundle = validate_bundle(bundle_path)
        except ContractError as exc:
            errors.append(f"{bundle_path}: {exc}")
            continue
        approval_error = check_approval(
            approvals_path,
            session_id,
            bundle.contract_id,
            bundle.fingerprint,
        )
        if approval_error:
            errors.append(approval_error)
    if verify_generated and (contracts_root / "generated").exists():
        try:
            errors.extend(check_generated_integrity(root, contracts_root=contracts_root))
        except ContractError as exc:
            errors.append(str(exc))
    return errors


def check_documentation_impact(impact: dict[str, Any], *, generated_current: bool) -> list[str]:
    errors: list[str] = []
    for area in ("generated_reference", "user_docs", "semantic_layer"):
        record = impact.get(area)
        if not isinstance(record, dict):
            errors.append(f"documentation impact missing {area}")
            continue
        status = record.get("status")
        if status in {"unchanged", "not_applicable"} and not str(record.get("reason") or "").strip():
            errors.append(f"documentation impact {area} requires a reason when {status}")
        if status == "update_required" and not record.get("documents"):
            errors.append(f"documentation impact {area} requires documents while update_required")
    generated_status = (impact.get("generated_reference") or {}).get("status")
    if generated_status == "regenerate" and not generated_current:
        errors.append("generated reference is stale and must be regenerated")
    return errors


_TRAILER_KEYS = ("Contracts", "Assertions", "Spec", "Contract-Impact", "Contract-Exceptions")


def _parse_trailers(message: str) -> dict[str, list[str]]:
    trailers = {key: [] for key in _TRAILER_KEYS}
    for line in message.splitlines():
        for key in _TRAILER_KEYS:
            prefix = f"{key}:"
            if line.startswith(prefix):
                trailers[key].extend(item.strip() for item in line[len(prefix) :].split(",") if item.strip())
    return trailers


def validate_commit_trace(message: str, *, contract_governed: bool) -> list[str]:
    if not contract_governed:
        return []
    trailers = _parse_trailers(message)
    errors: list[str] = []
    for key in ("Contracts", "Assertions", "Spec", "Contract-Impact"):
        if not trailers[key]:
            errors.append(f"contract-governed commit requires {key}: trailer")
    return errors


def build_release_summary(messages: list[str]) -> dict[str, Any]:
    values = {key: set() for key in _TRAILER_KEYS}
    for message in messages:
        for key, items in _parse_trailers(message).items():
            values[key].update(items)
    return {
        "schema_version": 1,
        "contracts": sorted(values["Contracts"]),
        "assertions": sorted(values["Assertions"]),
        "specs": sorted(values["Spec"]),
        "impacts": sorted(values["Contract-Impact"]),
        "approved_exceptions": sorted(values["Contract-Exceptions"]),
    }


def render_contract_reference(bundle: ContractBundle) -> str:
    lines = [f"# {bundle.contract['title']}", "", bundle.contract["summary"], "", "## Models"]
    for model_name, fields in bundle.contract["models"].items():
        lines.extend(["", f"### {model_name}", "", "| Field | Type | Required | Constraints |", "| --- | --- | --- | --- |"])
        for field_name, definition in fields.items():
            constraints = json.dumps(definition.get("constraints", {}), sort_keys=True)
            lines.append(f"| `{field_name}` | `{definition['type']}` | {bool(definition.get('required'))} | `{constraints}` |")
    lines.extend(["", "## Assertions"])
    for assertion in bundle.contract["assertions"]:
        lines.append(f"- `{assertion['id']}`: {assertion['must']}")
    lines.extend(["", "## Surfaces"])
    for surface in _required_surface_paths(bundle):
        lines.append(f"- `{surface}`")
    lines.extend(["", f"Bundle fingerprint: `{bundle.fingerprint}`", ""])
    return "\n".join(lines)


def archive_specs(
    active_root: Path,
    archive_root: Path,
    *,
    cooling_days: int,
    now: datetime,
) -> list[Path]:
    moved: list[Path] = []
    cutoff = now - timedelta(days=cooling_days)
    for path in sorted(Path(active_root).glob("*/spec.yml")):
        data = _load_yaml(path)
        modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        if data.get("status") != "verified" or modified > cutoff:
            continue
        if data.get("schema_version", 1) < 3 or not data.get("contract_refs"):
            continue
        if not isinstance(data.get("implementation_state"), dict) or not data["implementation_state"].get("subject_commit"):
            continue
        destination = Path(archive_root) / str(now.year) / path.parent.name / "spec.yml"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(destination))
        try:
            path.parent.rmdir()
        except OSError:
            pass
        moved.append(destination)
    return moved


def contract_command_names() -> set[str]:
    return {
        "validate",
        "registry",
        "coverage",
        "fingerprint",
        "approve",
        "check-approval",
        "check-test",
        "index-tests",
        "apply-evidence",
        "check-generated",
        "generate",
        "check-changed",
        "docs",
        "release-summary",
        "archive-specs",
        "verify",
    }


def verify_spec_contracts(
    spec_path: Path,
    *,
    contracts_root: Path,
    session_id: str | None = None,
    approvals_path: Path = DEFAULT_APPROVALS_PATH,
) -> list[str]:
    try:
        from spec_validate import validate_spec

        data = validate_spec(spec_path)
    except (ImportError, ValueError) as exc:
        return [str(exc)]
    if data.get("schema_version", 1) < 3:
        return []
    try:
        registry = build_registry(contracts_root)
    except ContractError as exc:
        return [str(exc)]
    errors: list[str] = []
    contracts = registry.get("contracts", {})
    assertions = registry.get("assertions", {})
    for ref in data.get("contract_refs", []):
        record = contracts.get(ref["id"])
        if not record:
            errors.append(f"unknown contract ref {ref['id']}@{ref['version']}")
        elif record.get("version") != ref["version"]:
            errors.append(f"contract ref {ref['id']} expects version {ref['version']} but registry has {record.get('version')}")
    referenced_assertions: set[str] = set(data.get("contract_impact", {}).get("affected_assertions", []))
    for criterion in data.get("acceptance_criteria", []):
        referenced_assertions.update(criterion.get("contract_assertions", []))
    for test in data.get("tests", []):
        referenced_assertions.update(test.get("contract_assertions", []))
    for assertion_id in sorted(referenced_assertions):
        if assertion_id not in assertions:
            errors.append(f"unknown contract assertion {assertion_id}")
    generated_current = (contracts_root / "generated" / "registry.yml").exists()
    errors.extend(check_documentation_impact(data.get("documentation_impact", {}), generated_current=generated_current))
    if data.get("status") == "verified":
        try:
            test_index = _load_yaml(contracts_root / "generated" / "assertion-index.yml")
            errors.extend(check_required_proof(registry, test_index, referenced_assertions))
        except ContractError as exc:
            errors.append(str(exc))
    if data.get("contract_impact", {}).get("contract_update_required") and session_id:
        for ref in data.get("contract_refs", []):
            if ref.get("role") != "primary" or ref["id"] not in contracts:
                continue
            error = check_approval(
                approvals_path,
                session_id,
                ref["id"],
                contracts[ref["id"]]["fingerprint"],
            )
            if error:
                errors.append(error)
    return errors


def _load_approvals(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "sessions": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid approval state: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("sessions"), dict):
        raise ContractError("approval state must contain a sessions mapping")
    return value


def record_approval(
    path: Path,
    *,
    session_id: str,
    contract_id: str,
    fingerprint: str,
    confirmation: str,
) -> None:
    if confirmation != "explicit_user_confirmation":
        raise ContractError("approval requires explicit_user_confirmation")
    for value, field in ((session_id, "session_id"), (contract_id, "contract_id"), (fingerprint, "fingerprint")):
        _non_empty_string(value, field)
    state = _load_approvals(path)
    sessions = state.setdefault("sessions", {})
    contracts = sessions.setdefault(session_id, {})
    contracts[contract_id] = {
        "fingerprint": fingerprint,
        "confirmation": confirmation,
        "approved_at": datetime.now(UTC).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def check_approval(path: Path, session_id: str, contract_id: str, fingerprint: str) -> str | None:
    record = _load_approvals(path).get("sessions", {}).get(session_id, {}).get(contract_id)
    if not isinstance(record, dict):
        return f"missing approval for {contract_id} in session {session_id}"
    if record.get("confirmation") != "explicit_user_confirmation":
        return f"unconfirmed approval for {contract_id}"
    if record.get("fingerprint") != fingerprint:
        return f"stale approval for {contract_id}: bundle fingerprint changed"
    return None


def _write_output(value: dict[str, Any], output: Path | None, as_json: bool) -> None:
    rendered = json.dumps(value, indent=2, sort_keys=True) if as_json else yaml.safe_dump(value, sort_keys=False).rstrip()
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and trace OpenMates contracts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate one bundle or all bundles")
    validate.add_argument("path", nargs="?", default=str(DEFAULT_CONTRACTS_ROOT))
    validate.add_argument("--json", action="store_true")

    registry = subparsers.add_parser("registry", help="Build deterministic contract and assertion registry")
    registry.add_argument("--contracts-root", default=str(DEFAULT_CONTRACTS_ROOT))
    registry.add_argument("--output", type=Path)
    registry.add_argument("--json", action="store_true")

    coverage = subparsers.add_parser("coverage", help="Report contract and proof coverage")
    coverage.add_argument("--contracts-root", default=str(DEFAULT_CONTRACTS_ROOT))
    coverage.add_argument("--test-index", type=Path)
    coverage.add_argument("--output", type=Path)
    coverage.add_argument("--json", action="store_true")

    fingerprint = subparsers.add_parser("fingerprint", help="Print exact bundle fingerprint")
    fingerprint.add_argument("bundle")

    approve = subparsers.add_parser("approve", help="Record explicit user approval for exact bundle hash")
    approve.add_argument("bundle")
    approve.add_argument("--session", required=True)
    approve.add_argument("--confirmation", required=True, choices=["explicit_user_confirmation"])
    approve.add_argument("--approvals-file", type=Path, default=DEFAULT_APPROVALS_PATH)

    approval = subparsers.add_parser("check-approval", help="Check exact-hash session approval")
    approval.add_argument("bundle")
    approval.add_argument("--session", required=True)
    approval.add_argument("--approvals-file", type=Path, default=DEFAULT_APPROVALS_PATH)

    check_test = subparsers.add_parser("check-test", help="Validate contract metadata in one changed test file")
    check_test.add_argument("path")
    check_test.add_argument("--contracts-root", default=str(DEFAULT_CONTRACTS_ROOT))

    test_index = subparsers.add_parser("index-tests", help="Build assertion-to-test index")
    test_index.add_argument("paths", nargs="+")
    test_index.add_argument("--contracts-root", default=str(DEFAULT_CONTRACTS_ROOT))
    test_index.add_argument("--output", type=Path)
    test_index.add_argument("--json", action="store_true")

    evidence = subparsers.add_parser("apply-evidence", help="Attach fingerprint-bound run evidence to an assertion index")
    evidence.add_argument("evidence", type=Path)
    evidence.add_argument("--test-index", type=Path, required=True)
    evidence.add_argument("--contracts-root", default=str(DEFAULT_CONTRACTS_ROOT))
    evidence.add_argument("--output", type=Path, required=True)

    generated = subparsers.add_parser("check-generated", help="Reject stale registry, assertion index, or coverage artifacts")
    generated.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    generated.add_argument("--contracts-root", type=Path)

    generate = subparsers.add_parser("generate", help="Regenerate registry, assertion index, and coverage together")
    generate.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    generate.add_argument("--contracts-root", type=Path)

    changed = subparsers.add_parser("check-changed", help="Block unresolved changed tests or contract approvals")
    changed.add_argument("paths", nargs="+")
    changed.add_argument("--session", required=True)
    changed.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    changed.add_argument("--approvals-file", type=Path, default=DEFAULT_APPROVALS_PATH)

    docs = subparsers.add_parser("docs", help="Generate deterministic Markdown references from contracts")
    docs.add_argument("bundle")
    docs.add_argument("--output", type=Path, required=True)

    release = subparsers.add_parser("release-summary", help="Aggregate contract trailers from commit-message files")
    release.add_argument("messages", nargs="*", type=Path)
    release.add_argument("--git-range")
    release.add_argument("--output", type=Path)
    release.add_argument("--json", action="store_true")

    archive = subparsers.add_parser("archive-specs", help="Move complete cooled specs to year archives")
    archive.add_argument("--active-root", type=Path, default=REPO_ROOT / "docs" / "specs" / "active")
    archive.add_argument("--archive-root", type=Path, default=REPO_ROOT / "docs" / "specs" / "archive")
    archive.add_argument("--cooling-days", type=int, default=30)

    verify = subparsers.add_parser("verify", help="Verify a spec's permanent contract references and impacts")
    verify.add_argument("--spec", type=Path, required=True)
    verify.add_argument("--contracts-root", type=Path, default=DEFAULT_CONTRACTS_ROOT)
    verify.add_argument("--session")
    verify.add_argument("--approvals-file", type=Path, default=DEFAULT_APPROVALS_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            path = _resolve(args.path)
            bundles = discover_bundles(path) if path.is_dir() and not (path / "contract.yml").exists() else [validate_bundle(path)]
            result = {"status": "passed", "bundles": [{"contract": bundle.versioned_id, "fingerprint": bundle.fingerprint} for bundle in bundles]}
            _write_output(result, None, args.json)
        elif args.command == "registry":
            _write_output(build_registry(_resolve(args.contracts_root)), args.output, args.json)
        elif args.command == "coverage":
            registry = build_registry(_resolve(args.contracts_root))
            test_index = _load_yaml(args.test_index) if args.test_index else {}
            _write_output(build_coverage(registry, test_index), args.output, args.json)
        elif args.command == "fingerprint":
            print(validate_bundle(_resolve(args.bundle)).fingerprint)
        elif args.command == "approve":
            bundle = validate_bundle(_resolve(args.bundle))
            record_approval(
                args.approvals_file,
                session_id=args.session,
                contract_id=bundle.contract_id,
                fingerprint=bundle.fingerprint,
                confirmation=args.confirmation,
            )
            print(f"APPROVED {bundle.versioned_id} {bundle.fingerprint}")
        elif args.command == "check-approval":
            bundle = validate_bundle(_resolve(args.bundle))
            error = check_approval(args.approvals_file, args.session, bundle.contract_id, bundle.fingerprint)
            if error:
                raise ContractError(error)
            print(f"PASS {bundle.versioned_id}: exact bundle hash approved")
        elif args.command == "check-test":
            registry = build_registry(_resolve(args.contracts_root))
            errors = check_test_file(_resolve(args.path), registry, changed=True)
            if errors:
                raise ContractError("\n".join(errors))
            print(f"PASS {args.path}: contract-test metadata valid")
        elif args.command == "index-tests":
            registry = build_registry(_resolve(args.contracts_root))
            paths = [_resolve(path) for path in args.paths]
            _write_output(build_test_index(paths, registry, repo_root=REPO_ROOT), args.output, args.json)
        elif args.command == "apply-evidence":
            merged_worktree_error = _merged_session_worktree_error(REPO_ROOT)
            if merged_worktree_error:
                raise ContractError(merged_worktree_error)
            registry = build_registry(_resolve(args.contracts_root))
            test_index_value = _load_yaml(args.test_index)
            evidence_value = _load_yaml(args.evidence)
            records = evidence_value.get("evidence")
            if not isinstance(records, list):
                raise ContractError("evidence file must contain an evidence list")
            result, errors = apply_evidence(
                registry,
                test_index_value,
                records,
                repo_root=REPO_ROOT,
                expected_subject_commit=_git_head(REPO_ROOT),
            )
            if errors:
                raise ContractError("\n".join(errors))
            _write_output(result, args.output, False)
        elif args.command == "check-generated":
            errors = check_generated_integrity(
                args.repo_root,
                contracts_root=args.contracts_root,
            )
            if errors:
                raise ContractError("\n".join(errors))
            print("PASS: generated contract artifacts are current")
        elif args.command == "generate":
            generate_contract_artifacts(args.repo_root, contracts_root=args.contracts_root)
            print("WROTE: generated contract registry, assertion index, and coverage")
        elif args.command == "check-changed":
            errors = check_changed_files(
                args.repo_root,
                args.paths,
                session_id=args.session,
                approvals_path=args.approvals_file,
            )
            if errors:
                raise ContractError("\n".join(errors))
            print(f"PASS: {len(args.paths)} changed path(s) satisfy contract gates")
        elif args.command == "docs":
            bundle = validate_bundle(_resolve(args.bundle))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(render_contract_reference(bundle), encoding="utf-8")
            print(f"WROTE {args.output}")
        elif args.command == "release-summary":
            messages = [path.read_text(encoding="utf-8") for path in args.messages]
            if args.git_range:
                result = subprocess.run(
                    ["git", "log", "--format=%B%x00", args.git_range],
                    cwd=str(REPO_ROOT),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    raise ContractError(result.stderr.strip() or "git log failed")
                messages.extend(message for message in result.stdout.split("\x00") if message.strip())
            if not messages:
                raise ContractError("release-summary requires message files or --git-range")
            _write_output(build_release_summary(messages), args.output, args.json)
        elif args.command == "archive-specs":
            moved = archive_specs(
                args.active_root,
                args.archive_root,
                cooling_days=args.cooling_days,
                now=datetime.now(UTC),
            )
            print(f"ARCHIVED {len(moved)} spec(s)")
        elif args.command == "verify":
            errors = verify_spec_contracts(
                _resolve(args.spec),
                contracts_root=args.contracts_root,
                session_id=args.session,
                approvals_path=args.approvals_file,
            )
            if errors:
                raise ContractError("\n".join(errors))
            print(f"PASS {args.spec}: contract references and impacts valid")
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
