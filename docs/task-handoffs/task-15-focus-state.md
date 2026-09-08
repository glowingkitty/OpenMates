# TASK-15 / TASK-2879 focus display handoff

- Worker: session `6456`, Codex thread `01a080f2-2611-70c0-9061-bd540f285cb8`, worktree `agent-6456`.
- Coordinator: TASK-5745, session `4aa6`.
- State: awaiting exact Specification approval; no product or test edits.
- Draft: `specifications/features/focus-activation-display/`; validation passed, fingerprint `3623d49d4299764e87ca0f198bcea52cde137d5f8fd941827bd93f945e6e65fd`.

## Findings

`FocusModeActivationRenderer.ts` starts from `alreadyActive=false` and only suppresses the countdown when current IndexedDB focus metadata indicates active. Missing metadata and lookup failures therefore permit a countdown. Generic embed `finished` does not prove activation completed: the backend creates finished embeds before its pending cancellation window ends. The component's module-level activated-ID set cannot survive page reloads. Do not simply treat every finished embed as completed or every historical activation as currently active.

`FocusModeActivationEmbed.svelte` starts a four-second timer on mount unless already active/rejected; timer completion invokes persistence through the renderer. The fix must positively establish live pending eligibility and bind callbacks to the originating chat, while historical rendering remains side-effect free.

Banner location: `enter_message/MessageInput.styles.css`, `.focus-pill` currently `top: -20px`. The class is also used by incognito and IdeaBucket pills. Scope the requested approximately 10px lift to the active focus banner; coordinate with TASK-5147 before any shared composer edits. Coordination activity was posted; no shared files claimed.

## Verification and next steps

1. Obtain exact PDF approval and record its generated review artifact with `specifications.py approve`.
2. Extend existing regression coverage and add required isolated component proof with contract metadata. Cover live cancellation, completed/reloaded history, examples/shares without metadata, and phone/laptop banner geometry.
3. The unchanged existing `focus-mode-ui-after-activation.spec.ts` was submitted through `tests.py run --session 6456`; request `7f1af6598a3c1f749307a828af6eec256e4b9fb9ab0827cad013097b07a7a1ee`, source `07ec08b7fad0d0373f806d929b86ecf4d4c04b33`. It was queued at last check, not red evidence and not proof of this bug. Use cached coordinator status/result; do not duplicate dispatch.
4. Reproduce before product edits, lease exact files, implement the smallest fix, then complete admitted isolated CI/component proof. Preserve migration holds and do not invoke old shared-dev test workflows.
5. No audio, example transcripts, registry, ActiveChat, backend protocol, or production changes made.

## Visible worker reconciliation

- Activated session: `32ef`; isolated worktree `agent-32ef`, distinct from `agent-6456` and coordinator `agent-4aa6`.
- Actual Codex thread: `01a080f6-c97b-7332-9d61-997585560557`.
- Preserved 6456 draft unchanged; no competing product/test edits or repeated test dispatch.
- Task activity reads returned HTTP 429; task connection did not acknowledge before coordinator pause. All Tasks API operations paused pending serialized coordinator recovery. Attribution is not claimed complete.
- Exact draft approval remains required before implementation.

## Unified contract redirect

- User superseded unapproved focus-display draft; replaced only this worktree copy with feature.focus-modes. Original worker 6456 draft remains untouched.
- Search: local and canonical specifications had composer/SDK fragments but no unified focus-mode contract. Career worker e54d has focus-specific draft feature.career-insights.
- TASK-2879 actual thread connection acknowledged. Coordination activity acknowledged on TASK-2879 and TASK-6436; career worker retains restoration implementation.
- Source evidence: main_processor.py:3207 reads inline system_prompt only; :5728 retains built prompt after AI deactivation. These are inspection findings, not passing behavioral evidence.
- Existing focus-mode-ui-after-activation.spec.ts check-test fails missing contract-test metadata. No new E2E run dispatched.
- Unified draft has ten requirements with two examples each; original display approval artifact is obsolete and must not be approved.

- User approved the design boundary only: Specifications define observable guarantees with concrete examples; exact prompt wording and tactics stay in app instructions. Updated full-instruction and specialization requirements/examples accordingly; no fingerprint approval inferred. Prior unified PDF is obsolete. Task history refresh returned HTTP 502; continued from acknowledged local history.
