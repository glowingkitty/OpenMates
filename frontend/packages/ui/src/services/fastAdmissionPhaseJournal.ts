export type AdmissionContextPhase = 'routing' | 'details';

export interface AdmissionContextIdentity {
  chat_id: unknown;
  turn_id: unknown;
  message_id: unknown;
  request_id: unknown;
}

/** Reuse a phase sealed before a previous send; never recollect a possibly accepted phase. */
export async function retainOrReuseContextPhaseFrame(input: {
  identity: AdmissionContextIdentity;
  phase: AdmissionContextPhase;
  proposed?: Record<string, unknown>;
  read: () => Promise<string | null>;
  commit: (sealed: string) => Promise<string>;
  seal: (frame: Record<string, unknown>) => Promise<string>;
  open: (sealed: string) => Promise<string | null>;
}): Promise<Record<string, unknown> | null> {
  const previous = await input.read();
  if (!previous && !input.proposed) return null;
  const sealed = previous ?? await input.commit(await input.seal(input.proposed!));
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
  return frame;
}
