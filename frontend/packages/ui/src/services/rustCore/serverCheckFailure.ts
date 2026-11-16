// Classifies a failed server-checked Rust admission (`restore_existing`).
// A server REJECTION (revoked or expired session, failed re-authentication) must
// end the local-read-only session too; an unreachable server (offline) must not,
// so offline-capable units (drafts) keep a borrowable local client.

/** Codes the Worker reports when the server answered and refused the session. */
const SERVER_REJECTION_CODES: ReadonlySet<string> = new Set([
  "session_expired", "reauthentication_required", "authentication_failed", "credential_conflict", "two_factor_required",
]);

/** How long a network-unavailable failure suppresses further server checks (also cleared by the `online` event). */
export const SERVER_CHECK_BACKOFF_MS = 30_000;

/** True when only the network failed: the local-read-only session may be kept or restored. */
export function keepsLocalSessionAfterServerCheckFailure(code: string): boolean {
  return code === "unavailable" || code === "deadline" || code === "other";
}

/**
 * True when the server was unreachable, so further server checks wait for the backoff
 * (or the `online` event). An unexpected failure (`other`) keeps the local session but
 * is not held back, so a transient error while online does not delay server reads.
 */
export function backsOffServerCheck(code: string): boolean {
  return code === "unavailable" || code === "deadline";
}

export function isServerRejection(code: string): boolean {
  return SERVER_REJECTION_CODES.has(code);
}
