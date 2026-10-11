/** A durable server receipt wins over a later IndexedDB failure. Never retry that save. */
export async function reconcileCommittedDiagramRevision(updateLocal: () => Promise<void>): Promise<boolean> {
  try { await updateLocal(); return true; }
  catch { return false; }
}

/** A pending atomic commit resolves its own conflict; its broadcast is not a rival edit. */
export function classifyDiagramRevisionBroadcast(saving: boolean, editing: boolean): 'defer' | 'conflict' | 'refresh' {
  if (saving) return 'defer';
  return editing ? 'conflict' : 'refresh';
}
