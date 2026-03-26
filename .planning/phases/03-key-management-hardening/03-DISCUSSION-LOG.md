# Phase 3: Key Management Hardening - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-26
**Phase:** 03-key-management-hardening
**Areas discussed:** Bypass handling, Failure behavior, Key delivery order

---

## Bypass Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Fix all bypasses now | Route everything through ChatKeyManager | |
| Fix only bug-causing | Fix 3 unknowns + chat key paths, leave legitimate bypasses | |
| You decide | Claude classifies each bypass | |
| Other | User's custom answer | ✓ |

**User's choice:** "What is the most reliable clean solution? (that doesn't break existing chats)"
**Notes:** Led to: fix 3 needs-investigation items + all chat-key operations through ChatKeyManager. Leave 14 legitimate bypasses (different key types) alone. Clean boundary: ChatKeyManager owns chat keys exclusively.

---

## Failure Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Retry then show error | Re-fetch key once, then show error | |
| Show error immediately | No retry, instant error display | |
| You decide | Claude designs failure behavior | |
| Other | User's custom answer | ✓ |

**User's choice:** "The main goal must be to prevent errors in the first place. Silent errors must always be prevented, but the architecture should prevent failures, not just show better errors."
**Notes:** Prevention-first approach. Error display is a safety net, not the solution. Visible errors + debug.py logging as fallback only.

---

## Key Delivery Order

| Option | Description | Selected |
|--------|-------------|----------|
| Hold messages | Buffer until key confirmed | ✓ |
| Pre-fetch on open | Fetch key before requesting messages | |
| You decide | Claude designs the guarantee | |

**User's choice:** Hold messages
**Notes:** Slight delay acceptable, decryption failure is not.

---

## Claude's Discretion

- Web Locks API integration details
- ChatKeyManager state machine extension
- BroadcastChannel completion
- Message buffering implementation

## Deferred Ideas

None
