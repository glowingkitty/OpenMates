/**
 * Presentation-only encrypted system event: a Memory request in a voice call
 * got no tap in time, so the assistant answered without memories.
 * Written by voiceCallPermissionPrompt.ts; never sent to the AI as history.
 */
export const MEMORY_REQUEST_TIMED_OUT_EVENT = 'memory_request' as const;
export interface MemoryRequestTimedOutEvent {
  schema_version: 1;
  type: typeof MEMORY_REQUEST_TIMED_OUT_EVENT;
  action: 'timed_out';
  request_id: string;
  created_at: number;
}

/** Only well-formed encrypted system contents become this notice. */
export function parseMemoryRequestTimedOutEvent(content: string): MemoryRequestTimedOutEvent | null {
  if (!content || !content.includes('"memory_request"')) return null;
  try {
    const event = JSON.parse(content);
    return event?.schema_version === 1 && event.type === MEMORY_REQUEST_TIMED_OUT_EVENT &&
      event.action === 'timed_out' && typeof event.request_id === 'string' &&
      /^[A-Za-z0-9_-]{4,128}$/.test(event.request_id) &&
      Number.isSafeInteger(event.created_at) && event.created_at > 0 ? event : null;
  } catch { return null; }
}

export function memoryRequestTimedOutMessageId(requestId: string): string {
  return `memory-request-timed-out-${requestId}`;
}
