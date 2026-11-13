import { reconcileCommittedRevision } from '../../../services/embedUserRevisionHistory';

/** A durable server receipt wins over a later IndexedDB failure. Never retry that save. */
export const reconcileCommittedDiagramRevision = reconcileCommittedRevision;

/** A pending atomic commit resolves its own conflict; its broadcast is not a rival edit. */
export function classifyDiagramRevisionBroadcast(saving: boolean, editing: boolean): 'defer' | 'conflict' | 'refresh' {
  if (saving) return 'defer';
  return editing ? 'conflict' : 'refresh';
}
