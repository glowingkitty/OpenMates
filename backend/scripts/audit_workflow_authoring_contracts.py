"""Deterministically check every enabled Workflow skill's authoring contract.

Run with the backend Python environment; no providers, dispatch, writes, or AI
requests are used. Examples are compiled through the actual flat-node parser,
and every declared output must support a typed reference in a complete graph.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from backend.core.api.app.services.workflow_authoring_compiler import (
    FlatAuthoringAccumulator, compile_authoring_plan,
)
from backend.core.api.app.services.workflow_authoring_preselection import WorkflowPreselection
from backend.core.api.app.services.workflow_capability_registry import (
    WorkflowCapabilityRegistry, _FilesystemWorkflowMetadataRegistry,
)
from backend.core.api.app.services.workflow_runtime_values import resolve_workflow_runtime_values


@dataclass(frozen=True)
class ContractIssue:
    capability_id: str
    code: str
    field: str | None = None


def audit_authoring_contracts(registry: WorkflowCapabilityRegistry | None = None) -> dict[str, Any]:
    """Return aggregate coverage and fixed, privacy-safe failure identifiers."""
    registry = registry or WorkflowCapabilityRegistry(_FilesystemWorkflowMetadataRegistry())
    capabilities = registry.list_capabilities()
    issues: list[ContractIssue] = []
    reference_count = 0
    enabled = [capability for capability in capabilities if capability.enabled]
    for capability in enabled:
        try:
            input_schema = capability.metadata["input_schema"]
            output_schema = capability.metadata["output_schema"]
            Draft202012Validator.check_schema(input_schema)
            Draft202012Validator.check_schema(output_schema)
            example = deepcopy(capability.metadata["workflow"]["test_example_input"])
            resolved = resolve_workflow_runtime_values(example, now=1780000000)
            Draft202012Validator(input_schema).validate(resolved)
        except (KeyError, TypeError, ValueError, SchemaError, ValidationError):
            issues.append(ContractIssue(capability.id, "INVALID_CONTRACT_OR_EXAMPLE"))
            continue
        selection = WorkflowPreselection([capability], "create", "none", True, {}, {})
        header = {"operation": "create", "title": "Skill contract check",
                  "description": "Offline authoring validation", "icon": "search",
                  "schedule": {"type": "manual"}}
        source = ({"kind": "ask_ai", "id": "source",
                   "prompt_json": json.dumps([{"text": example["prompt"]}])}
                  if capability.id == "ai.ask" else
                  {"kind": "app", "id": "source", "capability": capability.id,
                   "input_json": json.dumps(example)})

        def compile_with_reference(field: str) -> None:
            accumulator = FlatAuthoringAccumulator(selection, "UTC")
            accumulator.accept_header(header)
            accumulator.accept_node(source)
            accumulator.accept_node({
                "kind": "send", "id": "deliver", "title": "Result",
                "message_json": json.dumps([{"ref": {"step": "source", "field": field}}]),
            })
            compile_authoring_plan(accumulator.snapshot(), selection, "UTC")

        fields = output_schema.get("properties") or {}
        if not fields:
            issues.append(ContractIssue(capability.id, "NO_DECLARED_OUTPUT_FIELDS"))
        for field in fields:
            reference_count += 1
            try:
                compile_with_reference(field)
            except (KeyError, TypeError, ValueError):
                issues.append(ContractIssue(capability.id, "OUTPUT_REFERENCE_REJECTED", field))
        try:
            compile_with_reference("__undeclared_workflow_output__")
        except (KeyError, TypeError, ValueError):
            pass
        else:
            issues.append(ContractIssue(capability.id, "UNDECLARED_OUTPUT_ACCEPTED"))

        invalid = deepcopy(source)
        if capability.id == "ai.ask":
            invalid["prompt_json"] = json.dumps({"text": "Not a segment array"})
        else:
            invalid["input_json"] = json.dumps({**example, "__undeclared_input__": True})
        accumulator = FlatAuthoringAccumulator(selection, "UTC")
        accumulator.accept_header(header)
        try:
            accumulator.accept_node(invalid)
        except (KeyError, TypeError, ValueError):
            if accumulator.records:
                issues.append(ContractIssue(capability.id, "REJECTED_NODE_MUTATED_PREFIX"))
        else:
            issues.append(ContractIssue(capability.id, "INVALID_INPUT_ACCEPTED"))

    return {
        "checked_skills": len(enabled), "checked_output_references": reference_count,
        "checked_input_rejections": len(enabled), "checked_unknown_output_rejections": len(enabled),
        "checked_ids": [capability.id for capability in enabled],
        "excluded": {capability.id: capability.reason for capability in capabilities if not capability.enabled},
        "issues": [asdict(issue) for issue in issues],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = audit_authoring_contracts()
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{'FAIL' if result['issues'] else 'PASS'}: {result['checked_skills']} enabled skills, "
              f"{result['checked_output_references']} output references, "
              f"{result['checked_input_rejections']} invalid-input and unknown-output checks")
        for issue in result["issues"]:
            print(f"{issue['capability_id']}: {issue['code']} {issue['field'] or ''}".rstrip())
    return bool(result["issues"])


if __name__ == "__main__":
    raise SystemExit(main())
