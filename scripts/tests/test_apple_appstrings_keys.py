"""Guard: every i18n key used by apple AppStrings.swift exists in the generated en.json.

The Apple app resolves L("a.b.c") against frontend/packages/ui/src/i18n/locales/en.json,
where key a.b.c is the JSON object a.b.c holding a `text` field. A missing key renders
as the raw key in the UI. Interpolated keys (`prefix_\\(name)`) are checked by requiring
at least one existing key with that prefix.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EN_JSON = ROOT / "frontend/packages/ui/src/i18n/locales/en.json"
APP_STRINGS = ROOT / "apple/OpenMates/Sources/Core/I18n/AppStrings.swift"

L_CALL = re.compile(r"\bL\(([^\n]*)\)")
KEY_LITERAL = re.compile(r'"([a-z0-9_]+(?:\.[a-z0-9_]+)*(?:\\\([^)]*\)[a-z0-9_]*)?)"')


def _walk(node, path, out):
    if isinstance(node, dict):
        if isinstance(node.get("text"), str):
            out.add(path)
            out.add(f"{path}.text")
        for name, child in node.items():
            if name != "text":
                _walk(child, f"{path}.{name}" if path else name, out)
    elif isinstance(node, str) and path:
        out.add(path)


def _existing_keys():
    keys = set()
    _walk(json.loads(EN_JSON.read_text(encoding="utf-8")), "", keys)
    return keys


def _used_keys():
    used = set()
    for line in APP_STRINGS.read_text(encoding="utf-8").splitlines():
        for call in L_CALL.findall(line):
            for key in KEY_LITERAL.findall(call):
                used.add(key)
    return used


# contract-test: tooling
def test_appstrings_keys_exist_in_en_json():
    existing = _existing_keys()
    used = _used_keys()
    assert used, "no L(...) keys found; the extraction pattern is broken"
    missing = []
    for key in sorted(used):
        if "\\(" in key:
            prefix = key.split("\\(")[0]
            if not any(k.startswith(prefix) for k in existing):
                missing.append(key)
        elif key not in existing:
            missing.append(key)
    assert not missing, f"AppStrings.swift uses {len(missing)} keys missing from en.json: {missing}"
