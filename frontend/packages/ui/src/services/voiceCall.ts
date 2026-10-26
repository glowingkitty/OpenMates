/** A single browser-owned voice call, fixed to the chat selected at launch. */
import { get, writable, type Readable } from 'svelte/store';
import { text } from '../i18n/translations';
import { notificationStore } from '../stores/notificationStore';
import { getApiUrl } from '../config/api';
import { getWebSocketToken } from '../utils/cookies';
import { getSessionId } from '../utils/sessionId';
import { checkAuth } from '../stores/authSessionActions';
import { authStore } from '../stores/authStore';
import { websocketTokenNeedsRefresh } from './audioRealtimeTranscription';
import { assistantSpeechController } from './assistantSpeechController';
import { supportsAssistantSpeechStream } from './assistantSpeechStream';
import { prepareVoiceCallChat, VoiceCallContextError } from './voiceCallMessages';
import { reportVoiceCallTurnDelivery, sendVoiceCallTurn } from './voiceCallTurns';
import { setActiveVoiceCallId } from './voiceCallOwnership';
import { callArtifactReferencesInText, type VoiceArtifactReference } from './voiceCallArtifactReferences';
import { CallAudio } from '../components/videocall/callAudio';
import { VoiceCallAudioGate } from './voiceCallAudioGate';
import { recordCallLifecycle } from './voiceCallLifecycle';
import { VoiceCallCuePlayer } from './voiceCallCues';
import { ensureVoiceCallPrivacyAcknowledgement } from './voiceCallPrivacy';
import { VoiceCallCamera, type VoiceCallCameraFacing } from './voiceCallCamera';
import type { VoiceHeardBoundary } from '../types/chat';
import type { ChatSynchronizationService } from './chatSyncService';
import type { VoiceCallDisplayedMedia, createVoiceCallMediaResolver } from './voiceCallMedia';

export type VoiceCallStatus = 'idle' | 'connecting' | 'live' | 'ended' | 'error';
export interface VoiceCallUsage {
  elapsed_seconds: number;
  credits_accrued: number;
  credits_charged: number;
  audio_credits: number;
  stt_duration_seconds: number;
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
  cameraAvailable: boolean;
  cameraEnabled: boolean;
  cameraPending: boolean;
  cameraStream: MediaStream | null;
  cameraFacing: VoiceCallCameraFacing;
  cameraError: string | null;
  mediaExpanded: boolean;
  mediaItems: readonly VoiceCallDisplayedMedia[];
  mediaIndex: number;
  displayedMedia: VoiceCallDisplayedMedia | null;
  mateCategory?: string;
  mateName?: string;
  modelName?: string;
}
export interface VoiceCallControllerLike extends Readable<VoiceCallState> {
  start(chatId?: string, onBound?: (chatId: string) => void, draftReady?: Promise<boolean>): Promise<void>;
  submitText(chatId: string, text: string): Promise<boolean>;
  setMuted(muted: boolean): void;
  setMinimized(minimized: boolean): void;
  setCameraEnabled(enabled: boolean): Promise<void>;
  flipCamera(): Promise<void>;
  setMediaExpanded(expanded: boolean): void;
  showCamera(): void;
  selectMedia(index: number): void;
  hangup(): void;
}

export const initialVoiceCallState: VoiceCallState = {
  status: 'idle', chatId: null, callId: null, minimized: false, muted: false,
  elapsedSeconds: 0, activeElapsedSeconds: 0, audioLevels: Array(16).fill(0), inputIdle: false, userSpeaking: false, assistantSpeaking: false, usage: null, billingActivity: null, error: null,
  cameraAvailable: false, cameraEnabled: false, cameraPending: false, cameraStream: null,
  cameraFacing: 'environment', cameraError: null, mediaExpanded: false, mediaItems: [], mediaIndex: 0, displayedMedia: null,
};

