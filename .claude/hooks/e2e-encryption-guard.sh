#!/bin/bash
# Hook: PreToolUse (apply_patch|Edit|Write) — e2e-encryption-guard
# ------------------------------------------------------------------
# Blocks any affirmative "end-to-end encryption" / "E2EE" / "e2e encrypt"
# claim being written to a file. OpenMates uses client-side encryption with
# server-side in-memory decryption — NOT end-to-end encryption.
#
# Allowed: disclaimers like "this is NOT end-to-end encryption" or
#          "E2EE is FORBIDDEN" (negation/forbidden context detected).
# Blocked: "end-to-end encrypted", "E2EE", "e2e encryption" as assertions.
#
# Use instead: "client-side encrypted", "encrypted on the user's device",
#              "encrypted before leaving the browser".
#
# Strictness: BLOCKING (exit 2 on violation).
# Related: docs/architecture/core/encryption-architecture.md

INPUT=$(cat)

# Pass the full JSON payload to Python via env var
RESULT=$(HOOK_INPUT="$INPUT" python3 - <<'PY'
import json, sys, re, os

raw = os.environ.get("HOOK_INPUT", "")
try:
    data = json.loads(raw)
except Exception:
    sys.exit(0)

# Files that legitimately contain these terms as rule/guard definitions
EXEMPT_SUFFIXES = [
    "e2e-encryption-guard.sh",
    "test_privacy_promises.py",
    "privacy_promises.yml",
    "encryption-architecture.md",
    "client-side-encryption.md",
    "master-key-cross-device.md",
    "test_integration_encryption.py",
]

tool      = data.get("tool_name", "")
inp       = data.get("tool_input", {})
file_path = inp.get("file_path", "") or ""

def is_exempt(path: str) -> bool:
    fp = path.replace("\\", "/")
    return any(fp.endswith(suffix) for suffix in EXEMPT_SUFFIXES)

def added_patch_text(patch_text: str) -> tuple[str, list[str]]:
    paths = []
    added = []
    current_path = ""
    current_exempt = False

    for line in patch_text.splitlines():
        for prefix in ("*** Add File: ", "*** Update File: ", "*** Delete File: "):
            if line.startswith(prefix):
                current_path = line[len(prefix):].strip()
                current_exempt = is_exempt(current_path)
                paths.append(current_path)
                break
        else:
            if current_exempt:
                continue
            if line.startswith("+") and not line.startswith("+++"):
                added.append(line[1:])

    return "\n".join(added), paths

if tool == "Write":
    text = "" if is_exempt(file_path) else (inp.get("content", "") or "")
elif tool == "apply_patch":
    text, paths = added_patch_text(inp.get("patchText", "") or "")
    if paths and all(is_exempt(path) for path in paths):
        sys.exit(0)
else:
    text = "" if is_exempt(file_path) else (inp.get("new_string", "") or "")

if not text:
    sys.exit(0)

fp = file_path.replace("\\", "/")

# Forbidden patterns (affirmative E2E claims)
PATTERNS = [
    r'end[- ]to[- ]end\s+encry',
    r'\bE2EE\b',
    r'\be2e\s+encry',
    r'end\s+to\s+end\s+encry',
]

# Negation within 100 chars BEFORE the match → disclaimer, allow
NEGATION_BEFORE = re.compile(
    r'\b(not|never|no\b|isn\'t|is not|aren\'t|are not|avoid|unlike|without|'
    r'forbidden|FORBIDDEN|banned|prohibit|prevent|NOT|NEVER|NO)\b',
    re.IGNORECASE,
)
# Negation within 60 chars AFTER the match → also allow
NEGATION_AFTER = re.compile(
    r'\b(forbidden|FORBIDDEN|banned|prohibited|is not|isn\'t|NOT)\b',
    re.IGNORECASE,
)

hits = []
for pat in PATTERNS:
    for m in re.finditer(pat, text, re.IGNORECASE):
        ctx_before = text[max(0, m.start() - 100) : m.start()]
        ctx_after  = text[m.end() : min(len(text), m.end() + 60)]
        if NEGATION_BEFORE.search(ctx_before) or NEGATION_AFTER.search(ctx_after):
            continue
        hits.append(m.group(0))

if hits:
    found = '", "'.join(sorted(set(hits)))
    msg = (
        f'BLOCKED: Affirmative E2E encryption claim: "{found}". '
        "OpenMates uses client-side encryption with server-side in-memory decryption — "
        "NOT end-to-end encryption. "
        'Use "client-side encrypted", "encrypted on the user\'s device", '
        'or "encrypted before leaving the browser". '
        'Disclaimers like "this is NOT end-to-end encryption" are fine.'
    )
    print(json.dumps({"decision": "block", "reason": msg}))
    sys.exit(2)

sys.exit(0)
PY
)

EXIT_CODE=$?
[ -n "$RESULT" ] && echo "$RESULT"
exit $EXIT_CODE
