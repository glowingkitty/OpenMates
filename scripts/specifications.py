#!/usr/bin/env python3
"""Validate and trace OpenMates Specification bundles.

Specifications are concise, approved sources of durable truth. This CLI keeps bundle
validation, fingerprints, registries, coverage, approvals, test links, docs,
release traces, and archive policy behind one discoverable command surface.
Architecture: docs/plans/contract-driven-development/plan.yml
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
DEFAULT_SPECIFICATIONS_ROOT = REPO_ROOT / "specifications"


def _control_plane_root(repo_root: Path) -> Path:
    if repo_root.parent.name in {".openmates-agent-worktrees", ".agent-worktrees"}:
        return repo_root.parent.parent
    return repo_root


CONTROL_PLANE_ROOT = _control_plane_root(REPO_ROOT)
DEFAULT_APPROVALS_PATH = CONTROL_PLANE_ROOT / "scripts" / ".specifications-approvals-state.json"
BATCH_APPROVALS_KEY = "_batch_approvals"
SPECIFICATION_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9][a-z0-9-]*)+$")
ASSERTION_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9][a-z0-9-]*)+$")
VALID_SPECIFICATION_STATUSES = {"draft", "approved", "superseded"}
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
SPECIFICATION_GENERATED_PATHS = {
    "specifications/generated/assertion-index.yml",
    "specifications/generated/coverage.yml",
    "specifications/generated/registry.yml",
}
SPECIFICATION_EVIDENCE_TOOLING_PATHS = {
    "scripts/specification_approval_pdf.py",
    "scripts/specification_readable_pdf.py",
    "scripts/specifications.py",
    "scripts/plan_verify.py",
    "scripts/tests/test_specification_approval_pdf.py",
    "scripts/tests/test_specification_readable_pdf.py",
    "scripts/tests/test_specification_evidence.py",
    "scripts/tests/test_specifications_workflow.py",
    "scripts/tests/test_spec_demonstration_workflow.py",
}
SPEC_EVIDENCE_PATH = re.compile(r"^docs/plans/[^/]+/(?:plan\.yml|evidence/[^/]+\.(?:json|ya?ml))$")
SPEC_EVIDENCE_SUFFIXES = {".json", ".yml", ".yaml"}


class SpecificationError(ValueError):
    """Raised when Specification metadata is incomplete or contradictory."""


@dataclass(frozen=True)
class SpecificationBundle:
    path: Path
    specification_id: str
    version: int
    status: str
    specification: dict[str, Any]
    examples: dict[str, Any]
    fingerprint: str

    @property
    def versioned_id(self) -> str:
        return f"{self.specification_id}@{self.version}"


@dataclass(frozen=True)
class TestSpecificationRecord:
    path: Path
    line: int
    name: str
    classification: str
    surface: str | None
    assertions: tuple[str, ...]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SpecificationError(f"missing required file: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpecificationError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SpecificationError(f"{path} must contain a YAML mapping")
    return value


def _non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SpecificationError(f"{field} must be a non-empty string")
    return value.strip()


def _non_empty_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise SpecificationError(f"{field} must be a non-empty list")
    return value


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SpecificationError(f"{field} must be a mapping")
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
                raise SpecificationError(f"models.{model_name}.{field_name}.constraints must be a mapping")


def _validate_assertions(assertions: Any) -> None:
    seen: set[str] = set()
    for index, assertion in enumerate(_non_empty_list(assertions, "assertions"), start=1):
        assertion = _mapping(assertion, f"assertions[{index}]")
        assertion_id = _non_empty_string(assertion.get("id"), f"assertions[{index}].id")
        if not ASSERTION_ID.fullmatch(assertion_id):
            raise SpecificationError(f"invalid assertion id: {assertion_id}")
        if assertion_id in seen:
            raise SpecificationError(f"duplicate assertion id in bundle: {assertion_id}")
        seen.add(assertion_id)
        assertion_type = _non_empty_string(assertion.get("type"), f"{assertion_id}.type")
        if assertion_type not in VALID_ASSERTION_TYPES:
            raise SpecificationError(f"{assertion_id}.type must be one of {', '.join(sorted(VALID_ASSERTION_TYPES))}")
        _non_empty_string(assertion.get("must"), f"{assertion_id}.must")
        depends_on = assertion.get("depends_on")
        if depends_on is not None and (
            not isinstance(depends_on, list)
            or not depends_on
            or not all(isinstance(item, str) and item.strip() for item in depends_on)
        ):
            raise SpecificationError(f"{assertion_id}.depends_on must be a non-empty string list")


def _validate_applies_to(applies_to: Any) -> None:
    applies_to = _mapping(applies_to, "applies_to")
    if not applies_to:
        raise SpecificationError("applies_to must contain at least one applicability dimension")
    for name, value in applies_to.items():
        if name not in REQUIRED_SURFACES:
            if isinstance(value, list):
                values = _non_empty_list(value, f"applies_to.{name}")
                if not all(isinstance(item, str) and item.strip() for item in values):
                    raise SpecificationError(f"applies_to.{name} must contain non-empty strings")
            else:
                applicability = _mapping(value, f"applies_to.{name}")
                if not applicability:
                    raise SpecificationError(f"applies_to.{name} must not be empty")
                if "required" in applicability and not isinstance(applicability["required"], bool):
                    raise SpecificationError(f"applies_to.{name}.required must be boolean")
            continue
        surface = _mapping(value, f"applies_to.{name}")
        if not isinstance(surface.get("required"), bool):
            raise SpecificationError(f"applies_to.{name}.required must be boolean")
    for surface_name, implementations in (
        ("sdks", ("npm", "pip")),
        ("gui", ("web", "apple")),
    ):
        if surface_name not in applies_to:
            continue
        surface = applies_to[surface_name]
        mapped = _mapping(surface.get("implementations"), f"applies_to.{surface_name}.implementations")
        for implementation, raw_item in mapped.items():
            item = _mapping(raw_item, f"applies_to.{surface_name}.implementations.{implementation}")
            if not isinstance(item.get("required"), bool):
                raise SpecificationError(f"applies_to.{surface_name}.implementations.{implementation}.required must be boolean")
        for implementation in implementations:
            _mapping(mapped.get(implementation), f"applies_to.{surface_name}.implementations.{implementation}")
    if "gui" not in applies_to:
        return
    exceptions = applies_to["gui"].get("exceptions", [])
    if not isinstance(exceptions, list):
        raise SpecificationError("applies_to.gui.exceptions must be a list")
    for index, exception in enumerate(exceptions, start=1):
        exception = _mapping(exception, f"applies_to.gui.exceptions[{index}]")
        for field in ("id", "implementation", "reason", "equivalent_outcome"):
            _non_empty_string(exception.get(field), f"applies_to.gui.exceptions[{index}].{field}")


def validate_bundle(path: Path) -> SpecificationBundle:
    """Load and validate one specification.yml/examples.yml bundle."""
    bundle_path = Path(path)
    if bundle_path.name == "specification.yml":
        bundle_path = bundle_path.parent
    specification = _load_yaml(bundle_path / "specification.yml")
    if specification.get("schema_version") != 1:
        raise SpecificationError("specification.schema_version must be 1")
    specification_id = _non_empty_string(specification.get("id"), "id")
    if not SPECIFICATION_ID.fullmatch(specification_id):
        raise SpecificationError(f"invalid Specification id: {specification_id}")
    version = specification.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise SpecificationError("version must be a positive integer")
    status = _non_empty_string(specification.get("status"), "status")
    if status not in VALID_SPECIFICATION_STATUSES:
        raise SpecificationError(f"status must be one of {', '.join(sorted(VALID_SPECIFICATION_STATUSES))}")
    _non_empty_string(specification.get("title"), "title")
    _non_empty_string(specification.get("summary"), "summary")
    scope = _mapping(specification.get("scope"), "scope")
    _non_empty_list(scope.get("includes"), "scope.includes")
    _non_empty_list(scope.get("excludes"), "scope.excludes")
    if "models" in specification:
        _validate_models(specification["models"])
    _validate_assertions(specification.get("assertions"))
    _validate_applies_to(specification.get("applies_to"))

    examples_ref = _mapping(specification.get("examples"), "examples")
    examples_file = _non_empty_string(examples_ref.get("file"), "examples.file")
    required_groups = _non_empty_list(examples_ref.get("required_groups"), "examples.required_groups")
    if not all(isinstance(group, str) and group.strip() for group in required_groups):
        raise SpecificationError("examples.required_groups must contain non-empty strings")
    examples = _load_yaml(bundle_path / examples_file)
    if examples.get("schema_version") != 1:
        raise SpecificationError("examples.schema_version must be 1")
    expected_ref = f"{specification_id}@{version}"
    if examples.get("specification") != expected_ref:
        raise SpecificationError(f"examples.specification must be {expected_ref}")
    for group in required_groups:
        _non_empty_list(examples.get(group), f"examples.{group}")

    return SpecificationBundle(
        path=bundle_path,
        specification_id=specification_id,
        version=version,
        status=status,
        specification=specification,
        examples=examples,
        fingerprint=_canonical_hash(specification, examples),
    )


def discover_bundles(specifications_root: Path) -> list[SpecificationBundle]:
    root = Path(specifications_root)
    if not root.exists():
        return []
    return [validate_bundle(path.parent) for path in sorted(root.rglob("specification.yml")) if "generated" not in path.parts]


def _required_surface_paths(bundle: SpecificationBundle) -> list[str]:
    applies_to = bundle.specification.get("applies_to", bundle.specification.get("surfaces"))
    required = [
        name
        for name in ("rest_api", "cli")
        if isinstance(applies_to.get(name), dict) and applies_to[name].get("required") is True
    ]
    for group in ("sdks", "gui"):
        metadata = applies_to.get(group)
        if not isinstance(metadata, dict) or metadata.get("required") is not True:
            continue
        for implementation, implementation_metadata in metadata.get("implementations", {}).items():
            if implementation_metadata["required"]:
                required.append(f"{group}.{implementation}")
    return required


def build_registry(specifications_root: Path) -> dict[str, Any]:
    specifications: dict[str, Any] = {}
    assertions: dict[str, Any] = {}
    for bundle in discover_bundles(specifications_root):
        if bundle.specification_id in specifications:
            raise SpecificationError(f"duplicate Specification id: {bundle.specification_id}")
        specifications[bundle.specification_id] = {
            "version": bundle.version,
            "status": bundle.status,
            "path": str(bundle.path.relative_to(Path(specifications_root))),
            "fingerprint": bundle.fingerprint,
            "required_applies_to": _required_surface_paths(bundle),
        }
        for assertion in bundle.specification["assertions"]:
            assertion_id = assertion["id"]
            if assertion_id in assertions:
                raise SpecificationError(f"duplicate assertion id: {assertion_id}")
            dependencies = assertion.get("depends_on") or ["models", "examples", "surfaces"]
            dependency_values = {
                dependency: _resolve_bundle_dependency(bundle, dependency)
                for dependency in dependencies
            }
            assertions[assertion_id] = {
                "specification": bundle.versioned_id,
                "specification_id": bundle.specification_id,
                "type": assertion["type"],
                "fingerprint": _canonical_hash(assertion, dependency_values),
                "required_applies_to": _required_surface_paths(bundle),
            }
    return {"schema_version": 1, "specifications": specifications, "assertions": assertions}


def _resolve_bundle_dependency(bundle: SpecificationBundle, dependency: str) -> Any:
    if dependency == "models":
        return bundle.specification.get("models", {})
    if dependency == "examples":
        return bundle.examples
    if dependency in {"applies_to", "surfaces"}:
        return bundle.specification.get("applies_to", bundle.specification.get("surfaces", {}))
    if dependency.startswith("models."):
        value: Any = bundle.specification.get("models", {})
        parts = dependency.split(".")[1:]
    elif dependency.startswith("examples."):
        value = bundle.examples
        parts = dependency.split(".")[1:]
    elif dependency.startswith(("applies_to.", "surfaces.")):
        value = bundle.specification.get("applies_to", bundle.specification.get("surfaces", {}))
        parts = dependency.split(".")[1:]
    else:
        raise SpecificationError(f"unsupported assertion dependency {dependency!r}")
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
            continue
        if isinstance(value, list):
            match = next((item for item in value if isinstance(item, dict) and item.get("id") == part), None)
            if match is not None:
                value = match
                continue
        raise SpecificationError(f"assertion dependency {dependency!r} does not resolve")
    return value


def build_coverage(registry: dict[str, Any], test_index: dict[str, Any]) -> dict[str, Any]:
    assertions = registry.get("assertions", {})
    indexed = test_index.get("assertions", {}) if isinstance(test_index, dict) else {}
    surface_names = ("rest_api", "cli", "sdks.npm", "sdks.pip", "gui.web", "gui.apple")
    surface_parity: dict[str, dict[str, int]] = {}
    for surface in surface_names:
        required = sum(surface in record.get("required_applies_to", []) for record in assertions.values())
        proven = sum(
            bool(indexed.get(assertion_id, {}).get("surfaces", {}).get(surface, {}).get("current_direct_proof"))
            for assertion_id in assertions
            if surface in assertions[assertion_id].get("required_applies_to", [])
        )
        surface_parity[surface] = {"required": required, "proven": proven}
    return {
        "schema_version": 1,
        "approved_specifications": sum(record.get("status") == "approved" for record in registry.get("specifications", {}).values()),
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
        for surface in assertions[assertion_id].get("required_applies_to", []):
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


def parse_test_metadata(path: Path) -> list[TestSpecificationRecord]:
    """Parse framework-neutral contract-test comments attached to test cases."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    records: list[TestSpecificationRecord] = []
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
            TestSpecificationRecord(
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
            "specification": metadata.get("specification"),
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
                    raise SpecificationError(f"unknown assertion {assertion_id} in {record.path}:{record.line}")
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
            raise SpecificationError(f"test path is outside repository root: {resolved}")
        return str(resolved)


def apply_evidence(
    registry: dict[str, Any],
    test_index: dict[str, Any],
    evidence_records: list[dict[str, Any]],
    *,
    repo_root: Path | None = None,
    expected_subject_commit: str | None = None,
    stale_evidence_is_error: bool = True,
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
                if stale_evidence_is_error or not attestation_error.startswith("tested subject commit must be "):
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
        raise SpecificationError(result.stderr.strip() or "cannot resolve tested subject commit")
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
        raise SpecificationError(result.stderr.strip() or "cannot inspect checkout state")
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
        raise SpecificationError(f"cannot inspect session worktree state: {exc}") from exc
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
    changed_paths = _metadata_only_specification_evidence_paths_since(repo_root, subject_commit, expected_commit)
    if changed_paths is None:
        return False
    return all(_is_evidence_metadata_path(path) or _is_specification_test_metadata_only_change(repo_root, subject_commit, expected_commit, path) for path in changed_paths)


def _metadata_only_specification_evidence_paths_since(repo_root: Path, subject_commit: str, expected_commit: str) -> list[str] | None:
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
    return path in SPECIFICATION_GENERATED_PATHS or path in SPECIFICATION_EVIDENCE_TOOLING_PATHS or bool(SPEC_EVIDENCE_PATH.fullmatch(path))


def _is_specification_test_metadata_only_change(repo_root: Path, subject_commit: str, expected_commit: str, path: str) -> bool:
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
    return _diff_only_changes_specification_test_markers(result.stdout)


def _diff_only_changes_specification_test_markers(diff_text: str) -> bool:
    changed_lines = []
    for line in diff_text.splitlines():
        if not line or line.startswith(("diff --git", "index ", "@@ ", "--- ", "+++ ")):
            continue
        if line[0] not in {"+", "-"}:
            continue
        changed_lines.append(line[1:])
    return bool(changed_lines) and all(_MARKER.search(line) or _FILE_MARKER.search(line) for line in changed_lines)


def _bundle_for_changed_specification_path(path: Path, specifications_root: Path) -> Path | None:
    root = specifications_root.resolve()
    current = path.resolve().parent
    while current == root or root in current.parents:
        if (current / "specification.yml").exists():
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


def _dedupe_evidence_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        key = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _spec_evidence_records(repo_root: Path) -> list[dict[str, Any]]:
    specs_root = Path(repo_root) / "docs" / "plans"
    if not specs_root.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(specs_root.glob("*/evidence/*")):
        if path.suffix not in SPEC_EVIDENCE_SUFFIXES:
            continue
        value = _load_yaml(path)
        evidence = value.get("evidence")
        if evidence is None:
            continue
        if not isinstance(evidence, list):
                raise SpecificationError(f"{path}: evidence must be a list")
        for index, record in enumerate(evidence, start=1):
            if not isinstance(record, dict):
                raise SpecificationError(f"{path}: evidence[{index}] must be a mapping")
            records.append(copy.deepcopy(record))
    return records


def _generation_evidence_records(repo_root: Path, existing_index: dict[str, Any]) -> list[dict[str, Any]]:
    return _dedupe_evidence_records([
        *_evidence_records(existing_index),
        *_spec_evidence_records(repo_root),
    ])


def check_generated_integrity(repo_root: Path, *, specifications_root: Path | None = None) -> list[str]:
    root = Path(repo_root).resolve()
    specification_root = (specifications_root or root / "specifications").resolve()
    generated = specification_root / "generated"
    expected_registry = build_registry(specification_root)
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
        except SpecificationError as exc:
            errors.append(str(exc))
    if errors:
        return errors
    if actual["registry.yml"] != expected_registry:
        return ["specifications/generated/registry.yml is stale; regenerate Specification artifacts"]
    expected_index = build_test_index(_repository_test_files(root), expected_registry, repo_root=root)
    expected_index, evidence_errors = apply_evidence(
        expected_registry,
        expected_index,
        _generation_evidence_records(root, actual["assertion-index.yml"]),
        repo_root=root,
        expected_subject_commit=_git_head(root),
        stale_evidence_is_error=False,
    )
    errors.extend(evidence_errors)
    expected = {
        "registry.yml": expected_registry,
        "assertion-index.yml": expected_index,
        "coverage.yml": build_coverage(expected_registry, expected_index),
    }
    for name, value in expected.items():
        if actual[name] != value:
            errors.append(f"specifications/generated/{name} is stale; regenerate Specification artifacts")
    return errors


def generate_specification_artifacts(repo_root: Path, *, specifications_root: Path | None = None) -> None:
    root = Path(repo_root).resolve()
    specification_root = (specifications_root or root / "specifications").resolve()
    generated = specification_root / "generated"
    registry = build_registry(specification_root)
    existing_index_path = generated / "assertion-index.yml"
    existing_index = _load_yaml(existing_index_path) if existing_index_path.exists() else {}
    test_index = build_test_index(_repository_test_files(root), registry, repo_root=root)
    test_index, evidence_errors = apply_evidence(
        registry,
        test_index,
        _generation_evidence_records(root, existing_index),
        repo_root=root,
        expected_subject_commit=_git_head(root),
        stale_evidence_is_error=False,
    )
    if evidence_errors:
        raise SpecificationError("\n".join(evidence_errors))
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
    """Return blocking Specification errors for changed tests and bundles only."""
    root = Path(repo_root)
    specifications_root = root / "specifications"
    try:
        registry = build_registry(specifications_root)
    except SpecificationError as exc:
        return [str(exc)]
    errors: list[str] = []
    bundles: set[Path] = set()
    verify_generated = False
    for relative in sorted(set(changed_paths)):
        path = root / relative
        if _is_test_file(relative) and path.exists():
            errors.extend(check_test_file(path, registry, changed=True))
            verify_generated = True
        if relative.startswith("docs/plans/") and Path(relative).name == "plan.yml" and path.exists():
            verify_generated = True
            errors.extend(
                verify_plan_specifications(
                    path,
                    specifications_root=specifications_root,
                    session_id=session_id,
                    approvals_path=approvals_path,
                )
            )
        if relative.startswith("specifications/"):
            verify_generated = True
            bundle_path = _bundle_for_changed_specification_path(path, specifications_root)
            if bundle_path:
                bundles.add(bundle_path)
            elif Path(relative).name == "specification.yml" and not path.exists():
                errors.append(f"{relative}: permanent Specifications cannot be deleted; supersede the Specification instead")
    for bundle_path in sorted(bundles):
        try:
            bundle = validate_bundle(bundle_path)
        except SpecificationError as exc:
            errors.append(f"{bundle_path}: {exc}")
            continue
        approval_error = check_approval(
            approvals_path,
            session_id,
            bundle.specification_id,
            bundle.fingerprint,
        )
        if approval_error:
            errors.append(approval_error)
    if verify_generated and (specifications_root / "generated").exists():
        try:
            errors.extend(check_generated_integrity(root, specifications_root=specifications_root))
        except SpecificationError as exc:
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


_TRAILER_KEYS = ("Specifications", "Assertions", "Plan", "Specification-Impact", "Specification-Exceptions")


def _parse_trailers(message: str) -> dict[str, list[str]]:
    trailers = {key: [] for key in _TRAILER_KEYS}
    for line in message.splitlines():
        for key in _TRAILER_KEYS:
            prefix = f"{key}:"
            if line.startswith(prefix):
                trailers[key].extend(item.strip() for item in line[len(prefix) :].split(",") if item.strip())
    return trailers


def validate_commit_trace(message: str, *, specification_governed: bool) -> list[str]:
    if not specification_governed:
        return []
    trailers = _parse_trailers(message)
    errors: list[str] = []
    for key in ("Specifications", "Assertions", "Plan", "Specification-Impact"):
        if not trailers[key]:
            errors.append(f"Specification-governed commit requires {key}: trailer")
    return errors


def build_release_summary(messages: list[str]) -> dict[str, Any]:
    values = {key: set() for key in _TRAILER_KEYS}
    for message in messages:
        for key, items in _parse_trailers(message).items():
            values[key].update(items)
    return {
        "schema_version": 1,
        "specifications": sorted(values["Specifications"]),
        "assertions": sorted(values["Assertions"]),
        "plans": sorted(values["Plan"]),
        "impacts": sorted(values["Specification-Impact"]),
        "approved_exceptions": sorted(values["Specification-Exceptions"]),
    }


def render_specification_reference(bundle: SpecificationBundle) -> str:
    lines = [f"# {bundle.specification['title']}", "", bundle.specification["summary"]]
    models = bundle.specification.get("models", {})
    if models:
        lines.extend(["", "## Models"])
        for model_name, fields in models.items():
            lines.extend(["", f"### {model_name}", "", "| Field | Type | Required | Constraints |", "| --- | --- | --- | --- |"])
            for field_name, definition in fields.items():
                constraints = json.dumps(definition.get("constraints", {}), sort_keys=True)
                lines.append(f"| `{field_name}` | `{definition['type']}` | {bool(definition.get('required'))} | `{constraints}` |")
    lines.extend(["", "## Assertions"])
    for assertion in bundle.specification["assertions"]:
        lines.append(f"- `{assertion['id']}`: {assertion['must']}")
    lines.extend(["", "## Applies to"])
    for surface in _required_surface_paths(bundle):
        lines.append(f"- `{surface}`")
    lines.extend(["", f"Bundle fingerprint: `{bundle.fingerprint}`", ""])
    return "\n".join(lines)


def archive_plans(
    active_root: Path,
    archive_root: Path,
    *,
    cooling_days: int,
    now: datetime,
) -> list[Path]:
    moved: list[Path] = []
    cutoff = now - timedelta(days=cooling_days)
    for path in sorted(Path(active_root).glob("*/plan.yml")):
        data = _load_yaml(path)
        modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        if data.get("status") != "verified" or modified > cutoff:
            continue
        if data.get("schema_version", 1) < 3 or not data.get("specification_refs"):
            continue
        if not isinstance(data.get("implementation_state"), dict) or not data["implementation_state"].get("subject_commit"):
            continue
        destination = Path(archive_root) / str(now.year) / path.parent.name / "plan.yml"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(destination))
        try:
            path.parent.rmdir()
        except OSError:
            pass
        moved.append(destination)
    return moved


def specification_command_names() -> set[str]:
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
        "archive-plans",
        "verify",
    }


