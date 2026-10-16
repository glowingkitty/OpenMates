/** A single browser-owned voice call, fixed to the chat selected at launch. */
import { get, writable, type Readable } from 'svelte/store';
import { getApiUrl } from '../config/api';
import { getWebSocketToken } from '../utils/cookies';
import { getSessionId } from '../utils/sessionId';
import { checkAuth } from '../stores/authSessionActions';
import { authStore } from '../stores/authStore';
import { websocketTokenNeedsRefresh } from './audioRealtimeTranscription';
import { assistantSpeechController } from './assistantSpeechController';
import { markTypedCallMessageFailed, prepareVoiceCallChat, persistTypedCallMessage, upsertCallTranscript, upsertCallArtifact, VoiceCallContextError, type CallTranscriptUpdate } from './voiceCallMessages';
import { setActiveVoiceCallId } from './voiceCallOwnership';
import { loadVoiceProjectContext } from './voiceCallContext';
import { applyVoiceToolEvent, applyVoiceCompression } from './voiceCallTools';
import { voiceArtifactReferenceFromPayload, type VoiceArtifactReference } from './voiceCallArtifactReferences';
import { CallAudio, type CallAudioPlaybackSchedule } from '../components/videocall/callAudio';
import { VoiceCallAudioGate } from './voiceCallAudioGate';
import { recordCallLifecycle } from './voiceCallLifecycle';
import { VoiceCallCuePlayer } from './voiceCallCues';
import { ensureVoiceCallPrivacyAcknowledgement } from './voiceCallPrivacy';

export type VoiceCallStatus = 'idle' | 'connecting' | 'live' | 'ended' | 'error';
export interface VoiceCallUsage {
  elapsed_seconds: number;
  credits_accrued: number;
  credits_charged: number;
  audio_credits: number;
  gemini_input_tokens: number;
  gemini_output_tokens: number;
}
export interface VoiceCallState {
  status: VoiceCallStatus;
  chatId: string | null;
  callId: string | null;
  minimized: boolean;
  muted: boolean;
  elapsedSeconds: number;
  activeElapsedSeconds: number;
  audioLevels: readonly number[];
  inputIdle: boolean;
  userSpeaking: boolean;
  assistantSpeaking: boolean;
  usage: VoiceCallUsage | null;
  billingActivity: { inputListening: boolean; processing: boolean } | null;
  error: string | null;
}
export interface VoiceCallControllerLike extends Readable<VoiceCallState> {
  start(chatId?: string, onBound?: (chatId: string) => void): Promise<void>;
  submitText(chatId: string, text: string): Promise<boolean>;
  setMuted(muted: boolean): void;
  setMinimized(minimized: boolean): void;
  hangup(): void;
}

export const initialVoiceCallState: VoiceCallState = {
  status: 'idle', chatId: null, callId: null, minimized: false, muted: false,
  elapsedSeconds: 0, activeElapsedSeconds: 0, audioLevels: Array(16).fill(0), inputIdle: false, userSpeaking: false, assistantSpeaking: false, usage: null, billingActivity: null, error: null,
};

const NUMBER_FIELDS: (keyof VoiceCallUsage)[] = [
  'elapsed_seconds', 'credits_accrued', 'credits_charged', 'audio_credits',
  'gemini_input_tokens', 'gemini_output_tokens',
];

function microphoneError(error: unknown): string {
  const name = error instanceof Error ? error.name : '';
  if (name === 'NotAllowedError' || name === 'PermissionDeniedError' || name === 'SecurityError') return 'microphone_denied';
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') return 'microphone_missing';
  return 'microphone_failed';
}
class VoiceCallStartError extends Error {
  constructor(readonly key: string) { super(key); }
}

