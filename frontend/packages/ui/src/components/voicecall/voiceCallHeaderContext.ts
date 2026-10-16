/** Root workspace to nested Header bridge for a call bound to another chat. */
export const VOICE_CALL_PILL_CONTEXT = 'openmates.voiceCallPill';

export type VoiceCallPillContext = () => { onReturn: () => void } | undefined;
