// Purpose: Shared timestamp normalization helpers for chat/embed payloads.
// Purpose: Ensures we safely accept both Unix seconds and Unix milliseconds.
// Architecture: Keeps client/server timestamp unit handling centralized.
// Architecture: See docs/architecture/sync.md for sync context.
// Tests: N/A (manual verification via embed persistence flow)

const UNIX_SECONDS_MILLISECONDS_THRESHOLD = 10_000_000_000;

export function normalizeToUnixSeconds(
  timestamp: number | null | undefined,
  fallbackSeconds = Math.floor(Date.now() / 1000),
): number {
  if (
    typeof timestamp !== "number" ||
    !Number.isFinite(timestamp) ||
    timestamp <= 0
  ) {
    return fallbackSeconds;
  }

  if (timestamp >= UNIX_SECONDS_MILLISECONDS_THRESHOLD) {
    return Math.floor(timestamp / 1000);
  }

  return Math.floor(timestamp);
}
