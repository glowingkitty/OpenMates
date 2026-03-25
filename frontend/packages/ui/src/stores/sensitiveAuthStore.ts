/**
 * Sensitive Auth Store — remembers recent identity verification for 2 minutes.
 *
 * When a user successfully completes SecurityAuth (passkey / 2FA / password),
 * we record a timestamp here. Any subsequent sensitive action within the next
 * 2 minutes is allowed without re-prompting the user.
 *
 * Architecture context: docs/architecture/security.md
 * Used by: SettingsHidePersonalData (personal data contact entry editing)
 *
 * Intentionally kept in memory only (no persistence). A page reload always
 * requires a fresh auth challenge, which is the correct security posture.
 */

// ─── 2-minute grace period ────────────────────────────────────────────────────
const SENSITIVE_AUTH_GRACE_MS = 2 * 60 * 1000; // 2 minutes in milliseconds

/** Timestamp (ms) of the last successful sensitive-operation auth. null = never verified. */
let lastVerifiedAt: number | null = null;

/**
 * Record that the user just successfully verified their identity.
 * Call this inside the `onSuccess` callback of SecurityAuth.
 */
export function recordSensitiveAuthSuccess(): void {
  lastVerifiedAt = Date.now();
}

/**
 * Returns true if the user has verified their identity within the last 2 minutes.
 * If true, skip showing SecurityAuth and proceed directly.
 */
export function isSensitiveAuthValid(): boolean {
  if (lastVerifiedAt === null) return false;
  return Date.now() - lastVerifiedAt < SENSITIVE_AUTH_GRACE_MS;
}

/**
 * Explicitly invalidate the sensitive auth grace period.
 * Call this on logout or account switch.
 */
export function clearSensitiveAuth(): void {
  lastVerifiedAt = null;
}
