#!/usr/bin/env python3
"""Audit user-perspective npm and pip SDK parity.

Purpose: keep public SDK namespace method names, inputs, and outputs aligned
across TypeScript and Python.
Architecture: explicit manifest of durable SDK surface pairs with idiomatic
camelCase/snake_case names.
Security: cleartext public methods must remain equivalent regardless of SDK
language, with encryption hidden inside both clients.
Spec: docs/specs/sdk-cleartext-encryption-boundary/spec.yml.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
SDK_TS = ROOT / "frontend/packages/openmates-cli/src/sdk.ts"
SDK_PY = ROOT / "packages/openmates-python/openmates/sdk.py"


@dataclass(frozen=True)
class MethodPair:
    npm_class: str
    npm_method: str
    pip_class: str
    pip_method: str
    npm_inputs: tuple[str, ...]
    pip_inputs: tuple[str, ...]
    npm_output: str
    pip_output: str


METHODS = [
    MethodPair("OpenMatesProjects", "list", "OpenMatesProjects", "list", ("includeArchived",), ("include_archived",), "ProjectRecordPlain[]", "list[dict[str, Any]]"),
    MethodPair("OpenMatesProjects", "create", "OpenMatesProjects", "create", ("input",), ("payload",), "ProjectRecordPlain", "dict[str, Any]"),
    MethodPair("OpenMatesProjects", "history", "OpenMatesProjects", "history", ("projectId", "limit"), ("project_id", "limit"), "Record<string, unknown>[]", "list[dict[str, Any]]"),
    MethodPair("OpenMatesProjects", "restore", "OpenMatesProjects", "restore", ("projectId", "entryId", "state"), ("project_id", "entry_id", "state"), "Record<string, unknown>", "dict[str, Any]"),
    MethodPair("OpenMatesProjects", "ask", "OpenMatesProjects", "ask", ("instruction", "create", "update", "updates", "exactDelete", "exactDeletes"), ("instruction", "create", "update", "updates", "exact_delete", "exact_deletes"), "Record<string, unknown>", "dict[str, Any]"),
    MethodPair("OpenMatesTasks", "list", "OpenMatesTasks", "list", ("filters",), ("status", "chat_id", "project_id", "plan_id", "labels", "tags", "priority"), "TaskRecord[]", "list[dict[str, Any]]"),
    MethodPair("OpenMatesTasks", "listDecrypted", "OpenMatesTasks", "list_decrypted", ("filters",), ("status", "chat_id", "project_id", "plan_id", "labels", "tags", "priority"), "TaskRecord[]", "list[dict[str, Any]]"),
    MethodPair("OpenMatesTasks", "show", "OpenMatesTasks", "show", ("id", "filters"), ("task_id", "filters"), "TaskRecord", "dict[str, Any]"),
    MethodPair("OpenMatesTasks", "history", "OpenMatesTasks", "history", ("id", "filters", "limit"), ("task_id", "limit", "filters"), "Record<string, unknown>[]", "list[dict[str, Any]]"),
    MethodPair("OpenMatesTasks", "restore", "OpenMatesTasks", "restore", ("id", "entryId", "state", "filters"), ("task_id", "entry_id", "state", "filters"), "Record<string, unknown>", "dict[str, Any]"),
    MethodPair("OpenMatesTasks", "ask", "OpenMatesTasks", "ask", ("instruction", "create", "creates", "update", "updates", "exactDelete", "exactDeletes"), ("instruction", "create", "creates", "update", "updates", "exact_delete", "exact_deletes"), "Record<string, unknown>", "dict[str, Any]"),
    MethodPair("OpenMatesTasks", "create", "OpenMatesTasks", "create", ("input",), ("payload",), "TaskRecord", "dict[str, Any]"),
    MethodPair("OpenMatesTasks", "update", "OpenMatesTasks", "update", ("id", "input", "filters"), ("task_id", "payload", "filters"), "TaskRecord", "dict[str, Any]"),
    MethodPair("OpenMatesTasks", "edit", "OpenMatesTasks", "edit", ("id", "input", "filters"), ("task_id", "payload", "filters"), "TaskRecord", "dict[str, Any]"),
    MethodPair("OpenMatesTasks", "addToProject", "OpenMatesTasks", "add_to_project", ("id", "projectId", "options"), ("task_id", "project_id", "filters"), "TaskRecord", "dict[str, Any]"),
    MethodPair("OpenMatesTasks", "start", "OpenMatesTasks", "start", ("id", "filters"), ("task_id", "filters"), "TaskRecord", "dict[str, Any]"),
    MethodPair("OpenMatesTasks", "startAI", "OpenMatesTasks", "start_ai", ("id", "filters"), ("task_id", "payload"), "TaskRecord", "dict[str, Any]"),
    MethodPair("OpenMatesTasks", "delete", "OpenMatesTasks", "delete", ("id", "options"), ("task_id", "confirmed", "filters"), "deleted", "dict[str, Any]"),
    MethodPair("OpenMatesTasks", "done", "OpenMatesTasks", "done", ("id", "filters"), ("task_id", "filters"), "TaskRecord", "dict[str, Any]"),
    MethodPair("OpenMatesTasks", "complete", "OpenMatesTasks", "complete", ("id", "filters"), ("task_id", "filters"), "TaskRecord", "dict[str, Any]"),
    MethodPair("OpenMatesTasks", "block", "OpenMatesTasks", "block", ("id", "reason", "filters"), ("task_id", "reason", "filters"), "TaskRecord", "dict[str, Any]"),
    MethodPair("OpenMatesTasks", "unblock", "OpenMatesTasks", "unblock", ("id", "filters"), ("task_id", "filters"), "TaskRecord", "dict[str, Any]"),
    MethodPair("OpenMatesTasks", "skip", "OpenMatesTasks", "skip", ("id", "filters"), ("task_id", "filters"), "TaskRecord", "dict[str, Any]"),
    MethodPair("OpenMatesTasks", "reorder", "OpenMatesTasks", "reorder", ("id", "move", "filters"), ("task_id", "move", "filters"), "TaskRecord[]", "list[dict[str, Any]]"),
    MethodPair("OpenMatesTasks", "move", "OpenMatesTasks", "move", ("id", "move", "filters"), ("task_id", "move", "filters"), "TaskRecord[]", "list[dict[str, Any]]"),
    MethodPair("OpenMatesPlans", "list", "OpenMatesPlans", "list", ("status", "chatId", "projectId", "activeOnly"), ("status", "chat_id", "project_id", "active_only"), "PlanRecord[]", "list[dict[str, Any]]"),
    MethodPair("OpenMatesPlans", "create", "OpenMatesPlans", "create", ("input",), ("payload",), "PlanRecord", "dict[str, Any]"),
    MethodPair("OpenMatesPlans", "show", "OpenMatesPlans", "show", ("planId",), ("plan_id",), "PlanRecord", "dict[str, Any]"),
    MethodPair("OpenMatesPlans", "update", "OpenMatesPlans", "update", ("planId", "input"), ("plan_id", "payload"), "PlanRecord", "dict[str, Any]"),
    MethodPair("OpenMatesPlans", "addToProject", "OpenMatesPlans", "add_to_project", ("planId", "projectId"), ("plan_id", "project_id"), "PlanRecord", "dict[str, Any]"),
    MethodPair("OpenMatesPlans", "history", "OpenMatesPlans", "history", ("planId", "limit"), ("plan_id", "limit"), "Record<string, unknown>[]", "list[dict[str, Any]]"),
    MethodPair("OpenMatesPlans", "restore", "OpenMatesPlans", "restore", ("planId", "entryId", "state"), ("plan_id", "entry_id", "state"), "Record<string, unknown>", "dict[str, Any]"),
    MethodPair("OpenMatesPlans", "ask", "OpenMatesPlans", "ask", ("instruction", "create", "update", "updates"), ("instruction", "create", "update", "updates"), "Record<string, unknown>", "dict[str, Any]"),
    MethodPair("OpenMatesPlans", "activate", "OpenMatesPlans", "activate", ("planId", "chatId"), ("plan_id", "chat_id"), "PlanRecord", "dict[str, Any]"),
    MethodPair("OpenMatesPlans", "attach", "OpenMatesPlans", "attach", ("planId", "chatId"), ("plan_id", "chat_id"), "PlanRecord", "dict[str, Any]"),
    MethodPair("OpenMatesPlans", "start", "OpenMatesPlans", "start", ("planId",), ("plan_id",), "PlanRecord", "dict[str, Any]"),
    MethodPair("OpenMatesPlans", "resume", "OpenMatesPlans", "resume", ("planId",), ("plan_id",), "PlanRecord", "dict[str, Any]"),
    MethodPair("OpenMatesPlans", "complete", "OpenMatesPlans", "complete", ("planId",), ("plan_id",), "PlanRecord", "dict[str, Any]"),
]


def class_body(source: str, class_name: str, *, language: str) -> str:
    marker = f"export class {class_name}" if language == "ts" else f"class {class_name}:"
    start = source.index(marker)
    next_marker = "\nexport class " if language == "ts" else "\nclass "
    end = source.find(next_marker, start + 1)
    return source[start:] if end == -1 else source[start:end]


def _scan_balanced(source: str, start: int, opener: str, closer: str) -> int:
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"Unbalanced {opener}{closer} block")


def _camel_to_snake(value: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value).lower()


def _normalized_text(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", " ", _camel_to_snake(value)).lower()
    return " ".join(part.strip("_") for part in normalized.split() if part.strip("_"))


def _missing_tokens(text: str, expected: tuple[str, ...]) -> list[str]:
    normalized = f" {_normalized_text(text)} "
    return [token for token in expected if f" {_normalized_text(token).strip()} " not in normalized]


def _missing_output_tokens(text: str, expected: str) -> list[str]:
    normalized = f" {_normalized_text(text)} "
    return [token for token in _normalized_text(expected).split() if f" {token} " not in normalized]


def npm_method_signature(source: str, class_name: str, method: str) -> str | None:
    body = class_body(source, class_name, language="ts")
    match = re.search(rf"\n\s{{2}}(?:async\s+)?(?:\*\s*)?{re.escape(method)}\s*\(", body)
    if not match:
        return None
    open_paren = body.index("(", match.start())
    close_paren = _scan_balanced(body, open_paren, "(", ")")
    open_brace = -1
    angle_depth = 0
    for index in range(close_paren, len(body)):
        char = body[index]
        if char == "<":
            angle_depth += 1
        elif char == ">" and angle_depth > 0:
            angle_depth -= 1
        elif char == "{" and angle_depth == 0:
            open_brace = index
            break
    if open_brace == -1:
        return body[match.start():close_paren + 1]
    return body[match.start():open_brace]


def pip_method_signature(source: str, class_name: str, method: str) -> str | None:
    body = class_body(source, class_name, language="py")
    match = re.search(rf"\n\s{{4}}def\s+{re.escape(method)}\s*\(", body)
    if not match:
        return None
    open_paren = body.index("(", match.start())
    close_paren = _scan_balanced(body, open_paren, "(", ")")
    line_end = body.find("\n", close_paren)
    return body[match.start():line_end if line_end != -1 else close_paren + 1]


def check_signature(*, signature: str | None, class_name: str, method: str, inputs: tuple[str, ...], output: str, sdk_name: str) -> list[str]:
    if signature is None:
        return [f"Missing {sdk_name} SDK method {class_name}.{method}"]
    failures: list[str] = []
    missing_inputs = _missing_tokens(signature, inputs)
    if missing_inputs:
        failures.append(f"{sdk_name} SDK method {class_name}.{method} missing input token(s): {', '.join(missing_inputs)}")
    missing_outputs = _missing_output_tokens(signature, output)
    if missing_outputs:
        failures.append(f"{sdk_name} SDK method {class_name}.{method} missing output token(s) for {output}: {', '.join(missing_outputs)}")
    return failures


def main() -> int:
    sdk_ts = SDK_TS.read_text(encoding="utf-8")
    sdk_py = SDK_PY.read_text(encoding="utf-8")
    failures: list[str] = []
    for method in METHODS:
        failures.extend(check_signature(
            signature=npm_method_signature(sdk_ts, method.npm_class, method.npm_method),
            class_name=method.npm_class,
            method=method.npm_method,
            inputs=method.npm_inputs,
            output=method.npm_output,
            sdk_name="npm",
        ))
        failures.extend(check_signature(
            signature=pip_method_signature(sdk_py, method.pip_class, method.pip_method),
            class_name=method.pip_class,
            method=method.pip_method,
            inputs=method.pip_inputs,
            output=method.pip_output,
            sdk_name="pip",
        ))
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS sdk cleartext parity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
