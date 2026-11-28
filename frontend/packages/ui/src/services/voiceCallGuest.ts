/**
 * Web controller for voice calls by signed-out visitors. Same store shape as the
 * signed-in controller (VoiceCallControllerLike) so VoiceCallBar renders it.
 * Flow: privacy notice -> microphone -> guest WebSocket (/v1/voice-call/guest) ->
 * final transcripts become guest chat messages (anonymousChatStorage) -> the
 * reply is spoken through /v1/anonymous/speech. Camera and screen share are
 * unavailable. Credentials are never sent: only the anonymous id.
 */
import { get, writable, type Readable } from 'svelte/store';
import { text } from '../i18n/translations';
import { getApiUrl } from '../config/api';
import { notificationStore } from '../stores/notificationStore';
import { markAnonymousFreeUsageExhausted, refreshAnonymousFreeUsageStatus } from '../stores/serverStatusStore';
import { anonymousChatStorage, type AnonymousPendingSendResult } from './anonymousChatStorage';
import { CallAudio } from '../components/videocall/callAudio';
import { initialVoiceCallState, voicePcmEnvelope, type VoiceCallControllerLike, type VoiceCallState } from './voiceCall';
import { ensureGuestVoiceAck } from './voiceCallGuestConsent';
import { VoiceCallAudioGate } from './voiceCallAudioGate';
import {
  guestVoiceMicrophoneFrame, guestVoicePlan,
  type GuestVoiceEvent, type GuestVoiceFeedbackClip, type GuestVoiceSocketPlan,
} from './rustCore/voice/guestVoiceClient';

const READY_TIMEOUT_MS = 10_000;
const PING_INTERVAL_MS = 15_000;

/** Receives the pending user message / new chat of each call turn (ActiveChat registers it). */
export type GuestCallTurnSink = (pending: AnonymousPendingSendResult) => void | Promise<void>;
let turnSink: GuestCallTurnSink | null = null;
export function setGuestCallTurnSink(sink: GuestCallTurnSink | null): void { turnSink = sink; }

export function isGuestVoiceCallSupported(): boolean {
  return typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia &&
    typeof AudioContext !== 'undefined' && typeof WebSocket !== 'undefined';
}

function microphoneError(error: unknown): string {
  const name = error instanceof Error ? error.name : '';
  if (name === 'NotAllowedError' || name === 'PermissionDeniedError' || name === 'SecurityError') return 'microphone_denied';
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') return 'microphone_missing';
  return 'microphone_failed';
}

function showExhaustedNotification(): void {
  notificationStore.addNotificationWithOptions('warning', {
    message: get(text)('chat.anonymous_free_usage.daily_credits_exhausted'),
    actionLabel: get(text)('signup.sign_up'),
    duration: 10000,
    dedupeKey: 'anonymous-daily-credits-exhausted',
    onAction: () => { window.dispatchEvent(new CustomEvent('openSignupInterface')); },
  });
}

class GuestVoiceCallController implements VoiceCallControllerLike {
  private store = writable<VoiceCallState>({ ...initialVoiceCallState });
  private state: VoiceCallState = { ...initialVoiceCallState };
  private generation = 0;
  private socket: WebSocket | null = null;
  private socketPlan: GuestVoiceSocketPlan | null = null;
  private audio: CallAudio | null = null;
  private audioGate: VoiceCallAudioGate | null = null;
  private audioFrames = Promise.resolve();
  private queuedAudioFrames = 0;
  private abort: AbortController | null = null;
  private timers: ReturnType<typeof setInterval>[] = [];
  private readyTimer: ReturnType<typeof setTimeout> | null = null;
  private player: HTMLAudioElement | null = null;
  private playerUrl: string | null = null;
  private playerDone: (() => void) | null = null;
  private feedbackClip: GuestVoiceFeedbackClip | null = null;
  private queue: string[] = [];
  private turnGeneration: number | null = null;
  private guestChatId: string | undefined;
  private onBound: ((chatId: string) => void) | undefined;
  private speaking = false;

  subscribe: Readable<VoiceCallState>['subscribe'] = (run, invalidate) => this.store.subscribe(run, invalidate);

  private update(patch: Partial<VoiceCallState>): void {
    this.state = { ...this.state, ...patch };
    this.store.set(this.state);
  }

