import { writable } from 'svelte/store';
import { initialVoiceCallState, type VoiceCallControllerLike, type VoiceCallState } from '../../services/voiceCall';

class PreviewVoiceCall implements VoiceCallControllerLike {
  private store;
  subscribe;
  private state: VoiceCallState;
  constructor(state: Partial<VoiceCallState>) {
    this.state = { ...initialVoiceCallState, chatId: 'preview-chat', ...state };
    this.store = writable(this.state);
    this.subscribe = this.store.subscribe;
  }
  async start() {}
  async submitText() { return true; }
  setMuted(muted: boolean) { this.publish({ muted }); }
  setMinimized(minimized: boolean) { this.publish({ minimized }); }
  hangup() { this.publish({ status: 'ended' }); }
  private publish(patch: Partial<VoiceCallState>) {
    this.state = { ...this.state, ...patch };
    this.store.set(this.state);
  }
}

const usage = {
  elapsed_seconds: 32, credits_accrued: 14.4, credits_charged: 15, audio_credits: 14.4,
  gemini_input_tokens: 340, gemini_output_tokens: 120, audio_credits_per_minute: 27.6,
};
const onReturn = (chatId: string) => window.dispatchEvent(new CustomEvent('voice-call-preview-return', { detail: { chatId } }));
const props = (state: Partial<VoiceCallState>, boundChatVisible = true) => ({
  controller: new PreviewVoiceCall(state), boundChatVisible, onReturn,
});

export default props({ status: 'live', callId: 'preview-call', elapsedSeconds: 32, usage });
export const variants = {
  connecting: props({ status: 'connecting' }),
  muted: props({ status: 'live', callId: 'preview-call', muted: true, elapsedSeconds: 83, usage }),
  away: props({ status: 'live', callId: 'preview-call', elapsedSeconds: 91, usage }, false),
  error: props({ status: 'error', error: 'microphone_denied' }),
};
