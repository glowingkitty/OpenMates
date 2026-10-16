export type AdmissionContextPhase = 'routing' | 'details';

export interface AdmissionContextIdentity {
  chat_id: unknown;
  turn_id: unknown;
  message_id: unknown;
  request_id: unknown;
}

export interface ContextPhaseJournalStorage {
  identity: AdmissionContextIdentity;
  phase: AdmissionContextPhase;
  proposed?: Record<string, unknown>;
  read: () => Promise<string | null>;
  commit: (sealed: string) => Promise<string>;
  seal: (frame: Record<string, unknown>) => Promise<string>;
  open: (sealed: string) => Promise<string | null>;
}

/** Return the exact ciphertext so an unsent phase can be deleted by comparison. */
export async function retainOrReuseContextPhaseFrameWithSeal(
  input: ContextPhaseJournalStorage,
): Promise<{ frame: Record<string, unknown>; sealed: string; created: boolean } | null> {
  const previous = await input.read();
  if (!previous && !input.proposed) return null;
  const candidate = previous ? null : await input.seal(input.proposed!);
  const sealed = previous ?? await input.commit(candidate!);
  const created = candidate !== null && sealed === candidate;
  const plaintext = await input.open(sealed);
  if (!plaintext) throw new Error(`Pending ${input.phase} context cannot be decrypted.`);
  let frame: Record<string, unknown>;
  try { frame = JSON.parse(plaintext) as Record<string, unknown>; }
  catch { throw new Error(`Pending ${input.phase} context is invalid.`); }
  if (frame.chat_id !== input.identity.chat_id || frame.turn_id !== input.identity.turn_id ||
    frame.message_id !== input.identity.message_id || frame.request_id !== input.identity.request_id ||
    frame.phase !== input.phase || !frame.context || typeof frame.context !== 'object' ||
    Array.isArray(frame.context)) {
    throw new Error(`Pending ${input.phase} context has a different turn identity.`);
  }
  return { frame, sealed, created };
}

/** Reuse a phase sealed before a previous send; never recollect a possibly accepted phase. */
export async function retainOrReuseContextPhaseFrame(
  input: ContextPhaseJournalStorage,
): Promise<Record<string, unknown> | null> {
  return (await retainOrReuseContextPhaseFrameWithSeal(input))?.frame ?? null;
}
