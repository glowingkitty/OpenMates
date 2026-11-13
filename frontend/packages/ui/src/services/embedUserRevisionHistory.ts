/**
 * frontend/packages/ui/src/services/embedUserRevisionHistory.ts
 *
 * Dependency-free rules of the client-authored embed revision commit
 * (`embedUserRevision.ts`), kept separate so pure callers and tests do not load
 * the store, socket and sync services.
 */

/** Immutable version-one rows are reused; only heads without history need a seed. */
export function requiresInitialSnapshot(
  currentVersion: number,
  versions: readonly { version_number: number; has_snapshot: boolean }[],
): boolean {
  return currentVersion === 1 && !versions.some((row) => row.version_number === 1 && row.has_snapshot);
}

/** A durable server receipt wins over a later IndexedDB failure. Never retry that save. */
export async function reconcileCommittedRevision(updateLocal: () => Promise<void>): Promise<boolean> {
  try { await updateLocal(); return true; }
  catch { return false; }
}
