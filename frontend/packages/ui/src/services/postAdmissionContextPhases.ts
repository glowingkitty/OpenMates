/** Publish a completed routing phase before waiting for slower selection details. */
export async function publishSelectionDetailsPhases<T>(input: {
  routing: () => Promise<T>;
  details: () => Promise<T>;
  send: (phase: 'routing' | 'details', frame: T) => Promise<void>;
  isCurrent: () => boolean;
}): Promise<void> {
  const routing = await input.routing();
  if (!input.isCurrent()) return;
  await input.send('routing', routing);
  if (!input.isCurrent()) return;
  const details = await input.details();
  if (!input.isCurrent()) return;
  await input.send('details', details);
}

/** A retained legacy routing frame keeps its original field placement on retry. */
export function isSelectionDetailsV2Routing(frame: Record<string, unknown>): boolean {
  const context = frame.context;
  return !!context && typeof context === 'object' && !Array.isArray(context)
    && !Object.prototype.hasOwnProperty.call(context, 'related_task_candidates');
}

/** Report an admitted context failure without substituting an empty successful phase. */
export async function publishContextPreparationFailure(input: {
  identity: { chat_id: string; turn_id: string; message_id: string; request_id: string };
  isCurrent: () => boolean;
  supportsFailure: () => boolean;
  send: (frame: Record<string, unknown>) => Promise<void>;
}): Promise<void> {
  if (!input.isCurrent() || !input.supportsFailure()) return;
  await input.send({ ...input.identity, reason: 'context_preparation_failed' });
}
