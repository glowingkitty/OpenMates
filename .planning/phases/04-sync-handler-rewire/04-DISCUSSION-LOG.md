# Phase 4: Sync Handler Rewire - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.

**Date:** 2026-03-26
**Phase:** 04-sync-handler-rewire
**Areas discussed:** WebSocket ack, Reconnection, Sender-side crypto

---

## WebSocket Acknowledgment

| Option | Description | Selected |
|--------|-------------|----------|
| Simple server-side flag | Server marks key delivered, sender checks flag | |
| Full round-trip ack | Recipient sends key_received back, sender waits | ✓ |
| You decide | Claude picks based on patterns | |

**User's choice:** Full round-trip ack
**Notes:** Reliability over simplicity

---

## Reconnection Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Keys-first sync | Fetch all keys first, then messages | |
| Existing phased sync | Leverage existing sync + Phase 3 withKey() | |
| You decide | Claude analyzes reconnection path | |
| Other | User's custom answer | ✓ |

**User's choice:** "What solution makes the most sense given our existing sync architecture? Want reliability but also fast loading."
**Notes:** Led to: leverage existing phased sync + withKey() buffering. No new protocol needed.

---

## Sender-Side Crypto

| Option | Description | Selected |
|--------|-------------|----------|
| Route through encryptors | Replace inline encrypt with encryptor imports | |
| Encryptors + split file | Route through encryptors AND split 2100-line file | ✓ |
| You decide | Claude determines minimal safe change | |

**User's choice:** Encryptors + split file
**Notes:** Code quality matters, not just crypto routing

---

## Claude's Discretion

- File split boundaries for chatSyncServiceSenders.ts
- WebSocket ack protocol details
- BroadcastChannel completion

## Deferred Ideas

None
