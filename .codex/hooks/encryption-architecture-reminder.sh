#!/usr/bin/env bash
# encryption-architecture-reminder.sh — PostToolUse warning hook (never blocks).
# Fires when encryption-related symbols are written to .ts/.svelte files and
# injects a reminder of the KEYS-04 invariant and key-lifecycle rules into the
# model context via hookSpecificOutput.additionalContext.

INPUT=$(cat)

python3 - <<'PY' "$INPUT"
import json, sys, re

raw = sys.argv[1] if len(sys.argv) > 1 else ""
try:
    data = json.loads(raw)
except Exception:
    sys.exit(0)

tool     = data.get("tool_name", "")
inp      = data.get("tool_input", {})
fp       = (inp.get("file_path", "") or "").replace("\\", "/")
text     = inp.get("content", "") if tool == "Write" else inp.get("new_string", "") or ""

# Only watch TypeScript and Svelte files
if not re.search(r'\.(ts|svelte)$', fp):
    sys.exit(0)

# Exempt the canonical definition files — getKeySync/getKey are legitimately
# defined there and calling this a violation would be noise.
EXEMPT = ["ChatKeyManager.ts", "MessageEncryptor.ts"]
if any(fp.endswith(e) for e in EXEMPT):
    sys.exit(0)

if not text:
    sys.exit(0)

PATTERNS = [
    r'\bchatKeyManager\b',
    r'\bChatKeyManager\b',
    r'\bgetKeySync\b',
    r'\bgetKey\b',
    r'\bwithKey\b',
    r'\bdecryptHighlightPayload\b',
    r'\bdecryptMessage\b',
    r'\bencryptMessage\b',
    r'\bMessageEncryptor\b',
    r'\bCryptoKey\b',
    r'\bmasterKey\b',
    r'\bencrypted_payload\b',
    r'\bunwrapKey\b',
    r'\bwrapKey\b',
]

matched = sorted({m.group(0) for p in PATTERNS for m in re.finditer(p, text)})
if not matched:
    sys.exit(0)

symbols = ", ".join(matched)

warning = f"""
╔══════════════════════════════════════════════════════════════════════╗
║  ⚠  ENCRYPTION ARCHITECTURE REMINDER                                ║
║  Symbols touched: {symbols:<50}║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  KEYS-04 RULE (mandatory for all WS / inbound-event handlers):       ║
║                                                                      ║
║  ✅  chatKeyManager.withKey(chatId, "label", async (key) => {{ ... }})  ║
║  ❌  chatKeyManager.getKeySync(chatId)                                ║
║  ❌  await chatKeyManager.getKey(chatId)                              ║
║  ❌  getKeySync(id) ?? getKey(id)   ← the bug that caused ed206641   ║
║                                                                      ║
║  WHY getKeySync / getKey are unsafe in handlers:                     ║
║    IDB load → async unwrapKey() → ChatKeyManager "ready"             ║
║    During the unwrap window (secondary device cold-boot / post-      ║
║    login phased sync), BOTH calls return null. The decrypt call      ║
║    silently fails and the message / highlight is permanently lost.   ║
║    withKey() buffers the callback until the key transitions to       ║
║    "ready" — no data loss, no race.                                  ║
║                                                                      ║
║  KEY LIFECYCLE:                                                       ║
║    1. App boot / login → ChatKeyManager queues IDB fetch             ║
║    2. IDB read → encrypted_chat_key blob                             ║
║    3. SubtleCrypto.unwrapKey() (async, ~5-50ms on slow devices)      ║
║    4. State → "ready"; withKey() callbacks drain                     ║
║    5. Only after step 4 is getKeySync() safe to call                 ║
║                                                                      ║
║  OTHER RULES:                                                         ║
║    • Never import from ChatKeyManager internal modules — use barrel   ║
║    • decryptX() functions must be called inside withKey() callback   ║
║    • encryptX() for outbound sends is safe (key already loaded by    ║
║      the time the user can type), but still prefer withKey() for     ║
║      consistency and resilience to future cold-send paths            ║
║                                                                      ║
║  Docs: docs/architecture/core/encryption-root-causes.md#KEYS-04     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

out = {
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": warning.strip()
    }
}
print(json.dumps(out))
sys.exit(0)
PY
