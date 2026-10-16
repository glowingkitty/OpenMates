/** Process-local protection for the sole browser-owned call's transcript rows. */
let activeCallId: string | null = null;
export function setActiveVoiceCallId(callId: string | null): void { activeCallId = callId; }
export function isActiveVoiceCallRow(row: unknown): boolean {
  if (!activeCallId || !row || typeof row !== 'object') return false;
  const call = (row as { call_persistence_v1?: { call_id?: string } }).call_persistence_v1;
  return call?.call_id === activeCallId;
}
