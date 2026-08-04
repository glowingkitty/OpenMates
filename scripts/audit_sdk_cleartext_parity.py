#!/usr/bin/env python3
"""Audit user-perspective npm and pip SDK parity.

Purpose: keep public SDK namespace names, methods, inputs, and outputs aligned
across TypeScript and Python.
Architecture: dynamic union audit over the OpenMates public namespaces plus the
generated app-skill metadata; no SDK namespace is limited to a hand-written list.
Security: cleartext public methods must remain equivalent regardless of SDK
language, with encryption hidden inside both clients.
Spec: docs/specs/sdk-cleartext-encryption-boundary/spec.yml.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import ast
import json
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SDK_TS = ROOT / "frontend/packages/openmates-cli/src/sdk.ts"
SDK_PY = ROOT / "packages/openmates-python/openmates/sdk.py"
APP_SKILLS_TS = ROOT / "frontend/packages/openmates-cli/src/generated/appSkills.ts"
APP_SKILLS_PY = ROOT / "packages/openmates-python/openmates/generated/app_skills.py"

IGNORED_CLASSES = {"OpenMatesApiError", "OpenMatesConfigError"}
IGNORED_METHODS = {"constructor"}
TS_KEYWORDS = {"catch", "for", "if", "switch", "while"}
ROOT_INTERNAL_METHODS = {
    "decrypt_chat_metadata",
    "decrypt_loaded_chat_payload",
    "get",
    "get_public",
    "get_raw",
    "master_key",
    "patch",
    "put",
    "request",
    "resolve_embed_key_for_share",
    "run_app_skill",
    "sdk_session",
    "web_origin",
}
METHOD_ALIASES = {
    ("connected_accounts", "import"): "import_account",
    ("teams", "import"): "import_team",
}
ENTITY_ID_BY_NAMESPACE = {
    "api_keys": "key_id",
    "chats": "chat_id",
    "embeds": "embed_id",
    "memories": "memory_id",
    "plans": "plan_id",
    "projects": "project_id",
    "reminders": "reminder_id",
    "tasks": "task_id",
    "teams": "team_id",
    "workflows": "workflow_id",
}
GENERIC_INPUT_NAMES = {"filters", "input", "input_data", "kwargs", "options", "params", "payload", "query"}
CONTROL_INPUT_NAMES = {"accept_partial", "confirmed", "id", "password", "source_name"}


@dataclass(frozen=True)
class MethodContract:
    name: str
    inputs: tuple[str, ...]
    output: str


def _camel_to_snake(value: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value).lower()


def _normalized_text(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", " ", _camel_to_snake(value)).lower()
    return " ".join(part.strip("_") for part in normalized.split() if part.strip("_"))


def _normalize_name(value: str) -> str:
    return _normalized_text(value).replace(" ", "_")


def _canonical_input(namespace: str, value: str) -> str:
    normalized = _normalize_name(value)
    normalized = normalized.replace("chat_gpt", "chatgpt").replace("open_code", "opencode").replace("open_mates", "openmates")
    normalized = normalized.replace("recovery_poll_interval_ms", "recovery_poll_interval")
    normalized = normalized.replace("recovery_poll_interval_seconds", "recovery_poll_interval")
    normalized = normalized.replace("recovery_timeout_ms", "recovery_timeout")
    normalized = normalized.replace("recovery_timeout_seconds", "recovery_timeout")
    if normalized in GENERIC_INPUT_NAMES:
        return "input"
    if normalized in {"confirmed", "confirm_destructive"}:
        return "confirmed"
    entity_id = ENTITY_ID_BY_NAMESPACE.get(namespace)
    if entity_id and normalized == entity_id:
        return "id"
    if normalized.endswith("_id") and normalized.removesuffix("_id") == namespace.removesuffix("s"):
        return "id"
    return normalized


def _canonical_method(namespace: str, value: str) -> str:
    normalized = _normalize_name(value)
    normalized = normalized.replace("chat_gpt", "chatgpt").replace("open_code", "opencode").replace("open_mates", "openmates")
    return METHOD_ALIASES.get((namespace, normalized), normalized)


def _scan_balanced(source: str, start: int, opener: str, closer: str) -> int:
    depth = 0
    quote: str | None = None
    escape = False
    for index in range(start, len(source)):
        char = source[index]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'", "`"}:
            quote = char
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"Unbalanced {opener}{closer} block")


def _split_top_level(value: str, delimiter: str = ",") -> list[str]:
    parts: list[str] = []
    start = 0
    depths = {"(": 0, "{": 0, "[": 0, "<": 0}
    closers = {")": "(", "}": "{", "]": "[", ">": "<"}
    quote: str | None = None
    escape = False
    for index, char in enumerate(value):
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'", "`"}:
            quote = char
            continue
        if char in depths:
            depths[char] += 1
            continue
        if char in closers and depths[closers[char]] > 0:
            depths[closers[char]] -= 1
            continue
        if char == delimiter and not any(depths.values()):
            parts.append(value[start:index].strip())
            start = index + 1
    tail = value[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _extract_object_field_names(type_text: str) -> tuple[str, ...]:
    object_start = type_text.find("{")
    if object_start == -1:
        return ()
    try:
        object_end = _scan_balanced(type_text, object_start, "{", "}")
    except ValueError:
        return ()
    object_body = type_text[object_start + 1:object_end]
    fields: list[str] = []
    for part in _split_top_level(object_body, ";"):
        if not part:
            continue
        match = re.match(r"\s*([A-Za-z_$][A-Za-z0-9_$]*)\??\s*[:(]", part)
        if match:
            fields.append(_normalize_name(match.group(1)))
    if not fields:
        for part in _split_top_level(object_body, ","):
            match = re.match(r"\s*([A-Za-z_$][A-Za-z0-9_$]*)\??\s*[:(]", part)
            if match:
                fields.append(_normalize_name(match.group(1)))
    return tuple(fields)


def _extract_ts_type_shapes(source: str) -> dict[str, tuple[str, ...]]:
    parents: dict[str, tuple[str, ...]] = {}
    shapes: dict[str, tuple[str, ...]] = {}
    for match in re.finditer(r"(?:export\s+)?(?:interface|type)\s+([A-Za-z0-9_]+)([^{}=;]*)\s*(?:=)?\s*{", source):
        name = match.group(1)
        extends_match = re.search(r"\bextends\s+([A-Za-z0-9_,\s]+)", match.group(2))
        if extends_match:
            parents[name] = tuple(parent.strip() for parent in extends_match.group(1).split(",") if parent.strip())
        open_brace = source.index("{", match.start())
        try:
            close_brace = _scan_balanced(source, open_brace, "{", "}")
        except ValueError:
            continue
        shapes[name] = _extract_object_field_names(source[open_brace:close_brace + 1])
    for name, parent_names in parents.items():
        inherited: list[str] = []
        for parent_name in parent_names:
            inherited.extend(shapes.get(parent_name, ()))
        shapes[name] = tuple(dict.fromkeys([*inherited, *shapes.get(name, ())]))
    return shapes


def _class_body(source: str, class_name: str, *, language: str) -> str:
    pattern = rf"\n(?:export\s+)?class\s+{re.escape(class_name)}\b"
    match = re.search(pattern, source)
    if not match:
        raise ValueError(f"Class {class_name} not found")
    start = match.start()
    next_marker = "\nexport class " if language == "ts" else "\nclass "
    end = source.find(next_marker, start + 1)
    return source[start:] if end == -1 else source[start:end]


def _extract_ts_classes(source: str) -> dict[str, str]:
    classes: dict[str, str] = {}
    for match in re.finditer(r"\nexport class (OpenMates[A-Za-z0-9_]*)\b", source):
        class_name = match.group(1)
        if class_name in IGNORED_CLASSES:
            continue
        classes[class_name] = _class_body(source, class_name, language="ts")
    return classes


def _extract_py_classes(source: str) -> dict[str, ast.ClassDef]:
    module = ast.parse(source)
    return {
        node.name: node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name.startswith("OpenMates") and node.name not in IGNORED_CLASSES
    }


def _extract_ts_root_namespaces(source: str) -> dict[str, str]:
    body = _class_body(source, "OpenMates", language="ts")
    namespaces: dict[str, str] = {}
    for match in re.finditer(r"\n\s{2}readonly\s+([A-Za-z0-9_]+)\s*:\s*(OpenMates[A-Za-z0-9_]+)", body):
        namespaces[_normalize_name(match.group(1))] = match.group(2)
    return namespaces


def _extract_py_root_namespaces(class_node: ast.ClassDef) -> dict[str, str]:
    namespaces: dict[str, str] = {}
    init_node = next((node for node in class_node.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"), None)
    if not init_node:
        return namespaces
    for node in ast.walk(init_node):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call) or not isinstance(node.value.func, ast.Name):
            continue
        if not node.value.func.id.startswith("OpenMates"):
            continue
        for target in node.targets:
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                namespaces[_normalize_name(target.attr)] = node.value.func.id
    return namespaces


def _normalize_ts_inputs(part: str, type_shapes: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    cleaned = part.strip()
    if not cleaned or cleaned.startswith("..."):
        cleaned = cleaned.removeprefix("...").strip()
    match = re.match(r"([A-Za-z_$][A-Za-z0-9_$]*)\??\s*[:=]", cleaned)
    if not match:
        return ()
    param_name = _normalize_name(match.group(1))
    type_text = cleaned[match.end():]
    fields: list[str] = []
    if not type_text.strip().startswith("{"):
        for type_name in re.findall(r"\b[A-Z][A-Za-z0-9_]+\b", type_text):
            fields.extend(type_shapes.get(type_name, ()))
    inline_fields = _extract_object_field_names(type_text)
    if inline_fields:
        fields.extend(inline_fields)
    if fields:
        return tuple(dict.fromkeys(fields))
    type_match = re.search(r":\s*([A-Za-z0-9_]+)", cleaned)
    if type_match and type_match.group(1) in type_shapes:
        return type_shapes[type_match.group(1)]
    return (param_name,)


def _normalize_py_input(arg: ast.arg) -> str | None:
    if arg.arg in {"self", "cls"} or arg.arg.startswith("_"):
        return None
    return _normalize_name(arg.arg)


def _extract_ts_methods(class_body: str, *, class_name: str, namespace: str, type_shapes: dict[str, tuple[str, ...]]) -> dict[str, MethodContract]:
    methods: dict[str, MethodContract] = {}
    pattern = re.compile(r"\n\s{2}(private\s+|protected\s+)?(?:async\s+)?(?:\*\s*)?([A-Za-z_$][A-Za-z0-9_$]*)\s*(?:<[^\n{;]+>)?\s*\(")
    for match in pattern.finditer(class_body):
        if match.group(1):
            continue
        method_name = match.group(2)
        if method_name in IGNORED_METHODS or method_name in TS_KEYWORDS or method_name.startswith("_"):
            continue
        normalized_method = _canonical_method(namespace, method_name)
        if class_name == "OpenMates" and normalized_method in ROOT_INTERNAL_METHODS:
            continue
        open_paren = class_body.index("(", match.start())
        close_paren = _scan_balanced(class_body, open_paren, "(", ")")
        signature_end = class_body.find("{", close_paren)
        signature = class_body[match.start():signature_end if signature_end != -1 else close_paren + 1]
        params = class_body[open_paren + 1:close_paren]
        inputs = tuple(
            _canonical_input(namespace, input_name)
            for part in _split_top_level(params)
            for input_name in _normalize_ts_inputs(part, type_shapes)
        )
        output_match = re.search(r"\)\s*:\s*([^\n{]+)", signature)
        output = output_match.group(1).strip() if output_match else ""
        methods[normalized_method] = MethodContract(method_name, inputs, output)
    return methods


def _annotation_text(annotation: ast.AST | None) -> str:
    if annotation is None:
        return ""
    try:
        return ast.unparse(annotation)
    except Exception:
        return ""


def _extract_py_methods(class_node: ast.ClassDef, *, class_name: str, namespace: str) -> dict[str, MethodContract]:
    methods: dict[str, MethodContract] = {}
    for node in class_node.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name.startswith("_") or node.name in IGNORED_METHODS:
            continue
        normalized_method = _canonical_method(namespace, node.name)
        if class_name == "OpenMates" and normalized_method in ROOT_INTERNAL_METHODS:
            continue
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg:
            args.append(node.args.vararg)
        if node.args.kwarg:
            args.append(node.args.kwarg)
        inputs = tuple(
            _canonical_input(namespace, input_name)
            for input_name in (_normalize_py_input(arg) for arg in args)
            if input_name
        )
        output = _annotation_text(node.returns)
        methods[normalized_method] = MethodContract(node.name, inputs, output)
    return methods


def _feature_output_category(output: str) -> str:
    normalized = _normalized_text(output)
    raw = output.lower()
    if not normalized:
        return "unknown"
    if "async iterable" in normalized or "iterator" in normalized or "iterable" in normalized:
        return "iterator"
    if "bytes" in normalized or "uint8array" in normalized or "arraybuffer" in normalized:
        return "bytes"
    if "list" in normalized or "array" in normalized or "sequence" in normalized or "tuple" in normalized or "[]" in raw:
        return "list"
    if "bool" in normalized or "boolean" in normalized:
        return "boolean"
    if any(token in normalized for token in ("dict", "record", "response", "result", "detail", "metadata", "manifest", "projection", "event")):
        return "object"
    if "str" in normalized or "string" in normalized:
        return "string"
    if "number" in normalized or "int" in normalized or "float" in normalized:
        return "number"
    return "object"


def _has_generic_input(inputs: set[str]) -> bool:
    return "input" in inputs


def _comparable_input_sets(namespace: str, npm_inputs: tuple[str, ...], pip_inputs: tuple[str, ...]) -> tuple[set[str], set[str]]:
    npm_values = set(npm_inputs)
    pip_values = set(pip_inputs)
    if namespace == "projects":
        # TypeScript uses a discriminated context object; Python uses keyword arguments.
        context_inputs = {"context", "personal", "team_id"}
        npm_values -= context_inputs
        pip_values -= context_inputs
    if _has_generic_input(npm_values) or _has_generic_input(pip_values):
        return (
            {value for value in npm_values if value in CONTROL_INPUT_NAMES},
            {value for value in pip_values if value in CONTROL_INPUT_NAMES},
        )
    return npm_values, pip_values


def _compare_methods(namespace: str, npm_methods: dict[str, MethodContract], pip_methods: dict[str, MethodContract]) -> list[str]:
    failures: list[str] = []
    for method_name in sorted(set(npm_methods) | set(pip_methods)):
        npm = npm_methods.get(method_name)
        pip = pip_methods.get(method_name)
        if not npm:
            failures.append(f"Missing npm SDK method {namespace}.{pip.name}")
            continue
        if not pip:
            failures.append(f"Missing pip SDK method {namespace}.{npm.name}")
            continue
        npm_inputs, pip_inputs = _comparable_input_sets(namespace, npm.inputs, pip.inputs)
        if npm_inputs != pip_inputs:
            failures.append(
                f"SDK method input mismatch {namespace}.{npm.name}/{pip.name}: "
                f"npm={sorted(npm_inputs)} pip={sorted(pip_inputs)}"
            )
        npm_output = _feature_output_category(npm.output)
        pip_output = _feature_output_category(pip.output)
        if npm_output != pip_output and "unknown" not in {npm_output, pip_output}:
            failures.append(
                f"SDK method output mismatch {namespace}.{npm.name}/{pip.name}: "
                f"npm={npm.output or 'unknown'} pip={pip.output or 'unknown'}"
            )
    return failures


def _load_ts_app_skill_metadata() -> list[dict[str, Any]]:
    text = APP_SKILLS_TS.read_text(encoding="utf-8")
    match = re.search(r"export const APP_SKILL_METADATA = (\[.*?\])\s+as const;", text, re.S)
    if not match:
        raise RuntimeError("Could not parse TypeScript app skill metadata")
    return json.loads(match.group(1))


def _load_py_app_skill_metadata() -> list[dict[str, Any]]:
    module = ast.parse(APP_SKILLS_PY.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "APP_SKILL_METADATA":
                    return ast.literal_eval(node.value)
    raise RuntimeError("Could not parse Python app skill metadata")


def _app_skill_key(item: dict[str, Any]) -> tuple[str, str]:
    return (str(item.get("app_id") or ""), str(item.get("skill_id") or ""))


def _compare_app_skill_metadata() -> list[str]:
    failures: list[str] = []
    npm_items = {_app_skill_key(item): item for item in _load_ts_app_skill_metadata()}
    pip_items = {_app_skill_key(item): item for item in _load_py_app_skill_metadata()}
    for key in sorted(set(npm_items) | set(pip_items)):
        npm = npm_items.get(key)
        pip = pip_items.get(key)
        label = ".".join(key)
        if not npm:
            failures.append(f"Missing npm generated app skill {label}")
            continue
        if not pip:
            failures.append(f"Missing pip generated app skill {label}")
            continue
        pairs = (
            ("app_namespace_ts", "app_namespace_ts"),
            ("app_namespace_py", "app_namespace_py"),
            ("skill_method_ts", "skill_method_ts"),
            ("skill_method_py", "skill_method_py"),
        )
        for npm_field, pip_field in pairs:
            if npm.get(npm_field) != pip.get(pip_field):
                failures.append(f"Generated app skill metadata mismatch {label}.{npm_field}: npm={npm.get(npm_field)!r} pip={pip.get(pip_field)!r}")
        if sorted((npm.get("schema") or {}).get("properties") or {}) != sorted((pip.get("schema") or {}).get("properties") or {}):
            failures.append(f"Generated app skill input schema mismatch {label}")
    return failures


def main() -> int:
    sdk_ts = SDK_TS.read_text(encoding="utf-8")
    sdk_py = SDK_PY.read_text(encoding="utf-8")
    ts_type_shapes = _extract_ts_type_shapes(sdk_ts)
    ts_classes = _extract_ts_classes(sdk_ts)
    py_classes = _extract_py_classes(sdk_py)
    ts_namespaces = _extract_ts_root_namespaces(sdk_ts)
    py_namespaces = _extract_py_root_namespaces(py_classes["OpenMates"])
    failures: list[str] = []

    for namespace in sorted(set(ts_namespaces) | set(py_namespaces)):
        ts_class = ts_namespaces.get(namespace)
        py_class = py_namespaces.get(namespace)
        if not ts_class:
            failures.append(f"Missing npm SDK namespace {namespace} -> {py_class}")
            continue
        if not py_class:
            failures.append(f"Missing pip SDK namespace {namespace} -> {ts_class}")
            continue
        if ts_class not in ts_classes:
            failures.append(f"Missing npm SDK class {ts_class} for namespace {namespace}")
            continue
        if py_class not in py_classes:
            failures.append(f"Missing pip SDK class {py_class} for namespace {namespace}")
            continue
        failures.extend(_compare_methods(
            namespace,
            _extract_ts_methods(ts_classes[ts_class], class_name=ts_class, namespace=namespace, type_shapes=ts_type_shapes),
            _extract_py_methods(py_classes[py_class], class_name=py_class, namespace=namespace),
        ))

    failures.extend(_compare_app_skill_metadata())

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS sdk cleartext parity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