  async start(chatId?: string, onBound?: (chatId: string) => void, _draftReady?: Promise<boolean>): Promise<void> {
    if (this.state.status === 'connecting' || this.state.status === 'live') return;
    const generation = ++this.generation;
    const current = () => generation === this.generation;
    this.guestChatId = chatId;
    this.onBound = onBound;
    this.queue = [];
    this.update({ ...initialVoiceCallState, status: 'connecting', chatId: chatId ?? null });
    if (!isGuestVoiceCallSupported()) { this.fail('call_unavailable'); return; }
    const abort = new AbortController();
    this.abort = abort;
    const gate = new VoiceCallAudioGate({
      onAudio: (data) => this.queueAudioFrame(generation, () => guestVoiceMicrophoneFrame(data), true),
      onAudioEnd: (verifiedQuiet) => this.queueAudioFrame(generation,
        () => verifiedQuiet ? this.socketPlan?.quiet : this.socketPlan?.pause),
      onState: (state) => {
        if (current()) this.update(state);
      },
      onError: () => { if (current()) this.fail('connection_failed'); },
    });
    const audio = new CallAudio((data) => {
      if (!current()) return;
      this.update({ audioLevels: voicePcmEnvelope(data) });
      gate.push(data);
    }, () => {});
    this.audioGate = gate;
    this.audio = audio;
    // Unlock audio output inside the initiating gesture, before any await.
    audio.unlock();
    const accepted = await ensureGuestVoiceAck(abort.signal, () => audio.unlock());
    if (!current()) return;
    if (!accepted) {
      this.release();
      this.update({ ...initialVoiceCallState, chatId: chatId ?? null });
      return;
    }
    try { await audio.start(); }
    catch (error) {
      if (current()) this.fail(microphoneError(error));
      return;
    }
    if (!current()) return;
    try { await this.connect(generation); }
    catch (error) {
      if (current()) {
        console.warn('[guestVoiceCall] Could not open the guest call', error instanceof Error ? error.name : 'unknown');
        this.fail('connection_failed');
      }
    }
  }

  private async connect(generation: number): Promise<void> {
    const plan = await guestVoicePlan('connect', {
      base: getApiUrl(), anonymous_id: anonymousChatStorage.getAnonymousId(), instant_feedback: true,
    });
    if (generation !== this.generation) return;
    const socket = new WebSocket(plan.url);
    this.socket = socket;
    this.socketPlan = plan;
    const current = () => generation === this.generation && this.socket === socket;
    this.readyTimer = setTimeout(() => { if (current() && this.state.status === 'connecting') this.fail('connection_failed'); }, READY_TIMEOUT_MS);
    socket.onopen = () => {
      if (current()) socket.send(plan.start);
    };
    socket.onmessage = (event) => {
      if (!current()) return;
      void guestVoicePlan('receive', { frame: String(event.data) }).then(
        (message) => { if (current() && message) this.onMessage(message); },
        () => { if (current()) this.fail('invalid_message'); },
      );
    };
    socket.onerror = () => { if (current()) this.fail('connection_failed'); };
    socket.onclose = () => {
      if (!current()) return;
      if (this.state.status === 'live' || this.state.status === 'connecting') this.fail('connection_failed');
    };
  }

  private send(frame: string | undefined): void {
    if (frame && this.socket?.readyState === WebSocket.OPEN) this.socket.send(frame);
  }

  private queueAudioFrame(generation: number, frame: () => string | undefined | Promise<string>, microphone = false): void {
    if (this.queuedAudioFrames >= 300) {
      this.fail('connection_failed');
      return;
    }
    this.queuedAudioFrames += 1;
    this.audioFrames = this.audioFrames.then(async () => {
      if (generation !== this.generation) return;
      const payload = await frame();
      if (generation === this.generation && (!microphone || (!this.state.muted && !this.speaking))) this.send(payload);
    }).catch(() => { if (generation === this.generation) this.fail('connection_failed'); }).finally(() => {
      if (generation === this.generation) this.queuedAudioFrames -= 1;
    });
  }

