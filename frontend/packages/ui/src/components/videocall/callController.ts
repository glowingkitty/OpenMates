/**
 * Browser session controller for the standalone video call experiment.
 * It uses the existing OpenMates auth token and a first-party WebSocket.
 * Video clips live only as revocable Blob URLs in this process.
 * The server owns billing figures, duration limits and visual generation.
 */
import { get, writable, type Readable } from 'svelte/store';
import { text } from '../../i18n/translations';
import { getApiUrl } from '../../config/api';
import { getWebSocketToken } from '../../utils/cookies';
import { getSessionId } from '../../utils/sessionId';
import { checkAuth } from '../../stores/authSessionActions';
import { websocketTokenNeedsRefresh } from '../../services/audioRealtimeTranscription';
import { CallAudio } from './callAudio';

export type CallStatus = 'idle' | 'connecting' | 'live' | 'ended' | 'error';
export interface CallTranscript { role: 'user' | 'model'; text: string; final: boolean }
export interface CallClip { id: string; url: string; durationSeconds: number }
export interface CallUsage {
  elapsed_seconds: number;
  credits_accrued: number;
  credits_charged: number;
  audio_credits: number;
  video_credits: number;
  gemini_input_tokens: number;
  gemini_output_tokens: number;
  gemini_context_tokens: number;
  h3_generated_seconds: number;
  audio_credits_per_minute: number;
  video_credits_per_minute: number;
}
export interface CallState {
  status: CallStatus;
  error: string | null;
  elapsedSeconds: number;
  maxDurationSeconds: number;
  visualsAllowed: boolean;
  videoStatus: 'off' | 'queued' | 'playing';
  videoPending: boolean;
  videoDraining: boolean;
  clips: CallClip[];
  transcripts: CallTranscript[];
  usage: CallUsage | null;
  userSpeaking: boolean;
  modelSpeaking: boolean;
}
export interface CallControllerLike extends Readable<CallState> {
  start(): Promise<void>;
  stopVisuals(): void;
  allowVisuals(): void;
  hangup(): void;
  sendVideoFrame(data: string): void;
  sendContinuationFrame(clipId: string, data: string): void;
  videoPlaybackEnded(clipId: string): void;
  dispose(): void;
}

export const initialCallState: CallState = {
  status: 'idle', error: null, elapsedSeconds: 0, maxDurationSeconds: 120,
  visualsAllowed: true, videoStatus: 'off', videoPending: false, videoDraining: false, clips: [], transcripts: [], usage: null,
  userSpeaking: false, modelSpeaking: false,
};

const EMPTY_USAGE: CallUsage = {
  elapsed_seconds: 0, credits_accrued: 0, credits_charged: 0, audio_credits: 0, video_credits: 0,
  gemini_input_tokens: 0, gemini_output_tokens: 0, gemini_context_tokens: 0,
  h3_generated_seconds: 0, audio_credits_per_minute: 0, video_credits_per_minute: 0,
};

function callText(key: string): string { return get(text)(`videocall.${key}`); }
class CallStartFailure extends Error { constructor(public key: string) { super(key); } }
function microphoneErrorKey(error: unknown): string {
  const name = error instanceof Error ? error.name : '';
  if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError') return 'microphone_denied';
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') return 'microphone_missing';
  return 'microphone_failed';
}

export class VideoCallController implements CallControllerLike {
  private store = writable<CallState>({ ...initialCallState });
  subscribe = this.store.subscribe;
  private state: CallState = { ...initialCallState };
  private socket: WebSocket | null = null;
  private audio: CallAudio | null = null;
  private ticker: ReturnType<typeof setInterval> | null = null;
  private startedAt = 0;
  private generation = 0;
  private lastVideoFrameAt = 0;
  private videoDrainComplete = false;
  private playedClipIds = new Set<string>();
  private visualsStoppedExplicitly = false;

  private update(patch: Partial<CallState>): void {
    this.state = { ...this.state, ...patch };
    this.store.set(this.state);
  }

