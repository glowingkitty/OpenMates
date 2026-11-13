import { requiresInitialSnapshot } from '../../../services/embedUserRevisionHistory';

/** Immutable version-one rows are reused; only legacy heads without history need a seed. */
export const requiresInitialDiagramSnapshot = requiresInitialSnapshot;

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
