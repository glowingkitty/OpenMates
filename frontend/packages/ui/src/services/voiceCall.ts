/** A single browser-owned voice call, fixed to the chat selected at launch. */
import { get, writable, type Readable } from 'svelte/store';
import { getApiUrl } from '../config/api';
import { getWebSocketToken } from '../utils/cookies';
import { getSessionId } from '../utils/sessionId';
import { checkAuth } from '../stores/authSessionActions';
import { authStore } from '../stores/authStore';
import { websocketTokenNeedsRefresh } from './audioRealtimeTranscription';
import { assistantSpeechController } from './assistantSpeechController';
import { markTypedCallMessageFailed, prepareVoiceCallChat, persistTypedCallMessage, upsertCallTranscript } from './voiceCallMessages';
import { CallAudio } from '../components/videocall/callAudio';

export type VoiceCallStatus = 'idle' | 'connecting' | 'live' | 'ended' | 'error';
export interface VoiceCallUsage {
  elapsed_seconds: number;
  credits_accrued: number;
  credits_charged: number;
  audio_credits: number;
  gemini_input_tokens: number;
  gemini_output_tokens: number;
  audio_credits_per_minute: number;
}
export interface VoiceCallState {
  status: VoiceCallStatus;
  chatId: string | null;
  callId: string | null;
  minimized: boolean;
  muted: boolean;
  elapsedSeconds: number;
  userSpeaking: boolean;
  assistantSpeaking: boolean;
  usage: VoiceCallUsage | null;
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
  elapsedSeconds: 0, userSpeaking: false, assistantSpeaking: false, usage: null, error: null,
};

const NUMBER_FIELDS: (keyof VoiceCallUsage)[] = [
  'elapsed_seconds', 'credits_accrued', 'credits_charged', 'audio_credits',
  'gemini_input_tokens', 'gemini_output_tokens', 'audio_credits_per_minute',
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

export class VoiceCallController implements VoiceCallControllerLike {
  private store = writable<VoiceCallState>({ ...initialVoiceCallState });
  subscribe = this.store.subscribe;
  private state: VoiceCallState = { ...initialVoiceCallState };
  private socket: WebSocket | null = null;
  private audio: CallAudio | null = null;
  private generation = 0;
  private ticker: ReturnType<typeof setInterval> | null = null;
  private startedAt = 0;
  private transcriptWrites = new Map<string, Promise<void>>();
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
    if (!accepted) {
      try { await markTypedCallMessageFailed(pending.callId, pending.chatId, messageId); }
      catch { this.fail('transcript_save_failed'); }
    }
    pending.resolve(accepted);
  }

  async start(existingChatId?: string, onBound?: (chatId: string) => void): Promise<void> {
    if (this.state.status === 'connecting' || this.state.status === 'live') return;
    this.closeResources();
    const generation = ++this.generation;
    this.update({ ...initialVoiceCallState, status: 'connecting' });
    // The browser's audio activation must occur in the click handler. The mic is
    // captured but never transmitted until the server acknowledges readiness.
    const audio = new CallAudio(
      (data) => { if (this.state.status === 'live' && !this.state.muted) this.send({ type: 'mic_audio', data }); },
      (userSpeaking, assistantSpeaking) => this.update({ userSpeaking, assistantSpeaking }),
    );
    audio.setMicEnabled(false);
    this.audio = audio;
    const capture = audio.start().catch((error: unknown) => { throw new VoiceCallStartError(microphoneError(error)); });
    try {
      const [prepared] = await Promise.all([
        prepareVoiceCallChat(existingChatId).catch(() => { throw new VoiceCallStartError('call_unavailable'); }),
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
        this.send({ type: 'start', chat_id: prepared.chatId, context: { summary: prepared.summary, messages: prepared.history } });
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
        this.update({ status: 'live', callId: message.call_id, error: null,
          usage: NUMBER_FIELDS.reduce((usage, field) => ({ ...usage, [field]: Number(message[field]) || 0 }), {} as VoiceCallUsage) });
        this.audio?.setMicEnabled(!this.state.muted);
        this.ticker = setInterval(() => this.update({ elapsedSeconds: Math.floor((performance.now() - this.startedAt) / 1000) }), 250);
        return;
      }
      case 'audio_chunk':
        if (this.state.status === 'live' && typeof message.data === 'string') this.audio?.playPcm16(message.data, 24_000);
        return;
      case 'audio.interrupted':
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
        const previous = this.transcriptWrites.get(messageId) ?? Promise.resolve();
        const next = previous.catch(() => {}).then(() => upsertCallTranscript({
          callId, chatId, messageId, role: message.role as 'user' | 'assistant', text: message.text as string,
          final: message.final === true, interrupted: message.interrupted === true,
          userMessageId: typeof message.user_message_id === 'string' ? message.user_message_id : undefined,
          createdAt: typeof message.created_at === 'number' ? message.created_at : undefined,
        }));
        this.transcriptWrites.set(messageId, next);
        void next.catch(() => {
          this.fail('transcript_save_failed');
        }).finally(() => {
          if (this.transcriptWrites.get(messageId) === next) this.transcriptWrites.delete(messageId);
        });
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
      case 'ended': this.finish('ended', null); return;
      case 'error': this.fail(typeof message.code === 'string' ? message.code : 'call_unavailable'); return;
    }
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
    this.update({ muted, userSpeaking: muted ? false : this.state.userSpeaking });
    this.audio?.setMicEnabled(!muted && this.state.status === 'live');
  }

  setMinimized(minimized: boolean): void { this.update({ minimized }); }

  hangup(): void {
    if (this.state.status === 'idle' || this.state.status === 'ended') return;
    this.send({ type: 'hangup' });
    this.finish('ended', null);
  }

  private fail(key: string): void { this.finish('error', key); }

  private finish(status: 'ended' | 'error', error: string | null): void {
    this.closeResources();
    this.update({ status, error, userSpeaking: false, assistantSpeaking: false });
  }

  private closeResources(): void {
    ++this.generation;
    for (const messageId of this.pendingTyped.keys()) void this.settleTyped(messageId, false);
    if (this.ticker) clearInterval(this.ticker);
    this.ticker = null;
    this.audio?.stop();
    this.audio = null;
    const socket = this.socket;
    this.socket = null;
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close();
  }
}

export const voiceCallController = new VoiceCallController();