def verify_plan_specifications(
    plan_path: Path,
    *,
    specifications_root: Path,
    session_id: str | None = None,
    approvals_path: Path = DEFAULT_APPROVALS_PATH,
) -> list[str]:
    try:
        from plan_validate import validate_plan

        data = validate_plan(plan_path)
    except (ImportError, ValueError) as exc:
        return [str(exc)]
    if data.get("schema_version", 1) < 3:
        return []
    try:
        registry = build_registry(specifications_root)
    except SpecificationError as exc:
        return [str(exc)]
    errors: list[str] = []
    specifications = registry.get("specifications", {})
    assertions = registry.get("assertions", {})
    for ref in data.get("specification_refs", []):
        record = specifications.get(ref["id"])
        if not record:
            errors.append(f"unknown Specification ref {ref['id']}@{ref['version']}")
        elif record.get("version") != ref["version"]:
            errors.append(f"Specification ref {ref['id']} expects version {ref['version']} but registry has {record.get('version')}")
    referenced_assertions: set[str] = set(data.get("specification_impact", {}).get("affected_assertions", []))
    for criterion in data.get("acceptance_criteria", []):
        referenced_assertions.update(criterion.get("specification_assertions", []))
    for test in data.get("tests", []):
        referenced_assertions.update(test.get("specification_assertions", []))
    for assertion_id in sorted(referenced_assertions):
        if assertion_id not in assertions:
            errors.append(f"unknown Specification assertion {assertion_id}")
    generated_current = (specifications_root / "generated" / "registry.yml").exists()
    errors.extend(check_documentation_impact(data.get("documentation_impact", {}), generated_current=generated_current))
    if data.get("status") == "verified":
        try:
            test_index = _load_yaml(specifications_root / "generated" / "assertion-index.yml")
            errors.extend(check_required_proof(registry, test_index, referenced_assertions))
        except SpecificationError as exc:
            errors.append(str(exc))
    if data.get("specification_impact", {}).get("specification_update_required") and session_id:
        for ref in data.get("specification_refs", []):
            if ref.get("role") != "primary" or ref["id"] not in specifications:
                continue
            error = check_approval(
                approvals_path,
                session_id,
                ref["id"],
                specifications[ref["id"]]["fingerprint"],
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
        raise SpecificationError(f"invalid approval state: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("sessions"), dict):
        raise SpecificationError("approval state must contain a sessions mapping")
    return value


def validate_review_artifact(path: Path, bundle: SpecificationBundle) -> dict[str, str]:
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecificationError(f"invalid Specification review artifact: {exc}") from exc
    if not isinstance(artifact, dict):
        raise SpecificationError("Specification review artifact must contain a JSON object")
    if artifact.get("specification") != bundle.versioned_id or artifact.get("fingerprint") != bundle.fingerprint:
        raise SpecificationError("Specification review artifact does not match the current bundle fingerprint")
    pdf_value = artifact.get("pdf")
    pdf_sha256 = artifact.get("pdf_sha256")
    baseline_ref = artifact.get("baseline_ref")
    baseline_commit = artifact.get("baseline_commit")
    if not all(isinstance(value, str) and value for value in (pdf_value, pdf_sha256, baseline_ref, baseline_commit)):
        raise SpecificationError("Specification review artifact requires pdf, pdf_sha256, baseline_ref, and baseline_commit")
    pdf = Path(pdf_value).expanduser().resolve()
    if not pdf.is_file() or hashlib.sha256(pdf.read_bytes()).hexdigest() != pdf_sha256:
        raise SpecificationError("Specification review artifact PDF is missing or its hash does not match")
    highlight_policy = artifact.get("highlight_policy")
    if highlight_policy != {
        "additions": "inline_green_plus",
        "removals": "inline_red_minus",
        "unchanged": "neutral",
        "granularity": "changed_text_only",
    }:
        raise SpecificationError("Specification review artifact does not declare the required inline red/green text-diff policy")
    publication = artifact.get("publication")
    if artifact.get("approval_eligible") is not True or not isinstance(publication, dict):
        raise SpecificationError("Specification review artifact requires a privately uploaded PDF publication")
    if not all(isinstance(publication.get(field), str) and publication[field] for field in ("bucket", "key", "sha256")):
        raise SpecificationError("Specification review artifact publication requires bucket, key, and sha256")
    if publication["sha256"] != f"sha256:{pdf_sha256}":
        raise SpecificationError("Specification review artifact publication hash does not match the PDF")
    return {
        "path": str(path.resolve()),
        "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "pdf_sha256": pdf_sha256,
        "baseline_ref": baseline_ref,
        "baseline_commit": baseline_commit,
        "fingerprint": bundle.fingerprint,
    }


def record_approval(
    path: Path,
    *,
    session_id: str,
    specification_id: str,
    fingerprint: str,
    confirmation: str,
    review_artifact: dict[str, str],
) -> None:
    if confirmation != "explicit_user_confirmation":
        raise SpecificationError("approval requires explicit_user_confirmation")
    for value, field in ((session_id, "session_id"), (specification_id, "specification_id"), (fingerprint, "fingerprint")):
        _non_empty_string(value, field)
    state = _load_approvals(path)
    sessions = state.setdefault("sessions", {})
    specifications = sessions.setdefault(session_id, {})
    specifications[specification_id] = {
        "fingerprint": fingerprint,
        "confirmation": confirmation,
        "approved_at": datetime.now(UTC).isoformat(),
        "review_artifact": copy.deepcopy(review_artifact),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fingerprint_manifest_sha256(specification_fingerprints: dict[str, str]) -> str:
    encoded = json.dumps(
        specification_fingerprints,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_batch_review_artifact(
    review_artifact: dict[str, Any],
    specification_fingerprints: dict[str, str],
) -> None:
    if review_artifact.get("approval_kind") != "plan_batch":
        raise SpecificationError("batch approval review artifact requires approval_kind=plan_batch")
    expected_manifest = _fingerprint_manifest_sha256(specification_fingerprints)
    if review_artifact.get("fingerprint_manifest_sha256") != expected_manifest:
        raise SpecificationError("batch approval review artifact fingerprint manifest does not match")
    if not isinstance(review_artifact.get("plan_path"), str) or not review_artifact["plan_path"].strip():
        raise SpecificationError("batch approval review artifact requires plan_path")
    if not isinstance(review_artifact.get("plan_sha256"), str) or not review_artifact["plan_sha256"].strip():
        raise SpecificationError("batch approval review artifact requires plan_sha256")
    if review_artifact.get("specification_count") != len(specification_fingerprints):
        raise SpecificationError("batch approval review artifact specification_count does not match")


def record_batch_approval(
    path: Path,
    *,
    session_id: str,
    approval_id: str,
    specification_fingerprints: dict[str, str],
    confirmation: str,
    review_artifact: dict[str, Any],
) -> None:
    if confirmation != "explicit_user_confirmation":
        raise SpecificationError("approval requires explicit_user_confirmation")
    _non_empty_string(session_id, "session_id")
    _non_empty_string(approval_id, "approval_id")
    if not specification_fingerprints:
        raise SpecificationError("batch approval requires at least one Specification fingerprint")
    for specification_id, fingerprint in specification_fingerprints.items():
        _non_empty_string(specification_id, "specification_id")
        _non_empty_string(fingerprint, "fingerprint")
    _validate_batch_review_artifact(review_artifact, specification_fingerprints)
    state = _load_approvals(path)
    sessions = state.setdefault("sessions", {})
    session = sessions.setdefault(session_id, {})
    batches = session.setdefault(BATCH_APPROVALS_KEY, {})
    batches[approval_id] = {
        "confirmation": confirmation,
        "approved_at": datetime.now(UTC).isoformat(),
        "specification_fingerprints": copy.deepcopy(specification_fingerprints),
        "review_artifact": copy.deepcopy(review_artifact),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _check_batch_approval(session: dict[str, Any], session_id: str, specification_id: str, fingerprint: str) -> str | None:
    batches = session.get(BATCH_APPROVALS_KEY)
    if not isinstance(batches, dict):
        return f"missing approval for {specification_id} in session {session_id}"
    stale = False
    for approval_id, record in batches.items():
        if not isinstance(record, dict):
            continue
        specification_fingerprints = record.get("specification_fingerprints")
        if not isinstance(specification_fingerprints, dict) or specification_id not in specification_fingerprints:
            continue
        if record.get("confirmation") != "explicit_user_confirmation":
            return f"unconfirmed batch approval {approval_id} for {specification_id}"
        if specification_fingerprints.get(specification_id) != fingerprint:
            stale = True
            continue
        review_artifact = record.get("review_artifact")
        if not isinstance(review_artifact, dict):
            return f"unreviewed batch approval {approval_id} for {specification_id}: matching Plan review artifact is required"
        try:
            _validate_batch_review_artifact(
                review_artifact,
                {str(key): str(value) for key, value in specification_fingerprints.items()},
            )
        except SpecificationError:
            return f"unreviewed batch approval {approval_id} for {specification_id}: matching Plan review artifact is required"
        return None
    if stale:
        return f"stale batch approval for {specification_id}: bundle fingerprint changed"
    return f"missing approval for {specification_id} in session {session_id}"


def check_approval(path: Path, session_id: str, specification_id: str, fingerprint: str) -> str | None:
    session = _load_approvals(path).get("sessions", {}).get(session_id, {})
    if not isinstance(session, dict):
        return f"missing approval for {specification_id} in session {session_id}"
    record = session.get(specification_id)
    if not isinstance(record, dict):
        batch_error = _check_batch_approval(session, session_id, specification_id, fingerprint)
        if batch_error is None:
            return None
        if batch_error.startswith(("stale ", "unconfirmed ", "unreviewed ")):
            return batch_error
        return f"missing approval for {specification_id} in session {session_id}"
    if record.get("confirmation") != "explicit_user_confirmation":
        return f"unconfirmed approval for {specification_id}"
    if record.get("fingerprint") != fingerprint:
        return f"stale approval for {specification_id}: bundle fingerprint changed"
    review_artifact = record.get("review_artifact")
    if not isinstance(review_artifact, dict) or review_artifact.get("fingerprint") != fingerprint:
        return f"unreviewed approval for {specification_id}: matching PDF review artifact is required"
    return None


def _approved_plan_batch_review_artifact(plan_path: Path, specification_fingerprints: dict[str, str]) -> dict[str, Any]:
    plan = _load_yaml(plan_path)
    approvals = plan.get("approvals")
    if not isinstance(approvals, dict):
        raise SpecificationError("batch approval Plan requires approvals")
    specification_approval = approvals.get("specification")
    plan_approval = approvals.get("plan")
    if not isinstance(specification_approval, dict) or specification_approval.get("status") != "approved":
        raise SpecificationError("batch approval Plan requires approvals.specification.status=approved")
    if not isinstance(plan_approval, dict) or plan_approval.get("status") != "approved":
        raise SpecificationError("batch approval Plan requires approvals.plan.status=approved")
    clarification = plan.get("clarification")
    approved_by_user = (
        plan.get("approved_by_user") is True
        or isinstance(clarification, dict) and clarification.get("approved_by_user") is True
    )
    if not approved_by_user:
        raise SpecificationError("batch approval Plan requires approved_by_user=true")
    manifest_sha256 = _fingerprint_manifest_sha256(specification_fingerprints)
    return {
        "approval_kind": "plan_batch",
        "plan_path": str(plan_path.resolve()),
        "plan_id": str(plan.get("id") or ""),
        "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "fingerprint_manifest_sha256": manifest_sha256,
        "specification_count": len(specification_fingerprints),
    }


def _write_output(value: dict[str, Any], output: Path | None, as_json: bool) -> None:
    rendered = json.dumps(value, indent=2, sort_keys=True) if as_json else yaml.safe_dump(value, sort_keys=False).rstrip()
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


def _resolve_specification_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and trace OpenMates Specifications")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate one bundle or all bundles")
    validate.add_argument("path", nargs="?", default=str(DEFAULT_SPECIFICATIONS_ROOT))
    validate.add_argument("--json", action="store_true")

    registry = subparsers.add_parser("registry", help="Build deterministic Specification and assertion registry")
    registry.add_argument("--specifications-root", default=str(DEFAULT_SPECIFICATIONS_ROOT))
    registry.add_argument("--output", type=Path)
    registry.add_argument("--json", action="store_true")

    coverage = subparsers.add_parser("coverage", help="Report Specification and proof coverage")
    coverage.add_argument("--specifications-root", default=str(DEFAULT_SPECIFICATIONS_ROOT))
    coverage.add_argument("--test-index", type=Path)
    coverage.add_argument("--output", type=Path)
    coverage.add_argument("--json", action="store_true")

    fingerprint = subparsers.add_parser("fingerprint", help="Print exact bundle fingerprint")
    fingerprint.add_argument("bundle")

    approve = subparsers.add_parser("approve", help="Record explicit user approval for exact bundle hash")
    approve.add_argument("bundle")
    approve.add_argument("--session", required=True)
    approve.add_argument("--confirmation", required=True, choices=["explicit_user_confirmation"])
    approve.add_argument("--review-artifact", type=Path, required=True)
    approve.add_argument("--approvals-file", type=Path, default=DEFAULT_APPROVALS_PATH)

    approve_batch = subparsers.add_parser("approve-batch", help="Record Plan-backed approval for multiple exact Specification hashes")
    approve_batch.add_argument("bundles", nargs="+")
    approve_batch.add_argument("--session", required=True)
    approve_batch.add_argument("--approval-id", required=True)
    approve_batch.add_argument("--confirmation", required=True, choices=["explicit_user_confirmation"])
    approve_batch.add_argument("--plan", type=Path, required=True)
    approve_batch.add_argument("--approvals-file", type=Path, default=DEFAULT_APPROVALS_PATH)

    approval = subparsers.add_parser("check-approval", help="Check exact-hash session approval")
    approval.add_argument("bundle")
    approval.add_argument("--session", required=True)
    approval.add_argument("--approvals-file", type=Path, default=DEFAULT_APPROVALS_PATH)

    check_test = subparsers.add_parser("check-test", help="Validate Specification assertion metadata in one changed test file")
    check_test.add_argument("path")
    check_test.add_argument("--specifications-root", default=str(DEFAULT_SPECIFICATIONS_ROOT))

    test_index = subparsers.add_parser("index-tests", help="Build assertion-to-test index")
    test_index.add_argument("paths", nargs="+")
    test_index.add_argument("--specifications-root", default=str(DEFAULT_SPECIFICATIONS_ROOT))
    test_index.add_argument("--output", type=Path)
    test_index.add_argument("--json", action="store_true")

    evidence = subparsers.add_parser("apply-evidence", help="Attach fingerprint-bound run evidence to an assertion index")
    evidence.add_argument("evidence", type=Path)
    evidence.add_argument("--test-index", type=Path, required=True)
    evidence.add_argument("--specifications-root", default=str(DEFAULT_SPECIFICATIONS_ROOT))
    evidence.add_argument("--output", type=Path, required=True)

    generated = subparsers.add_parser("check-generated", help="Reject stale registry, assertion index, or coverage artifacts")
    generated.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    generated.add_argument("--specifications-root", type=Path)

    generate = subparsers.add_parser("generate", help="Regenerate registry, assertion index, and coverage together")
    generate.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    generate.add_argument("--specifications-root", type=Path)

    changed = subparsers.add_parser("check-changed", help="Block unresolved changed tests or Specification approvals")
    changed.add_argument("paths", nargs="+")
    changed.add_argument("--session", required=True)
    changed.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    changed.add_argument("--approvals-file", type=Path, default=DEFAULT_APPROVALS_PATH)

    docs = subparsers.add_parser("docs", help="Generate deterministic Markdown references from Specifications")
    docs.add_argument("bundle")
    docs.add_argument("--output", type=Path, required=True)

    release = subparsers.add_parser("release-summary", help="Aggregate Specification trailers from commit-message files")
    release.add_argument("messages", nargs="*", type=Path)
    release.add_argument("--git-range")
    release.add_argument("--output", type=Path)
    release.add_argument("--json", action="store_true")

    archive = subparsers.add_parser("archive-plans", help="Move complete cooled Plans to year archives")
    archive.add_argument("--active-root", type=Path, default=REPO_ROOT / "docs" / "plans" / "active")
    archive.add_argument("--archive-root", type=Path, default=REPO_ROOT / "docs" / "plans" / "archive")
    archive.add_argument("--cooling-days", type=int, default=30)

    verify = subparsers.add_parser("verify", help="Verify a Plan's permanent Specification references and impacts")
    verify.add_argument("--plan", type=Path, required=True)
    verify.add_argument("--specifications-root", type=Path, default=DEFAULT_SPECIFICATIONS_ROOT)
    verify.add_argument("--session")
    verify.add_argument("--approvals-file", type=Path, default=DEFAULT_APPROVALS_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            path = _resolve_specification_path(args.path)
            bundles = discover_bundles(path) if path.is_dir() and not (path / "specification.yml").exists() else [validate_bundle(path)]
            result = {"status": "passed", "bundles": [{"specification": bundle.versioned_id, "fingerprint": bundle.fingerprint} for bundle in bundles]}
            _write_output(result, None, args.json)
        elif args.command == "registry":
            _write_output(build_registry(_resolve_specification_path(args.specifications_root)), args.output, args.json)
        elif args.command == "coverage":
            registry = build_registry(_resolve_specification_path(args.specifications_root))
            test_index = _load_yaml(args.test_index) if args.test_index else {}
            _write_output(build_coverage(registry, test_index), args.output, args.json)
        elif args.command == "fingerprint":
            print(validate_bundle(_resolve_specification_path(args.bundle)).fingerprint)
        elif args.command == "approve":
            bundle = validate_bundle(_resolve_specification_path(args.bundle))
            review_artifact = validate_review_artifact(args.review_artifact, bundle)
            record_approval(
                args.approvals_file,
                session_id=args.session,
                specification_id=bundle.specification_id,
                fingerprint=bundle.fingerprint,
                confirmation=args.confirmation,
                review_artifact=review_artifact,
            )
            print(f"APPROVED {bundle.versioned_id} {bundle.fingerprint}")
        elif args.command == "approve-batch":
            bundles = [validate_bundle(_resolve_specification_path(bundle)) for bundle in args.bundles]
            specification_fingerprints = {
                bundle.specification_id: bundle.fingerprint
                for bundle in bundles
            }
            if len(specification_fingerprints) != len(bundles):
                raise SpecificationError("batch approval bundles must have unique Specification IDs")
            plan_path = args.plan if args.plan.is_absolute() else Path.cwd() / args.plan
            review_artifact = _approved_plan_batch_review_artifact(plan_path.resolve(), specification_fingerprints)
            record_batch_approval(
                args.approvals_file,
                session_id=args.session,
                approval_id=args.approval_id,
                specification_fingerprints=specification_fingerprints,
                confirmation=args.confirmation,
                review_artifact=review_artifact,
            )
            print(
                f"APPROVED-BATCH {args.approval_id} "
                f"{len(specification_fingerprints)} {review_artifact['fingerprint_manifest_sha256']}"
            )
        elif args.command == "check-approval":
            bundle = validate_bundle(_resolve_specification_path(args.bundle))
            error = check_approval(args.approvals_file, args.session, bundle.specification_id, bundle.fingerprint)
            if error:
                raise SpecificationError(error)
            print(f"PASS {bundle.versioned_id}: exact bundle hash approved")
        elif args.command == "check-test":
            registry = build_registry(_resolve_specification_path(args.specifications_root))
            errors = check_test_file(_resolve_specification_path(args.path), registry, changed=True)
            if errors:
                raise SpecificationError("\n".join(errors))
            print(f"PASS {args.path}: contract-test metadata valid")
        elif args.command == "index-tests":
            registry = build_registry(_resolve_specification_path(args.specifications_root))
            paths = [_resolve_specification_path(path) for path in args.paths]
            _write_output(build_test_index(paths, registry, repo_root=REPO_ROOT), args.output, args.json)
        elif args.command == "apply-evidence":
            merged_worktree_error = _merged_session_worktree_error(REPO_ROOT)
            if merged_worktree_error:
                raise SpecificationError(merged_worktree_error)
            registry = build_registry(_resolve_specification_path(args.specifications_root))
            test_index_value = _load_yaml(args.test_index)
            evidence_value = _load_yaml(args.evidence)
            records = evidence_value.get("evidence")
            if not isinstance(records, list):
                raise SpecificationError("evidence file must contain an evidence list")
            result, errors = apply_evidence(
                registry,
                test_index_value,
                records,
                repo_root=REPO_ROOT,
                expected_subject_commit=_git_head(REPO_ROOT),
            )
            if errors:
                raise SpecificationError("\n".join(errors))
            _write_output(result, args.output, False)
        elif args.command == "check-generated":
            errors = check_generated_integrity(
                args.repo_root,
                specifications_root=args.specifications_root,
            )
            if errors:
                raise SpecificationError("\n".join(errors))
            print("PASS: generated Specification artifacts are current")
        elif args.command == "generate":
            generate_specification_artifacts(args.repo_root, specifications_root=args.specifications_root)
            print("WROTE: generated Specification registry, assertion index, and coverage")
        elif args.command == "check-changed":
            errors = check_changed_files(
                args.repo_root,
                args.paths,
                session_id=args.session,
                approvals_path=args.approvals_file,
            )
            if errors:
                raise SpecificationError("\n".join(errors))
            print(f"PASS: {len(args.paths)} changed path(s) satisfy Specification gates")
        elif args.command == "docs":
            bundle = validate_bundle(_resolve_specification_path(args.bundle))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(render_specification_reference(bundle), encoding="utf-8")
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
                    raise SpecificationError(result.stderr.strip() or "git log failed")
                messages.extend(message for message in result.stdout.split("\x00") if message.strip())
            if not messages:
                raise SpecificationError("release-summary requires message files or --git-range")
            _write_output(build_release_summary(messages), args.output, args.json)
        elif args.command == "archive-plans":
            moved = archive_plans(
                args.active_root,
                args.archive_root,
                cooling_days=args.cooling_days,
                now=datetime.now(UTC),
            )
            print(f"ARCHIVED {len(moved)} Plan(s)")
        elif args.command == "verify":
            errors = verify_plan_specifications(
                _resolve_specification_path(args.plan),
                specifications_root=args.specifications_root,
                session_id=args.session,
                approvals_path=args.approvals_file,
            )
            if errors:
                raise SpecificationError("\n".join(errors))
            print(f"PASS {args.plan}: Specification references and impacts valid")
    except (SpecificationError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