let lastMessageMillis = 0;
let messageSequence = 0;
function sortableMessageId(): string {
  let now = Math.max(Date.now(), lastMessageMillis);
  if (now === lastMessageMillis && messageSequence === 0x0fff) now += 1;
  messageSequence = now === lastMessageMillis ? (messageSequence + 1) & 0x0fff : 0;
  lastMessageMillis = now;
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  for (let index = 5; index >= 0; index -= 1) {
    bytes[index] = Math.floor(now / 2 ** (8 * (5 - index))) & 0xff;
  }
  bytes[6] = 0x70 | (messageSequence >> 8);
  bytes[7] = messageSequence & 0xff;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

const WAVE_BINS = 16;
const WAVE_FRAME_MS = 40;
const zeroLevels = () => Array<number>(WAVE_BINS).fill(0);

function pcmSamples(data: string): Float32Array {
  const bytes = atob(data);
  if (bytes.length % 2) throw new Error('Invalid PCM16');
  const samples = new Float32Array(bytes.length / 2);
  for (let index = 0; index < samples.length; index++) {
    const word = bytes.charCodeAt(index * 2) | (bytes.charCodeAt(index * 2 + 1) << 8);
    samples[index] = (word >= 32768 ? word - 65536 : word) / 32768;
  }
  return samples;
}

function sampleEnvelope(samples: Float32Array): number[] {
  return Array.from({ length: WAVE_BINS }, (_, bin) => {
    const start = Math.floor(bin * samples.length / WAVE_BINS);
    const end = Math.floor((bin + 1) * samples.length / WAVE_BINS);
    let square = 0;
    for (let index = start; index < end; index++) square += samples[index] ** 2;
    return end > start ? Math.min(1, Math.sqrt(square / (end - start)) * 5) : 0;
  });
}

/** Bounded RMS envelope only: no raw microphone/playback PCM enters the store. */
export function voicePcmEnvelope(data: string): number[] { return sampleEnvelope(pcmSamples(data)); }

export class VoiceCallController implements VoiceCallControllerLike {
  private store = writable<VoiceCallState>({ ...initialVoiceCallState });
  subscribe = this.store.subscribe;
  private state: VoiceCallState = { ...initialVoiceCallState };
  private socket: WebSocket | null = null;
  private audio: CallAudio | null = null;
  private audioGate: VoiceCallAudioGate | null = null;
  private privacyRequest: AbortController | null = null;
  private generation = 0;
  private ticker: ReturnType<typeof setInterval> | null = null;
  private startedAt = 0;
  private clockUpdatedAt = 0;
  private activeMillis = 0;
  private lifecycleStarted = false;
  private cues = new VoiceCallCuePlayer();
  private waveAnimation: number | null = null;
  private micLevels = { at: 0, levels: zeroLevels() };
  private playbackLevels: Array<{ at: number; until: number; levels: number[] }> = [];
  private transcriptWrites = new Map<string, Promise<void>>();
  private responseEmbeds = new Map<string, Map<string, VoiceArtifactReference>>();
  private contextPause: string | null = null;
  private pausedInputs: Array<Record<string, unknown>> = [];
  private pausedInputBytes = 0;
  private pendingTyped = new Map<string, {
    callId: string; chatId: string; resolve: (accepted: boolean) => void;
    timer: ReturnType<typeof setTimeout>;
  }>();

  constructor() {
    if (typeof window === 'undefined') return;
    window.addEventListener('beforeunload', () => this.hangup());
    let wasAuthenticated = get(authStore).isAuthenticated;
    authStore.subscribe((auth) => {
      if (wasAuthenticated && !auth.isAuthenticated) this.hangup();
      wasAuthenticated = auth.isAuthenticated;
    });
  }

  private update(patch: Partial<VoiceCallState>): void {
    this.state = { ...this.state, ...patch };
    this.store.set(this.state);
  }

  private refreshClock(): void {
    if (this.state.status !== 'live') return;
    const now = performance.now();
    const activity = this.state.billingActivity;
    if (activity === null || activity.inputListening || activity.processing) this.activeMillis += Math.max(0, now - this.clockUpdatedAt);
    this.clockUpdatedAt = now;
    this.update({ elapsedSeconds: Math.floor((now - this.startedAt) / 1000), activeElapsedSeconds: Math.floor(this.activeMillis / 1000) });
  }

  private animateWaveform(): void {
    if (this.waveAnimation !== null || typeof requestAnimationFrame !== 'function') return;
    const frame = () => {
      this.waveAnimation = null;
      if (this.state.status !== 'connecting' && this.state.status !== 'live') return;
      const now = performance.now();
      const audioTime = this.audio?.playbackAudioTime ?? null;
      while (audioTime !== null && this.playbackLevels.length && this.playbackLevels[0].until <= audioTime) this.playbackLevels.shift();
      const playback = this.playbackLevels[0];
      const mic = !this.state.muted && now - this.micLevels.at < 150 ? this.micLevels.levels : zeroLevels();
      const levels = mic.map((level, bin) => Math.max(level,
        playback && audioTime !== null && playback.at <= audioTime ? playback.levels[bin] : 0));
      if (levels.some((level, index) => Math.abs(level - this.state.audioLevels[index]) > 0.005)) this.update({ audioLevels: levels });
      this.waveAnimation = requestAnimationFrame(frame);
    };
    this.waveAnimation = requestAnimationFrame(frame);
  }

  private schedulePlaybackEnvelope(data: string, schedule: CallAudioPlaybackSchedule): void {
    const samples = pcmSamples(data);
    const audioTime = this.audio?.playbackAudioTime ?? schedule.startTime;
    const frameSamples = Math.round(schedule.sampleRate * WAVE_FRAME_MS / 1000);
    // Keep only RMS envelopes within a bounded two-minute playback horizon.
    // AudioContext time stops during suspension; wall time must never expire them.
    for (let offset = 0; offset < samples.length; offset += frameSamples) {
      const at = schedule.startTime + offset / schedule.sampleRate;
      const end = Math.min(samples.length, offset + frameSamples);
      if (at > audioTime + 120 || this.playbackLevels.length >= 3000) break;
      this.playbackLevels.push({ at, until: schedule.startTime + end / schedule.sampleRate,
        levels: sampleEnvelope(samples.subarray(offset, end)) });
    }
    this.animateWaveform();
  }

  private recordLifecycle(type: 'started' | 'ended'): void {
    const { chatId, callId, activeElapsedSeconds } = this.state;
    if (!chatId || !callId) return;
    void recordCallLifecycle({ type, chatId, callId, activeElapsedSeconds, occurredAt: Math.floor(Date.now() / 1000) })
      .catch(() => console.warn('[VoiceCall] Call event could not be saved'));
  }

  private send(message: Record<string, unknown>): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    if (this.contextPause && (message.type === 'mic_audio' || message.type === 'text_input' || message.type === 'audio_stream_end')) {
      const bytes = JSON.stringify(message).length;
      if (this.pausedInputBytes + bytes > 2 * 1024 * 1024 || this.pausedInputs.length >= 512) {
        this.fail('transcript_limit');
        return false;
      }
      this.pausedInputs.push(message);
      this.pausedInputBytes += bytes;
      return true;
    }
    try { this.socket.send(JSON.stringify(message)); return true; }
    catch { return false; }
  }

  private async settleTyped(messageId: string, accepted: boolean): Promise<void> {
    const pending = this.pendingTyped.get(messageId);
    if (!pending) return;
    this.pendingTyped.delete(messageId);
    clearTimeout(pending.timer);
    if (!accepted) {
      try { await markTypedCallMessageFailed(pending.callId, pending.chatId, messageId); }
      catch { this.fail('transcript_save_failed'); }
    }
    pending.resolve(accepted);
  }

  async start(existingChatId?: string, onBound?: (chatId: string) => void): Promise<void> {
    if (this.state.status === 'connecting' || this.state.status === 'live') return;
    this.closeResources();
    this.cues.stop();
    this.cues.prepare();
    this.responseEmbeds.clear();
    const generation = ++this.generation;
    // Preparation can refuse incomplete/oversized context before opening a
    // socket. Keep its initiating chat bound so that error remains visible.
    this.update({ ...initialVoiceCallState, status: 'connecting', chatId: existingChatId ?? null });
    // The browser's audio activation must occur in the click handler. The mic is
    // captured but never transmitted until the server acknowledges readiness.
    const current = () => generation === this.generation;
    const gate = new VoiceCallAudioGate({
      onAudio: (data) => {
        if (current() && this.state.status === 'live' && !this.state.muted &&
            !this.send({ type: 'mic_audio', data })) this.fail('connection_lost');
      },
      onAudioEnd: () => {
        if (current() && this.state.status === 'live' &&
            !this.send({ type: 'audio_stream_end' })) this.fail('connection_lost');
      },
      onState: (state) => { if (current()) this.update(state); },
      onError: () => { if (current()) this.fail('connection_failed'); },
    });
    this.audioGate = gate;
    const audio = new CallAudio(
      (data) => {
        if (!current()) return;
        this.micLevels = { at: performance.now(), levels: voicePcmEnvelope(data) };
        this.animateWaveform();
        gate.push(data);
      },
      (_userSpeaking, assistantSpeaking) => { if (current()) this.update({ assistantSpeaking }); },
    );
    // Capture immediately after permission; the gate buffers up to ten seconds
    // without sending PCM until the provider acknowledges readiness.
    audio.setMicEnabled(true);
    this.audio = audio;
    try {
      // Unlock output in the initiating gesture without requesting microphone
      // permission. Capture and provider connection require the saved profile ack.
      audio.unlock();
      const privacyRequest = new AbortController();
      this.privacyRequest = privacyRequest;
      const accepted = await ensureVoiceCallPrivacyAcknowledgement(privacyRequest.signal, () => {
        if (current()) { audio.unlock(); this.cues.prepare(); }
      });
      if (!current()) return;
      this.privacyRequest = null;
      if (!accepted) {
        this.cues.stop();
        this.closeResources();
        this.update({ ...initialVoiceCallState, chatId: existingChatId ?? null });
        return;
      }
      const capture = audio.start().catch((error: unknown) => { throw new VoiceCallStartError(microphoneError(error)); });
      const [prepared, projectContext] = await Promise.all([
        prepareVoiceCallChat(existingChatId).catch((error) => {
          throw new VoiceCallStartError(error instanceof VoiceCallContextError ? error.code : 'call_unavailable');
        }),
        loadVoiceProjectContext(existingChatId),
        capture,
      ]);
      if (generation !== this.generation) return;
      this.update({ chatId: prepared.chatId });
      onBound?.(prepared.chatId);
      await assistantSpeechController.stop();
      let token = getWebSocketToken();
      if (websocketTokenNeedsRefresh(token)) {
        if (!await checkAuth(undefined, true)) throw new VoiceCallStartError('session_expired');
        token = getWebSocketToken();
      }
      if (!token || websocketTokenNeedsRefresh(token)) throw new VoiceCallStartError('session_expired');
      if (generation !== this.generation) return;
      const url = new URL(`${getApiUrl().replace(/^http/, 'ws')}/v1/voice-call`);
      url.searchParams.set('sessionId', getSessionId());
      url.searchParams.set('token', token);
      const socket = new WebSocket(url);
      this.socket = socket;
      socket.onopen = () => {
        if (generation !== this.generation) return;
        this.send({ type: 'start', chat_id: prepared.chatId, startup_audio_allowance_ms: 10_000, context: { summary: prepared.summary, messages: prepared.history,
          active_focus: prepared.activeFocus, ...projectContext,
          app_settings_memories_metadata: [...new Set([...(prepared.memoryMetadata ?? []), ...(projectContext.app_settings_memories_metadata ?? [])])] } });
      };
      socket.onmessage = (event: MessageEvent<string>) => {
        if (generation !== this.generation) return;
        try { this.handleMessage(JSON.parse(event.data) as Record<string, unknown>); }
        catch { this.fail('invalid_response'); }
      };
      socket.onerror = () => { if (generation === this.generation) this.fail('connection_lost'); };
      socket.onclose = () => {
        if (generation !== this.generation) return;
        this.fail(this.state.status === 'connecting' ? 'connection_failed' : 'connection_lost');
      };
    } catch (error) {
      if (generation !== this.generation) return;
      const key = error instanceof VoiceCallStartError ? error.key : 'call_unavailable';
      this.fail(key);
    }
  }

  private handleMessage(message: Record<string, unknown>): void {
    switch (message.type) {
      case 'ready': {
        if (this.state.status !== 'connecting' || typeof message.call_id !== 'string') return;
        this.startedAt = performance.now();
        this.clockUpdatedAt = this.startedAt;
        this.activeMillis = 0;
        setActiveVoiceCallId(message.call_id);
        this.update({ status: 'live', callId: message.call_id, error: null,
          usage: NUMBER_FIELDS.reduce((usage, field) => ({ ...usage, [field]: Number(message[field]) || 0 }), {} as VoiceCallUsage) });
        this.lifecycleStarted = true;
        this.recordLifecycle('started');
        this.cues.play('connected');
        this.audioGate?.setLive(true);
        // Model loading and warmup run in the background after a normal start.
        this.audioGate?.start();
        if (this.state.status !== 'live') return;
        this.ticker = setInterval(() => this.refreshClock(), 250);
        return;
      }
      case 'audio_chunk':
        if (this.state.status === 'live' && typeof message.data === 'string') {
          const schedule = this.audio?.playPcm16(message.data, 24_000);
          if (schedule) this.schedulePlaybackEnvelope(message.data, schedule);
        }
        return;
      case 'audio.interrupted':
        this.playbackLevels.length = 0;
        this.audio?.interrupt();
        return;
      case 'transcript': {
        const callId = this.state.callId;
        const chatId = this.state.chatId;
        if (!callId || !chatId || (message.role !== 'user' && message.role !== 'assistant') ||
            typeof message.message_id !== 'string' || typeof message.text !== 'string') return;
        const messageId = message.message_id;
        // The matching final user echo is the provider acceptance signal. A later
        // ciphertext outbox failure must retain its encrypted row, not restore a
        // draft that could submit the same accepted text a second time.
        if (message.role === 'user' && message.final === true) void this.settleTyped(messageId, true);
        this.persistTranscript({
          callId, chatId, messageId, role: message.role as 'user' | 'assistant', text: message.text as string,
          final: message.final === true, interrupted: message.interrupted === true,
          userMessageId: typeof message.user_message_id === 'string' ? message.user_message_id : undefined,
          createdAt: typeof message.created_at === 'number' ? message.created_at : undefined,
        });
        return;
      }
      case 'voice_compression': {
        const callId = this.state.callId;
        const chatId = this.state.chatId;
        const generation = this.generation;
        if (!callId || !chatId || this.state.status !== 'live') return;
        void Promise.all([...this.transcriptWrites.values()]).then(() => applyVoiceCompression({ callId, chatId,
          isCurrent: () => generation === this.generation && this.state.status === 'live',
          send: (event) => this.send(event),
        }, message)).catch(() => { if (generation === this.generation) this.fail('transcript_save_failed'); });
        return;
      }
      case 'voice_context_pause':
        if (message.call_id !== this.state.callId || typeof message.checkpoint_id !== 'string' || this.state.status !== 'live') return;
        if (this.contextPause && this.contextPause !== message.checkpoint_id) { this.fail('invalid_response'); return; }
        this.contextPause = message.checkpoint_id;
        if (!this.send({ type: 'voice_context_paused', call_id: this.state.callId, checkpoint_id: this.contextPause })) this.fail('connection_lost');
        return;
      case 'voice_context_resumed':
        if (message.call_id !== this.state.callId || message.checkpoint_id !== this.contextPause || !this.contextPause) return;
        this.contextPause = null;
        for (const frame of this.pausedInputs.splice(0)) if (!this.send(frame)) { this.fail('connection_lost'); break; }
        this.pausedInputBytes = 0;
        return;
      case 'voice_memory':
      case 'voice_focus':
      case 'voice_embed':
      case 'voice_context':
      case 'voice_tool_status': {
        const callId = this.state.callId;
        const chatId = this.state.chatId;
        const generation = this.generation;
        if (!callId || !chatId || this.state.status !== 'live') return;
        const payload = message.payload as Record<string, unknown> | undefined;
        if (message.type === 'voice_embed' && message.call_id === callId &&
            typeof message.function_call_id === 'string' && typeof message.user_message_id === 'string' &&
            typeof message.assistant_message_id === 'string' && typeof payload?.embed_id === 'string' &&
            /^[A-Za-z0-9_-]{1,240}$/.test(payload.embed_id)) {
          const reference = voiceArtifactReferenceFromPayload(payload);
          if (reference) {
            const refs = this.responseEmbeds.get(message.assistant_message_id) ?? new Map<string, VoiceArtifactReference>();
            refs.set(reference.embed_id, reference);
            this.responseEmbeds.set(message.assistant_message_id, refs);
          }
        }
        void applyVoiceToolEvent({ callId, chatId,
          isCurrent: () => generation === this.generation && this.state.status === 'live',
          send: (event) => this.send(event),
        }, message).then((embedId) => {
          if (!embedId || typeof message.assistant_message_id !== 'string') return;
          const id = message.assistant_message_id;
          const previous = this.transcriptWrites.get(id) ?? Promise.resolve();
          const persisted = previous.catch(() => {}).then(() => upsertCallArtifact({
            callId, chatId, messageId: id, userMessageId: String(message.user_message_id), embedRefs: [embedId],
            embedReferences: [...(this.responseEmbeds.get(id)?.values() ?? [])],
            createdAt: typeof message.created_at === 'number' ? message.created_at : undefined,
          })).then(() => {});
          this.transcriptWrites.set(id, persisted);
          void persisted.catch(() => { if (generation === this.generation) this.fail('transcript_save_failed'); })
            .finally(() => { if (this.transcriptWrites.get(id) === persisted) this.transcriptWrites.delete(id); });
        }).catch(() => { if (generation === this.generation) this.fail('transcript_save_failed'); });
        return;
      }
      case 'text_input_rejected':
        if (typeof message.message_id === 'string') void this.settleTyped(message.message_id, false);
        return;
      case 'usage': {
        const usage = { ...(this.state.usage ?? {} as VoiceCallUsage) };
        for (const field of NUMBER_FIELDS) if (typeof message[field] === 'number') usage[field] = message[field] as number;
        this.update({ usage });
        return;
      }
      case 'billing_activity':
        if (this.state.status !== 'live' || message.call_id !== this.state.callId ||
            typeof message.input_listening !== 'boolean' || typeof message.processing !== 'boolean') return;
        this.refreshClock();
        this.update({ billingActivity: { inputListening: message.input_listening, processing: message.processing } });
        return;
      case 'ended': this.finish('ended', null); return;
      case 'error': this.fail(typeof message.code === 'string' ? message.code : 'call_unavailable'); return;
    }
  }

  private persistTranscript(event: CallTranscriptUpdate): void {
    const generation = this.generation;
    const embedReferences = [...(this.responseEmbeds.get(event.messageId)?.values() ?? [])];
    const embedRefs = embedReferences.map((reference) => reference.embed_id);
    const previous = this.transcriptWrites.get(event.messageId) ?? Promise.resolve();
    const next = previous.catch(() => {}).then(() => upsertCallTranscript({ ...event, embedRefs, embedReferences }));
    this.transcriptWrites.set(event.messageId, next);
    void next.catch(() => { if (generation === this.generation) this.fail('transcript_save_failed'); }).finally(() => {
      if (this.transcriptWrites.get(event.messageId) === next) this.transcriptWrites.delete(event.messageId);
    });
  }

  async submitText(chatId: string, text: string): Promise<boolean> {
    const callId = this.state.callId;
    if (this.state.status !== 'live' || this.state.chatId !== chatId || !callId ||
        !text.trim() || text.length > 8_000 || this.socket?.readyState !== WebSocket.OPEN) return false;
    const id = sortableMessageId();
    const createdAt = Math.floor(Date.now() / 1000);
    try { await persistTypedCallMessage(callId, chatId, id, text, createdAt); }
    catch { this.fail('transcript_save_failed'); return false; }
    if (this.state.status !== 'live' || this.state.callId !== callId || this.socket?.readyState !== WebSocket.OPEN) {
      await markTypedCallMessageFailed(callId, chatId, id);
      return false;
    }
    return new Promise<boolean>((resolve) => {
      const timer = setTimeout(() => {
        this.fail('connection_lost');
      }, 20_000);
      this.pendingTyped.set(id, { callId, chatId, resolve, timer });
      if (!this.send({ type: 'text_input', message_id: id, text, created_at: createdAt })) {
        this.fail('connection_lost');
      }
    });
  }

  setMuted(muted: boolean): void {
    if (this.state.status !== 'live' && this.state.status !== 'connecting') return;
    if (muted === this.state.muted) return;
    this.update({ muted, userSpeaking: muted ? false : this.state.userSpeaking });
    this.cues.play(muted ? 'muted' : 'unmuted');
    if (muted) this.micLevels = { at: 0, levels: zeroLevels() };
    this.audio?.setMicEnabled(!muted);
    // The gate clears pending capture and owns the single ordered end marker.
    this.audioGate?.setMuted(muted);
  }

  setMinimized(minimized: boolean): void { this.update({ minimized }); }

  hangup(): void {
    if (this.state.status === 'idle' || this.state.status === 'ended') return;
    this.send({ type: 'hangup' });
    this.finish('ended', null);
  }

  private fail(key: string): void { this.finish('error', key); }

  private finish(status: 'ended' | 'error', error: string | null): void {
    this.refreshClock();
    if (this.lifecycleStarted) {
      this.lifecycleStarted = false;
      this.recordLifecycle('ended');
      this.cues.play('ended');
    } else if (this.state.status === 'connecting') this.cues.stop();
    this.closeResources();
    this.update({ status, error, audioLevels: zeroLevels(), inputIdle: false, userSpeaking: false, assistantSpeaking: false,
      billingActivity: { inputListening: false, processing: false } });
  }

  private closeResources(): void {
    ++this.generation;
    this.privacyRequest?.abort();
    this.privacyRequest = null;
    if (this.waveAnimation !== null) cancelAnimationFrame(this.waveAnimation);
    this.waveAnimation = null;
    this.micLevels = { at: 0, levels: zeroLevels() };
    this.playbackLevels.length = 0;
    setActiveVoiceCallId(null);
    this.contextPause = null;
    this.pausedInputs.length = 0;
    this.pausedInputBytes = 0;
    for (const messageId of this.pendingTyped.keys()) void this.settleTyped(messageId, false);
    if (this.ticker) clearInterval(this.ticker);
    this.ticker = null;
    this.audioGate?.stop();
    this.audioGate = null;
    this.audio?.stop();
    this.audio = null;
    const socket = this.socket;
    this.socket = null;
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close();
  }
}

export const voiceCallController = new VoiceCallController();