  private onMessage(message: GuestVoiceEvent): void {
    switch (message.type) {
      case 'ready': this.onReady(); break;
      case 'transcript': this.onTranscript(message); break;
      case 'limit': this.exhausted(); break;
      case 'error': this.fail(message.code); break;
      case 'ended': this.finish(); break;
      case 'voice_feedback': this.playFeedback(message.clip); break;
      case 'voice_feedback_stop':
        if (this.feedbackClip?.id === message.clip.id) this.stopFeedback();
        break;
      case 'waiting':
        if (this.state.status !== 'live' || !!this.state.waiting === message.active) break;
        this.update({
          waiting: message.active,
          waitingLine: { kind: message.line, text: waitingLineText(message.line) },
          liveTranscript: null,
        });
        if (message.clip) this.playFeedback(message.clip);
        else if (message.clip === undefined) {
          void playWaitingLine(message.line, async (url) => this.playFeedback({ id: message.line, url }));
        }
        break;
    }
  }

  private onReady(): void {
    if (this.state.status !== 'connecting') return;
    if (this.readyTimer) clearTimeout(this.readyTimer);
    this.readyTimer = null;
    this.update({ status: 'live' });
    this.audioGate?.setLive(true);
    this.audioGate?.start();
    this.timers.push(setInterval(() => {
      this.update({
        elapsedSeconds: this.state.elapsedSeconds + 1,
        activeElapsedSeconds: this.state.activeElapsedSeconds +
          ((!this.state.muted && !this.state.inputIdle) || this.turnGeneration === this.generation ? 1 : 0),
      });
    }, 1000));
    this.timers.push(setInterval(() => this.send(this.socketPlan?.ping), PING_INTERVAL_MS));
  }

  private onTranscript({ messageId, text, submitted }: Extract<GuestVoiceEvent, { type: 'transcript' }>): void {
    this.update({ liveTranscript: { messageId, text, submitted } });
    if (!submitted) return;
    this.queue.push(text);
    void this.drain(this.generation);
  }

  /** One turn at a time; later finals wait in the queue. */
  private async drain(generation: number): Promise<void> {
    if (this.turnGeneration === generation) return;
    this.turnGeneration = generation;
    try {
      while (this.queue.length && generation === this.generation) {
        const transcript = this.queue.shift();
        if (transcript) await this.runTurn(generation, transcript);
      }
    } finally {
      if (this.turnGeneration === generation) this.turnGeneration = null;
    }
  }

  private async runTurn(generation: number, markdown: string): Promise<void> {
    const current = () => generation === this.generation;
    let result;
    try {
      result = await anonymousChatStorage.sendTextMessage({
        markdown,
        currentChatId: this.guestChatId,
        sourceDemoId: null,
        onPending: async (pending) => {
          if (!current()) return;
          if (this.guestChatId !== pending.chat.chat_id) {
            this.guestChatId = pending.chat.chat_id;
            this.update({ chatId: pending.chat.chat_id });
            this.onBound?.(pending.chat.chat_id);
          }
          await turnSink?.(pending);
        },
      });
    } catch { if (current()) this.fail('turn_failed'); return; }
    if (!current()) return;
    this.update({ liveTranscript: null });
    if (result.rejectionReason === 'anonymous_usage_limit') { this.exhausted(); return; }
    void refreshAnonymousFreeUsageStatus();
    const content = result.assistantMessage?.content;
    if (typeof content === 'string' && content.trim()) await this.speak(generation, content);
  }

  private async speak(generation: number, markdown: string): Promise<void> {
    const current = () => generation === this.generation;
    this.stopFeedback();
    this.speaking = true;
    this.audioGate?.setMuted(true);
    this.update({ assistantSpeaking: true, userSpeaking: false });
    try {
      const plan = await guestVoicePlan('speech', {
        base: getApiUrl(), anonymous_id: anonymousChatStorage.getAnonymousId(), markdown, language: navigator.language,
      });
      for (const body of plan.bodies) {
        if (!current()) return;
        const response = await fetch(plan.url, {
          method: 'POST', credentials: 'omit', headers: { 'Content-Type': 'application/json' },
          body, signal: this.abort?.signal,
        });
        if (!current()) return;
        if (response.status === 429) { this.exhausted(); return; }
        if (!response.ok) { this.fail('speech_failed'); return; }
        const blob = await response.blob();
        if (!current()) return;
        await this.play(blob);
      }
    } catch {
      if (!current()) return;
      this.fail('speech_failed');
    } finally {
      if (current()) {
        this.speaking = false;
        this.audioGate?.setMuted(this.state.muted);
        this.update({ assistantSpeaking: false });
      }
    }
  }

