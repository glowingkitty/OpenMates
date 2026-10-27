import { writable } from 'svelte/store';
import { initialVoiceCallState, type VoiceCallControllerLike, type VoiceCallState } from '../../services/voiceCall';

class PreviewVoiceCall implements VoiceCallControllerLike {
  private store;
  subscribe;
  private state: VoiceCallState;
  constructor(state: Partial<VoiceCallState>) {
    this.state = { ...initialVoiceCallState, cameraAvailable: true, activeElapsedSeconds:state.status==='live'?15:0, chatId: 'preview-chat', ...state };
    this.store = writable(this.state);
    this.subscribe = this.store.subscribe;
  }
  async start() {}
  async submitText() { return true; }
  setMuted(muted: boolean) {
    this.publish({ muted, inputIdle: false, userSpeaking: false, billingActivity: { inputListening: !muted, processing: this.state.billingActivity?.processing ?? false } });
  }
  setMinimized(minimized: boolean) { this.publish({ minimized }); }
  async setCameraEnabled(cameraEnabled: boolean) { this.publish({ cameraEnabled, mediaExpanded: cameraEnabled }); }
  async flipCamera() { this.publish({ cameraFacing: this.state.cameraFacing === 'environment' ? 'user' : 'environment' }); }
  setMediaExpanded(mediaExpanded: boolean) { this.publish({ mediaExpanded }); }
  showCamera() { this.publish({ displayedMedia: null, mediaExpanded: true }); }
  selectMedia(mediaIndex: number) { this.publish({ mediaIndex, displayedMedia: this.state.mediaItems[mediaIndex] ?? null }); }
  hangup() { this.publish({ status: 'ended' }); }
  private publish(patch: Partial<VoiceCallState>) {
    this.state = { ...this.state, ...patch };
    this.store.set(this.state);
  }
}

const usage = {
  elapsed_seconds: 32, credits_accrued: 14.4, credits_charged: 15, audio_credits: 14.4,
  stt_duration_seconds: 32,
};
const onReturn = (chatId: string) => window.dispatchEvent(new CustomEvent('voice-call-preview-return', { detail: { chatId } }));
const props = (state: Partial<VoiceCallState>, boundChatVisible = true) => ({
  controller: new PreviewVoiceCall(state), boundChatVisible, onReturn,
});

const listening = { inputListening: true, processing: false };
const suspended = { inputListening: false, processing: false };
export default props({ status: 'live', callId: 'preview-call', elapsedSeconds: 32, activeElapsedSeconds:15, usage, billingActivity: listening });
export const variants = {
  connecting: props({ status: 'connecting' }),
  muted: props({ status: 'live', callId: 'preview-call', muted: true, elapsedSeconds: 83, activeElapsedSeconds:15, usage, billingActivity: suspended }),
  mutedProcessing: props({ status: 'live', callId: 'preview-call', muted: true, elapsedSeconds: 83, activeElapsedSeconds:15, usage,
    billingActivity: { inputListening: false, processing: true } }),
  playbackOnly: props({ status: 'live', callId: 'preview-call', muted: true, assistantSpeaking: true, elapsedSeconds: 83, activeElapsedSeconds:15,
    usage, billingActivity: suspended }),
  vadLoading: props({ status: 'live', callId: 'preview-call', usage, billingActivity: listening }),
  inputIdle: props({ status: 'live', callId: 'preview-call', inputIdle: true, usage, billingActivity: suspended }),
  idleAwaitingServer: props({ status: 'live', callId: 'preview-call', inputIdle: true, usage, billingActivity: listening }),
  idleUnknownBilling: props({ status: 'live', callId: 'preview-call', inputIdle: true, usage }),
  idleProcessing: props({ status: 'live', callId: 'preview-call', inputIdle: true, usage,
    billingActivity: { inputListening: false, processing: true } }),
  idlePlayback: props({ status: 'live', callId: 'preview-call', inputIdle: true, assistantSpeaking: true, usage,
    billingActivity: suspended }),
  resumedSpeech: props({ status: 'live', callId: 'preview-call', userSpeaking: true, assistantSpeaking: true, usage,
    billingActivity: { inputListening: true, processing: true } }),
  away: props({ status: 'live', callId: 'preview-call', elapsedSeconds: 91, activeElapsedSeconds:15, usage, billingActivity: listening }, false),
  error: props({ status: 'error', error: 'microphone_denied' }),
  contextTooLarge: props({ status: 'error', error: 'context_too_large' }),
  contextUnavailable: props({ status: 'error', error: 'context_unavailable' }),
};
