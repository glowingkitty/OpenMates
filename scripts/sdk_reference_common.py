#!/usr/bin/env python3
"""Shared SDK reference extraction helpers.

Purpose: expose the public npm/pip SDK surface parsed by the parity audit as a
stable data model for generated docs and coverage audits.
Architecture: imports the canonical parser from audit_sdk_cleartext_parity.py so
parity, docs, and test coverage use one source of truth.
Security: preserves the cleartext SDK boundary by describing public methods only.
Spec: docs/specs/sdk-cleartext-encryption-boundary/spec.yml.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import importlib.util
import sys


ROOT = Path(__file__).resolve().parents[1]
PARITY_AUDIT = ROOT / "scripts" / "audit_sdk_cleartext_parity.py"


@dataclass(frozen=True)
class SdkMethodReference:
    namespace: str
    npm_namespace: str
    pip_namespace: str
    npm_method: str
    pip_method: str
    npm_inputs: tuple[str, ...]
    pip_inputs: tuple[str, ...]
    output_category: str

    @property
    def key(self) -> str:
        return f"{self.namespace}.{self.npm_method}/{self.pip_method}"

    @property
    def npm_call(self) -> str:
        return f"om.{self.npm_namespace}.{self.npm_method}()"

    @property
    def pip_call(self) -> str:
        return f"om.{self.pip_namespace}.{self.pip_method}()"


def _load_parity_module():
    spec = importlib.util.spec_from_file_location("openmates_sdk_parity", PARITY_AUDIT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load SDK parity audit parser")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _ts_root_namespace_display(source: str, parity) -> dict[str, str]:
    body = parity._class_body(source, "OpenMates", language="ts")
    namespaces: dict[str, str] = {}
    for match in parity.re.finditer(r"\n\s{2}readonly\s+([A-Za-z0-9_]+)\s*:\s*(OpenMates[A-Za-z0-9_]+)", body):
        namespaces[parity._normalize_name(match.group(1))] = match.group(1)
    return namespaces


def _py_root_namespace_display(class_node, parity) -> dict[str, str]:
    namespaces: dict[str, str] = {}
    init_node = next((node for node in class_node.body if isinstance(node, parity.ast.FunctionDef) and node.name == "__init__"), None)
    if not init_node:
        return namespaces
    for node in parity.ast.walk(init_node):
        if not isinstance(node, parity.ast.Assign):
            continue
        if not isinstance(node.value, parity.ast.Call) or not isinstance(node.value.func, parity.ast.Name):
            continue
        if not node.value.func.id.startswith("OpenMates"):
            continue
        for target in node.targets:
            if isinstance(target, parity.ast.Attribute) and isinstance(target.value, parity.ast.Name) and target.value.id == "self":
                namespaces[parity._normalize_name(target.attr)] = target.attr
    return namespaces


def collect_sdk_method_references() -> list[SdkMethodReference]:
    parity = _load_parity_module()
    sdk_ts = parity.SDK_TS.read_text(encoding="utf-8")
    sdk_py = parity.SDK_PY.read_text(encoding="utf-8")
    ts_type_shapes = parity._extract_ts_type_shapes(sdk_ts)
    ts_classes = parity._extract_ts_classes(sdk_ts)
    py_classes = parity._extract_py_classes(sdk_py)
    ts_namespaces = parity._extract_ts_root_namespaces(sdk_ts)
    py_namespaces = parity._extract_py_root_namespaces(py_classes["OpenMates"])
    ts_display = _ts_root_namespace_display(sdk_ts, parity)
    py_display = _py_root_namespace_display(py_classes["OpenMates"], parity)

    references: list[SdkMethodReference] = []
    for namespace in sorted(set(ts_namespaces) | set(py_namespaces)):
        ts_class = ts_namespaces.get(namespace)
        py_class = py_namespaces.get(namespace)
        if not ts_class or not py_class or ts_class not in ts_classes or py_class not in py_classes:
            continue
        ts_methods = parity._extract_ts_methods(
            ts_classes[ts_class],
            class_name=ts_class,
            namespace=namespace,
            type_shapes=ts_type_shapes,
        )
        py_methods = parity._extract_py_methods(py_classes[py_class], class_name=py_class, namespace=namespace)
        for method_name in sorted(set(ts_methods) & set(py_methods)):
            npm = ts_methods[method_name]
            pip = py_methods[method_name]
            references.append(
                SdkMethodReference(
                    namespace=namespace,
                    npm_namespace=ts_display.get(namespace, namespace),
                    pip_namespace=py_display.get(namespace, namespace),
                    npm_method=npm.name,
                    pip_method=pip.name,
                    npm_inputs=npm.inputs,
                    pip_inputs=pip.inputs,
                    output_category=parity._feature_output_category(npm.output or pip.output),
                )
            )
    return references


def references_by_namespace() -> dict[str, list[SdkMethodReference]]:
    grouped: dict[str, list[SdkMethodReference]] = {}
    for reference in collect_sdk_method_references():
        grouped.setdefault(reference.namespace, []).append(reference)
    return grouped