  private playFeedback(clip: GuestVoiceFeedbackClip): void {
    if (this.state.status !== 'live' || this.speaking) return;
    this.stopFeedback();
    this.feedbackClip = clip;
    this.update({ assistantSpeaking: true });
    void this.play(clip.url).catch(() => {}).finally(() => {
      if (this.feedbackClip !== clip) return;
      this.feedbackClip = null;
      this.update({ assistantSpeaking: false });
    });
  }

  private stopFeedback(): void {
    if (!this.feedbackClip) return;
    this.feedbackClip = null;
    this.player?.pause();
    this.playerDone?.();
    this.update({ assistantSpeaking: false });
  }

  private play(source: Blob | string): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const generated = typeof source !== 'string';
      const url = typeof source === 'string' ? source : URL.createObjectURL(source);
      const player = new Audio(url);
      this.player = player;
      this.playerUrl = url;
      const done = () => {
        player.onended = null; player.onerror = null;
        if (this.player === player) { this.player = null; this.playerDone = null; }
        if (generated) URL.revokeObjectURL(url);
        if (this.playerUrl === url) this.playerUrl = null;
      };
      this.playerDone = () => { done(); resolve(); };
      player.onended = () => { done(); resolve(); };
      player.onerror = () => { done(); reject(new Error('speech_failed')); };
      void Promise.resolve(player.play()).catch((error) => { done(); reject(error); });
    });
  }

  private exhausted(): void {
    markAnonymousFreeUsageExhausted();
    showExhaustedNotification();
    this.hangup();
  }

  private fail(code: string): void {
    this.generation++;
    this.release(true);
    this.update({ status: 'error', error: code, assistantSpeaking: false, userSpeaking: false, liveTranscript: null });
  }

  private finish(): void {
    this.generation++;
    this.release(false);
    this.update({ ...initialVoiceCallState, status: 'ended', chatId: this.state.chatId });
  }

  /** Stops playback, timers, socket and microphone tracks. */
  private release(hangupFrame = false): void {
    if (this.readyTimer) clearTimeout(this.readyTimer);
    this.readyTimer = null;
    for (const timer of this.timers) clearInterval(timer);
    this.timers = [];
    this.abort?.abort();
    this.abort = null;
    this.player?.pause();
    this.playerDone?.();
    this.feedbackClip = null;
    this.speaking = false;
    this.queue = [];
    const socket = this.socket;
    if (hangupFrame) this.send(this.socketPlan?.hangup);
    this.socket = null;
    this.socketPlan = null;
    if (socket) {
      socket.onmessage = null; socket.onclose = null; socket.onerror = null; socket.onopen = null;
      if (socket.readyState === 0 || socket.readyState === 1) socket.close();
    }
    this.audioGate?.stop();
    this.audioGate = null;
    this.audioFrames = Promise.resolve();
    this.queuedAudioFrames = 0;
    this.audio?.stop();
    this.audio = null;
  }

  hangup(): void {
    if (this.state.status === 'idle' || this.state.status === 'ended') return;
    const chatId = this.state.chatId;
    this.generation++;
    this.release(true);
    this.update({ ...initialVoiceCallState, status: 'ended', chatId });
  }

  submitText(): Promise<boolean> { return Promise.resolve(false); }
  setMuted(muted: boolean): void {
    if (muted === this.state.muted) return;
    this.update({ muted, userSpeaking: false });
    this.audioGate?.setMuted(muted || this.speaking);
  }
  setWaiting(): void {}
  setMinimized(minimized: boolean): void { this.update({ minimized }); }
  setCameraEnabled(): Promise<void> { return Promise.reject(new Error('guest_unavailable')); }
  setScreenShareEnabled(): Promise<void> { return Promise.reject(new Error('guest_unavailable')); }
  flipCamera(): Promise<void> { return Promise.reject(new Error('guest_unavailable')); }
  setMediaExpanded(): void {}
  showCamera(): void {}
  selectMedia(): void {}
}

export const guestVoiceCallController = new GuestVoiceCallController();
import { playWaitingLine, waitingLineText } from './voiceCallWaiting';