const NUMBER_FIELDS: (keyof VoiceCallUsage)[] = [
  'elapsed_seconds', 'credits_accrued', 'credits_charged', 'audio_credits',
  'stt_duration_seconds',
];
const SPEECH_OUTPUT_TRANSPORT = 'mp3_turn_stream_v2';

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
  private turnWrites = new Map<string, Promise<boolean>>();
  private callTurnIds = new Set<string>();
  private sourceReferences = new Map<string, VoiceArtifactReference[]>();
  private speechCleanup: (() => void) | null = null;
  private chatCleanup: (() => void) | null = null;
  private assistantMessageId: string | null = null;
  private canonicalService: ChatSynchronizationService | null = null;
  private assistantTaskId: string | null = null;
  private pendingHeardBoundary: VoiceHeardBoundary | null = null;
  private turnAdmission: Promise<void> = Promise.resolve();
  private assistantMessagesByTask = new Map<string, string>();
  private assistantTasksByMessage = new Map<string, string>();
  private speechActivity = { chatId: null as string | null, messageId: null as string | null,
    text: '', speaking: false, language: 'en' };
  private camera: VoiceCallCamera | null = null;
  private cameraGeneration = 0;
  private cameraCollapse: ReturnType<typeof setTimeout> | null = null;
  private mediaResolver: ReturnType<typeof createVoiceCallMediaResolver> | null = null;
  private mediaListenerCleanup: (() => void) | null = null;
  private mediaLoad: Promise<void> | null = null;
  private mediaDirty = false;
  private mediaIds = new Set<string>();
  private presentedMediaIds = new Set<string>();
  private sourceFrames = new Map<string, Promise<void>>();
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
    if (patch.error) this.notifyError(patch.error);
    if (patch.cameraError) this.notifyError(patch.cameraError, true);
  }

  private notifyError(code: string, camera = false): void {
    // Only translate known public codes; never display arbitrary server payloads.
    const known = camera
      ? ['camera_denied', 'camera_missing', 'camera_failed', 'source_frame_failed', 'media_unavailable']
      : ['microphone_denied', 'microphone_missing', 'microphone_failed', 'session_expired',
        'connection_failed', 'connection_lost', 'invalid_response', 'transcript_save_failed', 'transcript_limit',
        'context_too_large', 'context_unavailable', 'insufficient_credits'];
    const key = known.includes(code) ? code : camera ? 'camera_failed' : 'call_unavailable';
    notificationStore.addNotificationWithOptions('error', {
      message: get(text)(key === 'insufficient_credits' ? 'settings.billing.insufficient_credits_error' : `voicecall.${key}`),
      duration: 7000,
      dedupeKey: `voice-call-${camera ? 'camera-' : ''}error-${key}`,
    });
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
      const levels = !this.state.muted && now - this.micLevels.at < 150 ? this.micLevels.levels : zeroLevels();
      if (levels.some((level, index) => Math.abs(level - this.state.audioLevels[index]) > 0.005)) this.update({ audioLevels: levels });
      this.waveAnimation = requestAnimationFrame(frame);
    };
    this.waveAnimation = requestAnimationFrame(frame);
  }

  private recordLifecycle(type: 'started' | 'ended'): void {
    const { chatId, callId, activeElapsedSeconds } = this.state;
    if (!chatId || !callId) return;
    void recordCallLifecycle({ type, chatId, callId, activeElapsedSeconds, occurredAt: Math.floor(Date.now() / 1000) })
      .catch(() => console.warn('[VoiceCall] Call event could not be saved'));
  }

  private send(message: Record<string, unknown>): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    try { this.socket.send(JSON.stringify(message)); return true; }
    catch { return false; }
  }

  private async settleTyped(messageId: string, accepted: boolean): Promise<void> {
    const pending = this.pendingTyped.get(messageId);
    if (!pending) return;
    this.pendingTyped.delete(messageId);
    clearTimeout(pending.timer);
    pending.resolve(accepted);
  }

  async start(existingChatId?: string, onBound?: (chatId: string) => void, draftReady?: Promise<boolean>): Promise<void> {
    // Observe rejection immediately, even while consent is pending or another
    // call owns startup. Registration must use the captured composer's saved ID.
    const savedDraft = draftReady?.catch(() => false);
    if (this.state.status === 'connecting' || this.state.status === 'live') return;
    this.closeResources();
    this.cues.stop();
    if (!supportsAssistantSpeechStream()) {
      this.update({ ...initialVoiceCallState, status: 'error', chatId: existingChatId ?? null, error: 'call_unavailable' });
      return;
    }
    this.cues.prepare();
    this.turnWrites.clear();
    this.turnAdmission = Promise.resolve();
    this.callTurnIds.clear();
    this.sourceReferences.clear();
    const generation = ++this.generation;
    // Preparation can refuse incomplete/oversized context before opening a
    // socket. Keep its initiating chat bound for diagnostics and handset retry.
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
      () => {}, // Shared assistant speech is the sole playback owner. Capture never changes it.
    );
    // Capture immediately after permission; the gate buffers up to ten seconds
    // without sending PCM until the provider acknowledges readiness.
    audio.setMicEnabled(true);
    this.audio = audio;
    try {
      // Unlock output in the initiating gesture without requesting microphone
      // permission. Capture and provider connection require the saved profile ack.
      audio.unlock();
      assistantSpeechController.primeForAutoplay();
      const privacyRequest = new AbortController();
      this.privacyRequest = privacyRequest;
      const accepted = await ensureVoiceCallPrivacyAcknowledgement(privacyRequest.signal, () => {
        if (current()) {
          audio.unlock();
          assistantSpeechController.primeForAutoplay();
          this.cues.prepare();
        }
      });
      if (!current()) return;
      this.privacyRequest = null;
      if (!accepted) {
        this.cues.stop();
        this.closeResources();
        this.update({ ...initialVoiceCallState, chatId: existingChatId ?? null });
        return;
      }
      if (savedDraft && !await savedDraft) throw new VoiceCallStartError('call_unavailable');
      if (!current()) return;
      const capture = audio.start().catch((error: unknown) => { throw new VoiceCallStartError(microphoneError(error)); });
      const [prepared] = await Promise.all([
        prepareVoiceCallChat(existingChatId, true).catch((error) => {
          throw new VoiceCallStartError(error instanceof VoiceCallContextError ? error.code : 'call_unavailable');
        }),
        capture,
      ]);
      if (generation !== this.generation) return;
      this.update({ chatId: prepared.chatId, mateCategory: prepared.mateCategory });
      onBound?.(prepared.chatId);
      await assistantSpeechController.stop();
      assistantSpeechController.setCallOwner(prepared.chatId);
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
        this.send({ type: 'start', chat_id: prepared.chatId, startup_audio_allowance_ms: 10_000,
          speech_output_transport: SPEECH_OUTPUT_TRANSPORT });
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
        if (message.speech_output_transport !== SPEECH_OUTPUT_TRANSPORT) { this.fail('call_unavailable'); return; }
        this.startedAt = performance.now();
        this.clockUpdatedAt = this.startedAt;
        this.activeMillis = 0;
        setActiveVoiceCallId(message.call_id);
        this.update({ status: 'live', callId: message.call_id, error: null,
          cameraAvailable: message.camera_available === true,

          mateCategory: typeof message.mate_category === 'string' ? message.mate_category : this.state.mateCategory,
          mateName: typeof message.mate_name === 'string' ? message.mate_name : undefined,
          usage: NUMBER_FIELDS.reduce((usage, field) => ({ ...usage, [field]: Number(message[field]) || 0 }), {} as VoiceCallUsage) });
        if (this.state.chatId) assistantSpeechController.setCallOwner(this.state.chatId, message.call_id);
        this.bindCanonicalChat();
        this.lifecycleStarted = true;
        this.recordLifecycle('started');
        this.cues.play('connected');
        this.audioGate?.setLive(true);
        // Model loading and warmup run in the background after a normal start.
        this.audioGate?.start();
        if (get(this.store).status !== 'live') return;
        this.ticker = setInterval(() => this.refreshClock(), 250);
        return;
      }
      case 'voice_source_frame': {
        const { callId, chatId } = this.state;
        const generation = this.generation;
        if (this.state.status !== 'live' || !callId || !chatId || message.call_id !== callId ||
            typeof message.user_message_id !== 'string' || typeof message.frame_id !== 'string' ||
            typeof message.data !== 'string' || message.data.length > 350_000 ||
            typeof message.captured_at !== 'number' || typeof message.created_at !== 'number') return;
        const id = message.frame_id;
        // One sampled frame may ground several turns before the next 1Hz
        // observation. Each issued user message needs its own attachment/ack.
        const sourceKey = `${message.user_message_id}:${id}`;
        const previous = this.sourceFrames.get(sourceKey);
        if (previous) return;
        if (this.sourceFrames.size >= 8) {
          this.send({ type: 'source_frame_failed', call_id: callId, user_message_id: message.user_message_id, frame_id: id });
          this.update({ cameraError: 'source_frame_failed' });
          return;
        }
        const pending = import('./voiceCallVisuals').then(({ persistCallSourceFrame }) => persistCallSourceFrame({
          callId, chatId, messageId: message.user_message_id as string, frameId: id,
          data: message.data as string, capturedAt: message.captured_at as number, createdAt: message.created_at as number,
          source: message.source === 'screen' ? 'screen' : 'camera',
        })).then(reference => {
          if (generation === this.generation && this.state.callId === callId && this.state.status === 'live') {
            const refs = this.sourceReferences.get(message.user_message_id as string) ?? [];
            refs.push(reference);
            this.sourceReferences.set(message.user_message_id as string, refs);
            this.send({ type: 'source_frame_saved', call_id: callId, user_message_id: message.user_message_id,
              frame_id: id, embed_reference: reference });
          }
        }).catch(() => {
          if (generation !== this.generation || this.state.callId !== callId) return;
          this.update({ cameraError: 'source_frame_failed' });
          this.send({ type: 'source_frame_failed', call_id: callId, user_message_id: message.user_message_id, frame_id: id });
          throw new Error('Call source could not be saved');
        }).finally(() => { if (this.sourceFrames.get(sourceKey) === pending) this.sourceFrames.delete(sourceKey); });
        this.sourceFrames.set(sourceKey, pending);
        void pending.catch(() => {});
        return;
      }
      case 'camera_error':
        if (message.call_id !== this.state.callId || this.state.status !== 'live') return;
        this.update({ cameraError: 'camera_failed' });
        if (message.enabled === false) void this.setCameraEnabled(false);
        return;
      case 'audio.interrupted': {
        if (this.state.status !== 'live' || message.call_id !== this.state.callId) return;
        const chatId = this.state.chatId;
        const taskId = chatId ? this.canonicalService?.activeAITasks.get(chatId)?.taskId : undefined;
        const sameMessage = typeof message.assistant_message_id === 'string' &&
          message.assistant_message_id === this.assistantMessageId;
        const sameTask = typeof message.assistant_task_id === 'string' &&
          message.assistant_task_id === taskId && message.assistant_task_id === this.assistantTaskId;
        if (!sameMessage && !sameTask) return;
        const boundary = assistantSpeechController.playbackBoundary;
        if (boundary && boundary.assistant_message_id === this.assistantMessageId) this.pendingHeardBoundary = boundary;
        void assistantSpeechController.stop();
        if (sameTask && taskId && chatId) void this.canonicalService?.sendCancelAiTask(taskId, chatId).catch(() => {});
        return;
      }
      case 'transcript': {
        const { callId, chatId } = this.state;
        if (this.state.status !== 'live' || !callId || !chatId || message.call_id !== callId ||
            message.role !== 'user' || message.final !== true || typeof message.message_id !== 'string' ||
            typeof message.text !== 'string' || !message.text.trim()) return;
        const id = message.message_id;
        if (this.turnWrites.has(id)) return;
        const generation = this.generation;
        reportVoiceCallTurnDelivery({ callId, chatId, turnId: id }, 'queued');
        this.callTurnIds.add(id);
        const frames = [...this.sourceFrames.entries()].filter(([key]) => key.startsWith(`${id}:`)).map(([, pending]) => pending);
        const pending = this.turnAdmission.catch(() => {}).then(() => Promise.all(frames)).then(async () => {
          if (generation !== this.generation || this.state.status !== 'live') return false;
          reportVoiceCallTurnDelivery({ callId, chatId, turnId: id }, 'started');
          const heardBoundary = this.pendingHeardBoundary;
          const accepted = await sendVoiceCallTurn({ callId, chatId, turnId: id, text: message.text as string,
            createdAt: typeof message.created_at === 'number' ? message.created_at : undefined,
            embedReferences: this.sourceReferences.get(id),
            ...(heardBoundary ? { heardBoundary } : {}),
            isCurrent: () => generation === this.generation && this.state.status === 'live' });
          if (accepted && generation === this.generation && this.pendingHeardBoundary === heardBoundary) this.pendingHeardBoundary = null;
          return accepted;
        }).then(accepted => {
          void this.settleTyped(id, accepted);
          if (!accepted && generation === this.generation) this.fail('transcript_save_failed');
          return accepted;
        }).catch(() => {
          void this.settleTyped(id, false);
          if (generation === this.generation) this.fail('transcript_save_failed');
          return false;
        }).finally(() => { this.sourceReferences.delete(id); });
        this.turnWrites.set(id, pending);
        this.turnAdmission = pending.then(() => {});
        // Completed IDs remain for the call lifetime: a late final must never
        // invoke the canonical inference pipeline twice.
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

  /** Bind interruption decisions to the exact canonical task, including the
   * interval before preprocessing has issued an assistant message identity. */
  private publishAssistantState(): void {
    const chatId = this.state.chatId;
    if (this.state.status !== 'live' || !chatId) return;
    const task = this.canonicalService?.activeAITasks.get(chatId);
    const activeTask = task && this.callTurnIds.has(task.userMessageId) ? task : null;
    const speech = this.speechActivity;
    const speaking = speech.chatId === chatId && speech.speaking;
    const messageId = speaking ? speech.messageId
      : activeTask ? this.assistantMessagesByTask.get(activeTask.taskId) ?? null
        : speech.chatId === chatId ? speech.messageId : null;
    const taskId = speaking && messageId ? this.assistantTasksByMessage.get(messageId) ?? null
      : activeTask?.taskId ?? null;
    this.assistantMessageId = messageId;
    this.assistantTaskId = taskId;
    this.update({ assistantSpeaking: speaking });
    this.send({ type: 'assistant_state', speaking, generating: !!activeTask,
      assistant_message_id: messageId, assistant_task_id: taskId,
      text: speech.chatId === chatId && speech.messageId === messageId ? speech.text.slice(-8_000) : '',
      language: speech.language });
  }

  private bindCanonicalChat(): void {
    const generation = this.generation;
    this.speechCleanup = assistantSpeechController.activity.subscribe(activity => {
      if (generation !== this.generation || this.state.status !== 'live' || activity.chatId !== this.state.chatId) return;
      this.speechActivity = activity;
      this.publishAssistantState();
    });
    void import('./chatSyncService').then(({ chatSyncService }) => {
      if (generation !== this.generation) return;
      this.canonicalService = chatSyncService;
      const changed = (event: Event) => {
        const detail = (event as CustomEvent).detail;
        const message = detail?.newMessage;
        if (message?.chat_id !== this.state.chatId || message.role !== 'assistant' ||
            !this.callTurnIds.has(message.user_message_id) || typeof message.content !== 'string') return;
        this.update({ modelName: message.model_name, mateCategory: message.category, mateName: message.sender_name });
        for (const ref of callArtifactReferencesInText(message.content)) this.mediaIds.add(ref.embed_id);
        void this.refreshCallMedia();
      };
      const taskChanged = (event: Event) => {
        const detail = (event as CustomEvent).detail;
        if ((detail?.chat_id ?? detail?.chatId) !== this.state.chatId) return;
        if (event.type === 'aiTaskEnded') { this.publishAssistantState(); return; }
        if (!this.callTurnIds.has(detail?.user_message_id)) return;
        // A real canonical credit refusal must stop paid listening and notify
        // immediately, even when the bound chat is not currently visible.
        if (event.type === 'aiMessageChunk' && detail.is_final_chunk === true &&
            detail.rejection_reason === 'insufficient_credits') {
          this.fail('insufficient_credits');
          return;
        }
        const taskId = detail.task_id ?? detail.ai_task_id;
        if (typeof taskId === 'string' && typeof detail.message_id === 'string') {
          this.assistantMessagesByTask.set(taskId, detail.message_id);
          this.assistantTasksByMessage.set(detail.message_id, taskId);
        }
        this.publishAssistantState();
      };
      const taskEvents = ['aiTaskInitiated', 'aiTypingStarted', 'aiMessageChunk', 'aiTaskEnded'];
      chatSyncService.addEventListener('chatUpdated', changed);
      for (const name of taskEvents) chatSyncService.addEventListener(name, taskChanged);
      this.chatCleanup = () => {
        chatSyncService.removeEventListener('chatUpdated', changed);
        for (const name of taskEvents) chatSyncService.removeEventListener(name, taskChanged);
      };
      this.publishAssistantState();
    }).catch(() => {});
  }

  async submitText(chatId: string, text: string): Promise<boolean> {
    const callId = this.state.callId;
    if (this.state.status !== 'live' || this.state.chatId !== chatId || !callId ||
        !text.trim() || text.length > 8_000 || this.socket?.readyState !== WebSocket.OPEN) return false;
    const id = sortableMessageId();
    const createdAt = Math.floor(Date.now() / 1000);
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

  private clearCameraCollapse(): void {
    if (this.cameraCollapse !== null) clearTimeout(this.cameraCollapse);
    this.cameraCollapse = null;
  }

  async setCameraEnabled(enabled: boolean): Promise<void> {
    if (this.state.status !== 'live') return;
    if (!enabled) {
      ++this.cameraGeneration;
      this.camera?.stop();
      this.camera = null;
      this.clearCameraCollapse();
      this.update({ cameraEnabled: false, cameraPending: false, cameraStream: null });
      this.send({ type: 'camera_state', call_id: this.state.callId, enabled: false });
      return;
    }
    if (!this.state.cameraAvailable || this.state.cameraEnabled || this.state.cameraPending) return;
    const generation = this.generation;
    const cameraGeneration = ++this.cameraGeneration;
    this.camera?.stop();
    let firstStream = true;
    const current = () => generation === this.generation && cameraGeneration === this.cameraGeneration && this.state.status === 'live';
    const camera = new VoiceCallCamera({
      onFrame: frame => {
        // Compression may pause provider ingress. Drop transient frames instead of
        // queuing old images or delaying microphone/text recovery.
        if (!current() || !this.state.cameraEnabled) return;
        if (!this.send({ type: 'camera_frame', call_id: this.state.callId, frame_id: frame.frameId,
          data: frame.data, captured_at: frame.capturedAt })) {
          this.update({ cameraError: 'camera_failed' });
          void this.setCameraEnabled(false);
        }
      },
      onStream: (stream, facing) => {
        if (!current()) return;
        const wasEnabled = this.state.cameraEnabled;
        this.update({ cameraStream: stream, cameraFacing: facing, cameraEnabled: stream !== null });
        if (!stream) {
          if (wasEnabled) this.send({ type: 'camera_state', call_id: this.state.callId, enabled: false });
          return;
        }
        this.send({ type: 'camera_state', call_id: this.state.callId, enabled: true });
        if (!firstStream) { this.update({ cameraPending: false, cameraError: null }); return; }
        firstStream = false;
        this.update({ cameraPending: false, cameraError: null, mediaExpanded: true, displayedMedia: null });
        this.clearCameraCollapse();
        this.cameraCollapse = setTimeout(() => {
          this.cameraCollapse = null;
          if (current() && !this.state.displayedMedia) this.update({ mediaExpanded: false });
        }, 2000);
      },
      onError: error => {
        if (!current()) return;
        this.clearCameraCollapse();
        this.update({ cameraEnabled: false, cameraPending: false, cameraStream: null, cameraError: error });
        this.send({ type: 'camera_state', call_id: this.state.callId, enabled: false });
      },
    });
    this.camera = camera;
    this.update({ cameraPending: true, cameraError: null });
    await camera.start();
  }

  async flipCamera(): Promise<void> {
    const camera = this.camera;
    const generation = this.generation;
    if (this.state.status !== 'live' || !this.state.cameraEnabled || this.state.cameraPending || !camera) return;
    this.update({ cameraPending: true });
    try { await camera.flip(); }
    finally {
      if (generation === this.generation && this.camera === camera) this.update({ cameraPending: false });
    }
  }

  setMediaExpanded(expanded: boolean): void { this.clearCameraCollapse(); this.update({ mediaExpanded: expanded }); }
  showCamera(): void { this.clearCameraCollapse(); this.update({ displayedMedia: null, mediaExpanded: true }); }
  selectMedia(index: number): void {
    const media = this.state.mediaItems[index];
    if (!media || !Number.isSafeInteger(index)) return;
    this.clearCameraCollapse();
    this.update({ displayedMedia: media, mediaIndex: index, mediaExpanded: true });
  }

  private async refreshCallMedia(): Promise<void> {
    if (this.state.status !== 'live' || !this.mediaIds.size) return;
    if (this.mediaLoad) { this.mediaDirty = true; return this.mediaLoad; }
    const generation = this.generation;
    const current = () => generation === this.generation && this.state.status === 'live';
    const pending = (async () => {
      if (!this.mediaResolver) {
        const [{ createVoiceCallMediaResolver }, { chatSyncService }] = await Promise.all([
          import('./voiceCallMedia'), import('./chatSyncService'),
        ]);
        if (!current()) return;
        this.mediaResolver = createVoiceCallMediaResolver();
        const listener = () => { void this.refreshCallMedia(); };
        chatSyncService.addEventListener('embedUpdated', listener);
        this.mediaListenerCleanup = () => chatSyncService.removeEventListener('embedUpdated', listener);
      }
      do {
        this.mediaDirty = false;
        // Inspect newest call artifacts first; unrelated earlier skill cards
        // must not exhaust the resolver's bounded graph before a new visual.
        const items = await this.mediaResolver.resolve([...this.mediaIds].reverse());
        if (!current()) return;
        const fresh = items.find(item => !this.presentedMediaIds.has(item.embedId));
        for (const item of items) this.presentedMediaIds.add(item.embedId);
        if (fresh) {
          this.clearCameraCollapse();
          this.update({ mediaItems: items, displayedMedia: fresh, mediaIndex: items.indexOf(fresh), mediaExpanded: true });
        } else if (items.length) {
          this.update({ mediaItems: items, mediaIndex: Math.max(0, items.findIndex(item => item.embedId === this.state.displayedMedia?.embedId)) });
        }
      } while (this.mediaDirty && current());
    })().catch(() => { if (current()) this.update({ cameraError: 'media_unavailable' }); })
      .finally(() => { if (this.mediaLoad === pending) this.mediaLoad = null; });
    this.mediaLoad = pending;
    return pending;
  }

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
    ++this.cameraGeneration;
    this.camera?.stop();
    this.camera = null;
    this.clearCameraCollapse();
    this.mediaListenerCleanup?.();
    this.mediaListenerCleanup = null;
    this.mediaResolver?.destroy();
    this.mediaResolver = null;
    this.mediaLoad = null;
    this.mediaDirty = false;
    this.mediaIds.clear();
    this.presentedMediaIds.clear();
    this.sourceFrames.clear();
    this.update({ cameraEnabled: false, cameraPending: false, cameraStream: null, cameraAvailable: false,
      mediaExpanded: false, mediaItems: [], displayedMedia: null, mediaIndex: 0, cameraError: null });
    this.privacyRequest?.abort();
    this.privacyRequest = null;
    if (this.waveAnimation !== null) cancelAnimationFrame(this.waveAnimation);
    this.waveAnimation = null;
    this.micLevels = { at: 0, levels: zeroLevels() };
    this.speechCleanup?.();
    this.speechCleanup = null;
    this.chatCleanup?.();
    this.chatCleanup = null;
    this.assistantMessageId = null;
    this.assistantTaskId = null;
    this.pendingHeardBoundary = null;
    this.assistantMessagesByTask.clear();
    this.assistantTasksByMessage.clear();
    this.speechActivity = { chatId: null, messageId: null, text: '', speaking: false, language: 'en' };
    this.canonicalService = null;
    if (this.state.callId) void assistantSpeechController.stop();
    assistantSpeechController.setCallOwner(null);
    setActiveVoiceCallId(null);
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
