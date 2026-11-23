/** `waiting_*` are the ready-made waiting lines of a call, shown as call events. */
export type VoiceCallHistoryAction = 'started' | 'ended' | 'waiting_start' | 'waiting_resume';
const HISTORY_ACTIONS: readonly string[] = ['started', 'ended', 'waiting_start', 'waiting_resume'];

/** Lifecycle input from the controller, bound to the admitted call's original chat. */
export interface VoiceCallLifecycleEvent {
  type: VoiceCallHistoryAction;
  chatId: string;
  callId: string;
  occurredAt: number;
  activeElapsedSeconds: number;
  /** Millisecond time of a repeatable waiting line; gives each occurrence its own ID. */
  occurredAtMs?: number;
}
export interface VoiceCallHistoryEvent {
  schema_version: 1;
  type: 'voice_call';
  action: VoiceCallHistoryAction;
  call_id: string;
  created_at: number;
  active_elapsed_seconds: number;
}
/** Only encrypted system message contents are interpreted as presentation events. */
export function parseVoiceCallHistoryEvent(content: string): VoiceCallHistoryEvent | null {
  try {
    const event = JSON.parse(content);
    return event?.schema_version === 1 && event.type === 'voice_call' &&
      HISTORY_ACTIONS.includes(event.action) &&
      typeof event.call_id === 'string' && /^[A-Za-z0-9_-]{8,128}$/.test(event.call_id) &&
      Number.isSafeInteger(event.created_at) && event.created_at > 0 &&
      Number.isSafeInteger(event.active_elapsed_seconds) && event.active_elapsed_seconds >= 0 ? event : null;
  } catch { return null; }
}

/** ChatHistory orders equal-second rows lexically by message_id. Call transcript
 * UUIDv7 IDs fall between these ordinal prefixes: start precedes the first turn,
 * and end follows the last turn, while each call/kind keeps a stable identity.
 * Client message IDs are strings; Directus derives its UUID primary key separately.
 */
export function voiceCallLifecycleMessageId(callId: string, action: 'started' | 'ended'): string {
  return `${action === 'started' ? '00000000' : 'ffffffff'}-voice-call-${callId}-${action}`;
}

/** Waiting lines repeat within one call, so each occurrence gets its own ID. It sorts
 * after the start event and before the end event; equal-second order follows the time suffix. */
export function voiceCallWaitingMessageId(callId: string, action: 'waiting_start' | 'waiting_resume', occurredAtMs: number): string {
  return `8${String(Math.floor(occurredAtMs)).padStart(15, '0')}-voice-call-${callId}-${action}`;
}
