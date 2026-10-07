/**
 * Deterministic bare-preview states for the isolated call surface.
 * Synthetic local MP4 clips exercise clip switching without provider calls.
 * The controller implements the same interface as the production controller.
 * Preview actions mutate only in-memory state and never request a microphone.
 */
import { writable } from 'svelte/store';
import { initialCallState, type CallControllerLike, type CallState } from './callController';
import { CallAudio } from './callAudio';
import clipA from '../../../../../apps/web_app/tests/fixtures/video-call-clip-a.mp4?url';
import clipB from '../../../../../apps/web_app/tests/fixtures/video-call-clip-b.mp4?url';
import audioClip from '../../../../../apps/web_app/tests/fixtures/video-call-clip-audio.webm?url';
import mp4AudioClip from '../../../../../apps/web_app/tests/fixtures/video-call-clip-audio.mp4?url';

class PreviewCallController implements CallControllerLike {
  private store;
  subscribe;
  private state: CallState;
  private drainComplete = false;
  private playedClips = new Set<string>();
  private audio: CallAudio | null = null;

  constructor(initial: Partial<CallState> = {}) {
    this.state = { ...initialCallState, ...initial };
    this.store = writable(this.state);
    this.subscribe = this.store.subscribe;
    if (typeof window !== 'undefined') {
      window.addEventListener('video-call-preview-event', (event) => {
        const detail = (event as CustomEvent<{ type: string }>).detail;
        if (detail.type === 'queued') this.update({ videoStatus: 'playing', videoPending: true });
        if (detail.type === 'idle') this.update({ visualsAllowed: false, videoDraining: true, videoPending: false });
        if (detail.type === 'idle_pending') this.update({ visualsAllowed: false, videoDraining: true, videoPending: true });
        if (detail.type === 'drain_complete') { this.drainComplete = true; this.update({ videoPending: false }); this.finishDrain(); }
        if (detail.type === 'audio_interrupted') this.update({ modelSpeaking: false });
        if (detail.type === 'model_speaking') this.update({ modelSpeaking: true, userSpeaking: false });
        if (detail.type === 'user_speaking') this.update({ modelSpeaking: false, userSpeaking: true });
        if (detail.type === 'silence') this.update({ modelSpeaking: false, userSpeaking: false });
        if (detail.type === 'ready') {
          if (!this.state.visualsAllowed && (!this.state.videoDraining || this.drainComplete)) return;
          const first = this.state.clips.length === 0;
          this.update({ clips: [...this.state.clips, { id: first ? '1' : '2', url: first ? clipA : clipB, durationSeconds: 1.5 }], videoPending: false, videoStatus: 'playing' });
        }
        if (detail.type === 'ready_audio' || detail.type === 'ready_mp4_audio') {
          if (this.state.status !== 'live' || !this.state.visualsAllowed) return;
          this.update({ clips: [{ id: detail.type, url: detail.type === 'ready_audio' ? audioClip : mp4AudioClip, durationSeconds: 1.5 }], videoPending: false, videoStatus: 'playing' });
        }
      });
    }
  }

  private update(patch: Partial<CallState>) {
    this.state = { ...this.state, ...patch };
    this.store.set(this.state);
  }

  private finishDrain() {
    if (this.state.videoDraining && this.drainComplete && this.state.clips.every((clip) => this.playedClips.has(clip.id))) {
      this.playedClips.clear();
      this.update({ videoDraining: false, videoStatus: 'off', videoPending: false, clips: [] });
    }
  }

  async start() {
    this.audio?.stop();
    this.audio = new CallAudio(() => {}, () => {});
    this.audio.unlock();
    this.drainComplete = false; this.playedClips.clear();
    this.update({ status: 'live', error: null, elapsedSeconds: 1, clips: [], visualsAllowed: true, videoStatus: 'off', videoPending: false, videoDraining: false, transcripts: [{ role: 'model', text: 'Hi! What would you like to explore?', final: true }] });
  }
  stopVisuals() { this.drainComplete = false; this.playedClips.clear(); this.update({ visualsAllowed: false, videoDraining: false, videoStatus: 'off', videoPending: false, clips: [] }); }
  allowVisuals() { this.drainComplete = false; this.update({ visualsAllowed: true, videoDraining: false, videoStatus: 'queued' }); }
  hangup() { this.audio?.stop(); this.audio = null; this.drainComplete = false; this.playedClips.clear(); this.update({ status: 'ended', videoDraining: false, videoStatus: 'off', videoPending: false, clips: [] }); }
  sendVideoFrame() { /* Preview transport is inert. */ }
  sendContinuationFrame(clipId: string) { window.dispatchEvent(new CustomEvent('video-call-preview-continuation', { detail: clipId })); }
  videoPlaybackEnded(clipId: string) { this.playedClips.add(clipId); this.finishDrain(); }
  setVideoElement(video: HTMLVideoElement | null) { this.audio?.setVideoElement(video); }
  setVideoGain(value: number) { this.audio?.setVideoGain(value); }
  dispose() { this.audio?.stop(); this.audio = null; }
}

const usage = {
  elapsed_seconds: 28, credits_accrued: 192.88, credits_charged: 193, audio_credits: 12.88, video_credits: 180,
  gemini_input_tokens: 320, gemini_output_tokens: 92, gemini_context_tokens: 684,
  h3_generated_seconds: 10, audio_credits_per_minute: 27.6, video_credits_per_minute: 1080,
};
const transcript = [
  { role: 'user' as const, text: 'Can you explain how an aurora works?', final: true },
  { role: 'model' as const, text: 'Charged particles from the Sun meet gases high in Earth’s atmosphere.', final: true },
];
const onLeave = () => window.dispatchEvent(new Event('video-call-preview-leave'));
export default { controller: new PreviewCallController(), onLeave };
export const variants = {
  live: { controller: new PreviewCallController({ status: 'live', elapsedSeconds: 28, transcripts: transcript, usage }), onLeave },
  visuals: { controller: new PreviewCallController({ status: 'live', videoStatus: 'playing', clips: [{ id: '1', url: clipA, durationSeconds: 1.5 }], elapsedSeconds: 38, transcripts: transcript, usage }), onLeave },
  error: { controller: new PreviewCallController({ status: 'error', error: 'Microphone access was denied.' }), onLeave },
};
export const layout = 'fill';