  private send(message: Record<string, unknown>): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(message));
  }

  async start(): Promise<void> {
    if (this.state.status === 'connecting' || this.state.status === 'live') return;
    this.hangup();
    const generation = ++this.generation;
    this.visualsStoppedExplicitly = false;
    this.update({ ...initialCallState, status: 'connecting' });
    const audio = new CallAudio(
      (data) => this.send({ type: 'mic_audio', data }),
      (userSpeaking, modelSpeaking) => this.update({ userSpeaking, modelSpeaking }),
    );
    this.audio = audio;
    let microphoneReady = false;
    try {
      // The browser permission prompt starts inside the button's gesture.
      await audio.start();
      microphoneReady = true;
      if (generation !== this.generation) return;
      let token = getWebSocketToken();
      if (websocketTokenNeedsRefresh(token)) {
        if (!await checkAuth(undefined, true)) throw new CallStartFailure('session_expired');
        token = getWebSocketToken();
      }
      if (!token || websocketTokenNeedsRefresh(token)) throw new CallStartFailure('auth_unavailable');
      if (generation !== this.generation) return;
      const url = new URL(`${getApiUrl().replace(/^http/, 'ws')}/v1/experiment/videocall`);
      url.searchParams.set('sessionId', getSessionId());
      url.searchParams.set('token', token);
      const socket = new WebSocket(url);
      this.socket = socket;
      socket.onmessage = (event: MessageEvent<string>) => {
        if (generation !== this.generation) return;
        try { this.handleMessage(JSON.parse(event.data) as Record<string, unknown>); }
        catch { this.update({ error: callText('invalid_response') }); this.finish('error'); }
      };
      socket.onerror = () => { if (generation === this.generation) { this.update({ error: callText('connection_lost') }); this.finish('error'); } };
      socket.onclose = () => {
        if (generation !== this.generation) return;
        if (this.state.status === 'connecting') { this.update({ error: callText('connection_failed') }); this.finish('error'); }
        else this.finish('ended');
      };
    } catch (error) {
      if (generation !== this.generation) return;
      const key = error instanceof CallStartFailure ? error.key : microphoneReady ? 'could_not_start' : microphoneErrorKey(error);
      this.update({ status: 'error', error: callText(key) });
      audio.stop();
    }
  }

  private handleMessage(message: Record<string, unknown>): void {
    switch (message.type) {
      case 'ready': {
        const max = Number(message.max_duration_seconds);
        this.startedAt = Date.now();
        this.update({
          status: 'live', maxDurationSeconds: Number.isFinite(max) && max > 0 ? max : 120,
          usage: {
            ...EMPTY_USAGE,
            audio_credits_per_minute: Number(message.audio_credits_per_minute) || 0,
            video_credits_per_minute: Number(message.video_credits_per_minute) || 0,
          },
        });
        if (this.ticker) clearInterval(this.ticker);
        this.ticker = setInterval(() => this.update({ elapsedSeconds: Math.min(this.state.maxDurationSeconds, Math.floor((Date.now() - this.startedAt) / 1000)) }), 250);
        break;
      }
      case 'audio_chunk':
        if (typeof message.data === 'string') this.audio?.playPcm16(message.data, 24_000);
        break;
      case 'audio.interrupted':
        this.audio?.interrupt();
        break;
      case 'transcript':
        if ((message.role === 'user' || message.role === 'model') && typeof message.text === 'string') {
          const entries = [...this.state.transcripts];
          const last = entries[entries.length - 1];
          if (last?.role === message.role && !last.final) {
            const fragment = message.text;
            const combined = fragment.startsWith(last.text) ? fragment : last.text + fragment;
            entries[entries.length - 1] = { role: message.role, text: combined, final: message.final === true };
          } else if (message.text) {
            entries.push({ role: message.role, text: message.text, final: message.final === true });
          }
          this.update({ transcripts: entries.slice(-50) });
        }
        break;
      case 'video.queued':
        if (this.state.visualsAllowed) this.update({ videoStatus: this.state.clips.length ? 'playing' : 'queued', videoPending: true });
        break;
      case 'video.ready': {
        if (this.state.status !== 'live' || this.visualsStoppedExplicitly || (!this.state.visualsAllowed && (!this.state.videoDraining || this.videoDrainComplete)) || typeof message.data !== 'string' || message.data.length > 28_000_000 || typeof message.clip_id !== 'string') break;
        const binary = atob(message.data);
        const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
        const url = URL.createObjectURL(new Blob([bytes], { type: 'video/mp4' }));
        const clips = [...this.state.clips, { id: message.clip_id, url, durationSeconds: Number(message.duration_seconds) || 5 }];
        for (const expired of clips.slice(0, -4)) URL.revokeObjectURL(expired.url);
        this.update({ clips: clips.slice(-4), videoStatus: 'playing', videoPending: false });
        break;
      }
      case 'video.stopped':
        if (message.reason === 'idle' && message.finish_playback === true && !this.visualsStoppedExplicitly) {
          this.videoDrainComplete = false;
          this.update({ visualsAllowed: false, videoDraining: true, videoPending: message.pending_clip === true, videoStatus: this.state.clips.length ? 'playing' : message.pending_clip === true ? 'queued' : 'off' });
        } else {
          this.visualsStoppedExplicitly = true;
          this.clearVisuals();
          this.update({ visualsAllowed: false });
        }
        break;
      case 'video.drain_complete':
        if (!this.state.videoDraining) break;
        this.videoDrainComplete = true;
        this.update({ videoPending: false });
        this.finishVideoDrain();
        break;
      case 'usage': {
        const usage = { ...EMPTY_USAGE };
        for (const key of Object.keys(usage) as (keyof CallUsage)[]) {
          const value = Number(message[key]);
          usage[key] = Number.isFinite(value) && value >= 0 ? value : 0;
        }
        this.update({ usage });
        break;
      }
      case 'error':
        if (message.code === 'video_unavailable') {
          this.update({ error: callText('visual_unavailable'), videoStatus: this.state.clips.length ? 'playing' : 'off', videoPending: false });
          break;
        }
        this.update({ error: callText('call_unavailable') });
        this.finish('error');
        break;
      case 'ended':
        this.finish('ended');
        break;
    }
  }

  sendVideoFrame(data: string): void {
    if (this.state.status !== 'live' || this.visualsStoppedExplicitly || (!this.state.visualsAllowed && !this.state.videoDraining)) return;
    const now = Date.now();
    if (now - this.lastVideoFrameAt < 1_000) return;
    this.lastVideoFrameAt = now;
    this.send({ type: 'video_frame', data, mime_type: 'image/jpeg' });
  }

  sendContinuationFrame(clipId: string, data: string): void {
    if (this.state.status === 'live' && this.state.visualsAllowed) this.send({ type: 'continuation_frame', clip_id: clipId, data, source: 'continuation' });
  }

  videoPlaybackEnded(clipId: string): void {
    if (!this.state.clips.some((clip) => clip.id === clipId)) return;
    this.playedClipIds.add(clipId);
    this.finishVideoDrain();
  }

  private finishVideoDrain(): void {
    if (this.state.videoDraining && this.videoDrainComplete && this.state.clips.every((clip) => this.playedClipIds.has(clip.id))) this.clearVisuals();
  }

  private clearVisuals(): void {
    this.state.clips.forEach((clip) => URL.revokeObjectURL(clip.url));
    this.playedClipIds.clear();
    this.videoDrainComplete = false;
    this.update({ clips: [], videoStatus: 'off', videoPending: false, videoDraining: false });
  }

  stopVisuals(): void {
    this.visualsStoppedExplicitly = true;
    this.update({ visualsAllowed: false });
    this.clearVisuals();
    this.send({ type: 'stop_visuals' });
  }

  allowVisuals(): void {
    this.visualsStoppedExplicitly = false;
    this.videoDrainComplete = false;
    this.update({ visualsAllowed: true, videoDraining: false });
    this.send({ type: 'allow_visuals' });
  }

  private finish(status: 'ended' | 'error'): void {
    if (this.ticker) clearInterval(this.ticker);
    this.ticker = null;
    this.audio?.stop();
    this.audio = null;
    if (this.socket) this.socket.onclose = null;
    this.socket?.close();
    this.socket = null;
    this.clearVisuals();
    this.update({ status, userSpeaking: false, modelSpeaking: false });
  }

  hangup(): void {
    this.generation += 1;
    this.send({ type: 'hangup' });
    this.finish('ended');
  }

  dispose(): void { this.hangup(); }
}
