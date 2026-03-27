# Phase 8: Sender Barrel Deployment - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Deploy the sender sub-module barrel that was created in Phase 4 but never persisted on the dev branch. Replace the 2856-line `chatSyncServiceSenders.ts` monolith with a ~30-line re-export barrel pointing to the 5 existing sub-modules. Close the ARCH-03 gap so all sync handlers route crypto through encryptor modules with zero direct cryptoService imports.

</domain>

<decisions>
## Implementation Decisions

### Swap Strategy
- **D-01:** Atomic swap — replace `chatSyncServiceSenders.ts` content with re-exports from the 5 sub-modules in a single commit. The sub-modules already exist with correct encryptor imports (verified: `sendersChatMessages.ts` imports from `./encryption/MessageEncryptor`).

### Verification Approach
- **D-02:** Run `import-audit.test.ts` (which explicitly checks `chatSyncServiceSenders.ts` for forbidden cryptoService imports) plus the full encryption test suite (90+ tests) to confirm zero regressions.

### Claude's Discretion
- Exact re-export syntax and barrel file structure
- Whether to keep any utility imports in the barrel or move them to sub-modules
- Git history considerations (preserve blame by keeping the file vs replacing content)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 4 Context and Results
- `.planning/phases/04-sync-handler-rewire/04-CONTEXT.md` — Original sender split decisions (D-03)
- `.planning/phases/04-sync-handler-rewire/04-01-SUMMARY.md` — What the barrel was supposed to look like

### Source Files
- `frontend/packages/ui/src/services/chatSyncServiceSenders.ts` — Current 2856-line monolith to replace
- `frontend/packages/ui/src/services/sendersChatMessages.ts` — 1655 lines, message sending + encrypted storage
- `frontend/packages/ui/src/services/sendersChatManagement.ts` — 341 lines, chat CRUD
- `frontend/packages/ui/src/services/sendersDrafts.ts` — 129 lines, draft management
- `frontend/packages/ui/src/services/sendersEmbeds.ts` — 90 lines, embed operations
- `frontend/packages/ui/src/services/sendersSync.ts` — 631 lines, sync utilities

### Consumers (files that import from chatSyncServiceSenders)
- `frontend/packages/ui/src/services/chatSyncService.ts` — Lines 59, 61 (static imports)
- `frontend/packages/ui/src/services/chatSyncServiceHandlersAppSettings.ts`
- `frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts`
- `frontend/packages/ui/src/services/chatSyncServiceHandlersChatUpdates.ts`

### Test Files
- `frontend/packages/ui/src/services/encryption/__tests__/import-audit.test.ts` — ARCH-03 enforcement test

### Milestone Audit
- `.planning/v1.0-MILESTONE-AUDIT.md` — Documents ARCH-03 gap and orphaned sub-modules

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- 5 sender sub-modules already exist with correct encryptor imports — no new code to write
- `chatSyncService.ts` imports via `import * as senders from "./chatSyncServiceSenders"` — barrel re-exports will satisfy this

### Established Patterns
- Phase 2 used the same extract-and-redirect barrel pattern for cryptoService.ts → MessageEncryptor/MetadataEncryptor
- The barrel must preserve all export names for dynamic import compatibility

### Integration Points
- `chatSyncService.ts` line 59: `import * as senders from "./chatSyncServiceSenders"` — must continue to resolve
- `chatSyncService.ts` line 61: `import { sendOfflineChangesImpl } from "./chatSyncServiceSenders"` — named import
- Several handler files import from chatSyncServiceSenders — all must continue to work
- `import-audit.test.ts` line 19 includes `chatSyncServiceSenders.ts` in its scan — will enforce zero cryptoService imports after swap

</code_context>

<specifics>
## Specific Ideas

- This is a gap closure from a merge issue — the work was done in Phase 4 but didn't persist on dev
- Sub-modules already have the correct imports (MessageEncryptor/MetadataEncryptor instead of cryptoService)
- The monolith currently has 9 cryptoService references that violate ARCH-03

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 08-sender-barrel-deployment*
*Context gathered: 2026-03-27*
