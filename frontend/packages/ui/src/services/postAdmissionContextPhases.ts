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
