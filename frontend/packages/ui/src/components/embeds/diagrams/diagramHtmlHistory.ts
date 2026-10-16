/** Immutable version-one rows are reused; only legacy heads without history need a seed. */
export function requiresInitialDiagramSnapshot(
  currentVersion: number,
  versions: readonly { version_number: number; has_snapshot: boolean }[],
): boolean {
  return currentVersion === 1 && !versions.some((row) => row.version_number === 1 && row.has_snapshot);
}

/** Keep the canonical head separate from historical display and editing rights. */
export function resolveDiagramVersionView(
  currentVersion: number,
  currentSource: string,
  selection: { version: number; source: string | null; failed?: boolean } | null,
): { source: string; historical: boolean; canEdit: boolean; pending: boolean; unavailable: boolean } {
  if (!selection || selection.version === currentVersion) return { source: currentSource, historical: false, canEdit: true, pending: false, unavailable: false };
  return { source: selection.source ?? currentSource, historical: true, canEdit: false,
    pending: selection.source === null && selection.failed !== true, unavailable: selection.failed === true };
}
