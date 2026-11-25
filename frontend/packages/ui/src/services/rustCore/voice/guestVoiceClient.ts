/** Browser binding for the core's credential-free guest voice wire format. */
import { parseCall } from '../parse/parseClient';

export interface GuestVoiceSocketPlan {
  url: string;
  start: string;
  pause: string;
  quiet: string;
  ping: string;
  hangup: string;
}

export type GuestVoiceEvent =
  | { type: 'ready' | 'ended' | 'limit' }
  | { type: 'error'; code: string }
  | { type: 'waiting'; active: boolean; line: VoiceCallWaitingLine }
  | { type: 'transcript'; messageId: string; text: string; submitted: boolean };

interface GuestVoiceProtocol {
  connect: { request: { base: string; anonymous_id: string }; response: GuestVoiceSocketPlan };
  receive: { request: { frame: string }; response: GuestVoiceEvent | null };
  speech: { request: { base: string; anonymous_id: string; markdown: string; language: string };
    response: { url: string; bodies: string[] } };
}

export async function guestVoicePlan<K extends keyof GuestVoiceProtocol>(
  operation: K, payload: GuestVoiceProtocol[K]['request'],
): Promise<GuestVoiceProtocol[K]['response']> {
  const output = await parseCall('guestVoice', { input: JSON.stringify({ operation, ...payload }) });
  return JSON.parse(output) as GuestVoiceProtocol[K]['response'];
}

/** The browser socket takes the core-produced frame as opaque serialized text. */
export function guestVoiceMicrophoneFrame(data: string): Promise<string> {
  return parseCall('guestVoice', { input: JSON.stringify({ operation: 'microphone', data }) });
}
import type { VoiceCallWaitingLine } from '../../voiceCallWaiting';
