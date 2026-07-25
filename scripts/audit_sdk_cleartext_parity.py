#!/usr/bin/env python3
"""Audit user-perspective npm and pip SDK parity.

Purpose: keep public SDK namespace methods aligned across TypeScript and Python.
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


METHODS = [
    MethodPair("OpenMatesProjects", "list", "OpenMatesProjects", "list"),
    MethodPair("OpenMatesProjects", "create", "OpenMatesProjects", "create"),
    MethodPair("OpenMatesProjects", "history", "OpenMatesProjects", "history"),
    MethodPair("OpenMatesProjects", "restore", "OpenMatesProjects", "restore"),
    MethodPair("OpenMatesProjects", "ask", "OpenMatesProjects", "ask"),
    MethodPair("OpenMatesTasks", "list", "OpenMatesTasks", "list"),
    MethodPair("OpenMatesTasks", "listDecrypted", "OpenMatesTasks", "list_decrypted"),
    MethodPair("OpenMatesTasks", "show", "OpenMatesTasks", "show"),
    MethodPair("OpenMatesTasks", "history", "OpenMatesTasks", "history"),
    MethodPair("OpenMatesTasks", "restore", "OpenMatesTasks", "restore"),
    MethodPair("OpenMatesTasks", "ask", "OpenMatesTasks", "ask"),
    MethodPair("OpenMatesTasks", "create", "OpenMatesTasks", "create"),
    MethodPair("OpenMatesTasks", "update", "OpenMatesTasks", "update"),
    MethodPair("OpenMatesTasks", "edit", "OpenMatesTasks", "edit"),
    MethodPair("OpenMatesTasks", "addToProject", "OpenMatesTasks", "add_to_project"),
    MethodPair("OpenMatesTasks", "start", "OpenMatesTasks", "start"),
    MethodPair("OpenMatesTasks", "startAI", "OpenMatesTasks", "start_ai"),
    MethodPair("OpenMatesTasks", "delete", "OpenMatesTasks", "delete"),
    MethodPair("OpenMatesTasks", "done", "OpenMatesTasks", "done"),
    MethodPair("OpenMatesTasks", "complete", "OpenMatesTasks", "complete"),
    MethodPair("OpenMatesTasks", "block", "OpenMatesTasks", "block"),
    MethodPair("OpenMatesTasks", "unblock", "OpenMatesTasks", "unblock"),
    MethodPair("OpenMatesTasks", "skip", "OpenMatesTasks", "skip"),
    MethodPair("OpenMatesTasks", "reorder", "OpenMatesTasks", "reorder"),
    MethodPair("OpenMatesTasks", "move", "OpenMatesTasks", "move"),
    MethodPair("OpenMatesPlans", "list", "OpenMatesPlans", "list"),
    MethodPair("OpenMatesPlans", "create", "OpenMatesPlans", "create"),
    MethodPair("OpenMatesPlans", "show", "OpenMatesPlans", "show"),
    MethodPair("OpenMatesPlans", "update", "OpenMatesPlans", "update"),
    MethodPair("OpenMatesPlans", "addToProject", "OpenMatesPlans", "add_to_project"),
    MethodPair("OpenMatesPlans", "history", "OpenMatesPlans", "history"),
    MethodPair("OpenMatesPlans", "restore", "OpenMatesPlans", "restore"),
    MethodPair("OpenMatesPlans", "ask", "OpenMatesPlans", "ask"),
    MethodPair("OpenMatesPlans", "activate", "OpenMatesPlans", "activate"),
    MethodPair("OpenMatesPlans", "attach", "OpenMatesPlans", "attach"),
    MethodPair("OpenMatesPlans", "start", "OpenMatesPlans", "start"),
    MethodPair("OpenMatesPlans", "resume", "OpenMatesPlans", "resume"),
    MethodPair("OpenMatesPlans", "complete", "OpenMatesPlans", "complete"),
]


def class_body(source: str, class_name: str, *, language: str) -> str:
    marker = f"export class {class_name}" if language == "ts" else f"class {class_name}:"
    start = source.index(marker)
    next_marker = "\nexport class " if language == "ts" else "\nclass "
    end = source.find(next_marker, start + 1)
    return source[start:] if end == -1 else source[start:end]


def npm_method_exists(source: str, class_name: str, method: str) -> bool:
    body = class_body(source, class_name, language="ts")
    return re.search(rf"\n\s{{2}}(?:async\s+)?{re.escape(method)}\s*\(", body) is not None


def pip_method_exists(source: str, class_name: str, method: str) -> bool:
    body = class_body(source, class_name, language="py")
    return re.search(rf"\n\s{{4}}def\s+{re.escape(method)}\s*\(", body) is not None


def main() -> int:
    sdk_ts = SDK_TS.read_text(encoding="utf-8")
    sdk_py = SDK_PY.read_text(encoding="utf-8")
    failures: list[str] = []
    for method in METHODS:
        if not npm_method_exists(sdk_ts, method.npm_class, method.npm_method):
            failures.append(f"Missing npm SDK method {method.npm_class}.{method.npm_method}")
        if not pip_method_exists(sdk_py, method.pip_class, method.pip_method):
            failures.append(f"Missing pip SDK method {method.pip_class}.{method.pip_method}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS sdk cleartext parity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
