/**
 * frontend/packages/ui/src/services/embedStateMachine.ts
 *
 * Embed Status State Machine — canonical frontend definition of valid embed statuses
 * and transitions. This module mirrors the backend definition in
 * backend/shared/python_schemas/embed_status.py and must stay in sync.
 *
 * Architecture: docs/architecture/embeds.md — "Embed State Machine" section
 *
 * State diagram:
 *     (initial) ──► PROCESSING ──► FINISHED
 *                         │
 *                         ├──► ERROR
 *                         │
 *                         └──► CANCELLED
 *
 *     FINISHED ──► ERROR  (frontend-only: decryption failure)
 *
 * Terminal states: FINISHED, ERROR, CANCELLED
 */

// ── Status enum ─────────────────────────────────────────────────────────────

/** All valid embed statuses. Used as the single source of truth across the frontend. */
export const EmbedStatus = {
  PROCESSING: "processing",
  FINISHED: "finished",
  ERROR: "error",
  CANCELLED: "cancelled",
} as const;

export type EmbedStatusValue = (typeof EmbedStatus)[keyof typeof EmbedStatus];

// ── Allowed transitions ─────────────────────────────────────────────────────

/**
 * Map of current status → set of valid target statuses.
 * Any transition not listed here is invalid and will be rejected.
 */
const ALLOWED_TRANSITIONS: Record<
  EmbedStatusValue,
  ReadonlySet<EmbedStatusValue>
> = {
  [EmbedStatus.PROCESSING]: new Set([
    EmbedStatus.PROCESSING, // streaming updates (content changes, status stays)
    EmbedStatus.FINISHED, // normal completion
    EmbedStatus.ERROR, // skill failure
    EmbedStatus.CANCELLED, // user pressed stop
  ]),
  [EmbedStatus.FINISHED]: new Set([
    EmbedStatus.ERROR, // frontend-only: decryption failure on stored embed
  ]),
  [EmbedStatus.ERROR]: new Set(), // terminal — no transitions out
  [EmbedStatus.CANCELLED]: new Set(), // terminal — no transitions out
};

/** Set of terminal statuses — embeds in these states should not transition further. */
export const TERMINAL_STATUSES: ReadonlySet<EmbedStatusValue> = new Set([
  EmbedStatus.FINISHED,
  EmbedStatus.ERROR,
  EmbedStatus.CANCELLED,
]);

// ── All valid status values (for runtime validation) ────────────────────────

const VALID_STATUSES: ReadonlySet<string> = new Set(Object.values(EmbedStatus));

// ── Validation functions ────────────────────────────────────────────────────

/**
 * Check whether a string is a valid EmbedStatusValue.
 */
export function isValidEmbedStatus(value: unknown): value is EmbedStatusValue {
  return typeof value === "string" && VALID_STATUSES.has(value);
}

/**
 * Validate whether transitioning from `current` to `target` is allowed.
 *
 * @param current - Current embed status
 * @param target - Desired new embed status
 * @param embedId - Embed ID for logging context (optional)
 * @returns true if the transition is valid, false otherwise
 */
export function validateEmbedTransition(
  current: string,
  target: string,
  embedId: string = "",
): boolean {
  if (!isValidEmbedStatus(current)) {
    console.warn(
      `[EmbedStateMachine] Unknown current status '${current}' for embed ${embedId}`,
    );
    return false;
  }

  if (!isValidEmbedStatus(target)) {
    console.warn(
      `[EmbedStateMachine] Unknown target status '${target}' for embed ${embedId}`,
    );
    return false;
  }

  const allowed = ALLOWED_TRANSITIONS[current];
  if (allowed.has(target)) {
    return true;
  }

  console.warn(
    `[EmbedStateMachine] Invalid transition: '${current}' → '${target}' for embed ${embedId}. ` +
      `Allowed from '${current}': [${Array.from(allowed).sort().join(", ")}]`,
  );
  return false;
}

/**
 * Check if an embed status is terminal (no further transitions expected,
 * except FINISHED → ERROR for decryption failures).
 */
export function isTerminalStatus(status: string): boolean {
  return isValidEmbedStatus(status) && TERMINAL_STATUSES.has(status);
}

/**
 * Normalize an unknown value to a valid EmbedStatusValue.
 * Unknown or null/undefined values default to FINISHED (matches existing behavior
 * in normalizeEmbedStatus functions throughout the codebase).
 */
export function normalizeEmbedStatus(value: unknown): EmbedStatusValue {
  if (isValidEmbedStatus(value)) {
    return value;
  }
  // "completed" is a known alias used by some backend events
  if (value === "completed") {
    return EmbedStatus.FINISHED;
  }
  return EmbedStatus.FINISHED;
}
