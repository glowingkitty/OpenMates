/**
 * Spoken "needs your tap" flow of a live web voice call.
 *
 * When a call turn pauses for an approval, the server sends static,
 * pre-recorded lines in the answering Mate's voice (no inference, no credits).
 * This plays the local "needs you" chime, then the request line; a reminder at
 * about 15 s; the thanks after the tap. A Memory request in a call cancels
 * itself after about 30 s: the timeout line plays, the request is answered
 * "without memories" through the ordinary reject path and a "memory request
 * timed out" system event is saved encrypted in the chat.
 *
 * Approval stays a manual tap. Nothing here approves anything; the only
 * automatic outcome is the safe one (continue without memories).
 * Spec: specifications/features/video-call/specification.yml (video-call.chat.permission-prompt).
 */
import { get, writable, type Readable } from 'svelte/store';
import { webSocketService } from './websocketService';
import { assistantSpeechController } from './assistantSpeechController';
import { voiceCallController } from './voiceCall';
import {
  MEMORY_REQUEST_TIMED_OUT_EVENT, memoryRequestTimedOutMessageId, type MemoryRequestTimedOutEvent,
} from './memoryRequestTimedOutEvent';

export type CallPermissionPromptKind = 'memory' | 'approval';
export interface CallPermissionPromptClips {
  request: string;
  reminder: string;
  thanks: string;
  timeout?: string;
}
export interface CallPermissionPromptPayload {
  chat_id: string;
  request_id: string;
  voice_call_id?: string | null;
  kind: CallPermissionPromptKind;
  clips: CallPermissionPromptClips;
}
/** Visible countdown of a Memory request in a call (absent outside calls). */
export interface CallPermissionCountdown {
  requestId: string;
  chatId: string;
  startedAt: number;
  deadlineAt: number;
}

export const CALL_PERMISSION_REMINDER_MS = 15_000;
export const CALL_MEMORY_REQUEST_TIMEOUT_MS = 30_000;
/** The chime is ~0.4 s; the spoken line follows right after it. */
const LINE_AFTER_CHIME_MS = 450;

interface ActivePrompt {
  payload: CallPermissionPromptPayload;
  timers: ReturnType<typeof setTimeout>[];
}

/** Injected so the flow can be tested without a real call or socket. */
export interface CallPermissionPromptDeps {
  isLiveCallFor(chatId: string, callId?: string | null): boolean;
  playCue(): void;
  playLine(chatId: string, promptId: string, url: string): void;
  /** Ordinary "continue without memories" (reject) path of the request. */
  continueWithoutMemories(requestId: string): Promise<void>;
  /** Encrypted presentation-only system event in the chat. */
  recordTimedOut(chatId: string, requestId: string): Promise<void>;
  now(): number;
}

export class CallPermissionPromptFlow {
  private active = new Map<string, ActivePrompt>();
  private readonly countdownStore = writable<CallPermissionCountdown | null>(null);
  readonly countdown: Readable<CallPermissionCountdown | null> = { subscribe: this.countdownStore.subscribe };

  constructor(private readonly deps: CallPermissionPromptDeps) {}

  /** A request now waits for the user's tap in a live call. */
  start(payload: CallPermissionPromptPayload): void {
    if (!payload?.request_id || !payload.chat_id || !payload.clips?.request) return;
    if (this.active.has(payload.request_id)) return;
    if (!this.deps.isLiveCallFor(payload.chat_id, payload.voice_call_id)) {
      console.info('[CallPermissionPrompt] Ignored: no live call for this chat', payload.kind);
      return;
    }
    console.info('[CallPermissionPrompt] Started', payload.kind);
    const { request_id: requestId, chat_id: chatId, clips } = payload;
    const prompt: ActivePrompt = { payload, timers: [] };
    this.active.set(requestId, prompt);
    this.deps.playCue();
    prompt.timers.push(setTimeout(() => this.line(prompt, 'request', clips.request), LINE_AFTER_CHIME_MS));
    prompt.timers.push(setTimeout(() => {
      this.deps.playCue();
      prompt.timers.push(setTimeout(() => this.line(prompt, 'reminder', clips.reminder), LINE_AFTER_CHIME_MS));
    }, CALL_PERMISSION_REMINDER_MS));
    if (payload.kind === 'memory') {
      const startedAt = this.deps.now();
      this.countdownStore.set({ requestId, chatId, startedAt, deadlineAt: startedAt + CALL_MEMORY_REQUEST_TIMEOUT_MS });
      prompt.timers.push(setTimeout(() => void this.timeOut(requestId), CALL_MEMORY_REQUEST_TIMEOUT_MS));
    }
  }

  /** The user tapped (allow or exclude): stop the countdown and confirm aloud. */
  answered(requestId: string): void {
    const prompt = this.active.get(requestId);
    if (!prompt) {
      console.info('[CallPermissionPrompt] Answered with no active prompt');
      return;
    }
    console.info('[CallPermissionPrompt] Answered');
    this.clear(requestId);
    if (this.deps.isLiveCallFor(prompt.payload.chat_id, prompt.payload.voice_call_id)) {
      this.deps.playLine(prompt.payload.chat_id, `${requestId}:thanks`, prompt.payload.clips.thanks);
    }
  }

  /** The request went away without a tap (server dismissed it, call ended). */
  dismiss(requestId: string): void { this.clear(requestId); }

  dismissAll(): void { for (const requestId of [...this.active.keys()]) this.clear(requestId); }

  isActive(requestId: string): boolean { return this.active.has(requestId); }

  private line(prompt: ActivePrompt, kind: string, url: string | undefined): void {
    if (!url || this.active.get(prompt.payload.request_id) !== prompt) return;
    if (!this.deps.isLiveCallFor(prompt.payload.chat_id, prompt.payload.voice_call_id)) {
      this.clear(prompt.payload.request_id);
      return;
    }
    this.deps.playLine(prompt.payload.chat_id, `${prompt.payload.request_id}:${kind}`, url);
  }

  private async timeOut(requestId: string): Promise<void> {
    const prompt = this.active.get(requestId);
    if (!prompt) return;
    const { chat_id: chatId, clips } = prompt.payload;
    const live = this.deps.isLiveCallFor(chatId, prompt.payload.voice_call_id);
    console.info('[CallPermissionPrompt] Timed out', live ? 'in a live call' : 'after the call');
    this.clear(requestId);
    if (!live) return;
    if (clips.timeout) this.deps.playLine(chatId, `${requestId}:timeout`, clips.timeout);
    await this.deps.continueWithoutMemories(requestId);
    await this.deps.recordTimedOut(chatId, requestId);
  }

  private clear(requestId: string): void {
    const prompt = this.active.get(requestId);
    if (!prompt) return;
    for (const timer of prompt.timers) clearTimeout(timer);
    this.active.delete(requestId);
    if (get(this.countdownStore)?.requestId === requestId) this.countdownStore.set(null);
  }
}

async function recordTimedOut(chatId: string, requestId: string): Promise<void> {
  const { storeSystemEvent } = await import('./contextEntryEvents');
  const createdAt = Math.floor(Date.now() / 1000);
  const event: MemoryRequestTimedOutEvent = {
    schema_version: 1, type: MEMORY_REQUEST_TIMED_OUT_EVENT, action: 'timed_out',
    request_id: requestId, created_at: createdAt,
  };
  await storeSystemEvent(chatId, memoryRequestTimedOutMessageId(requestId), JSON.stringify(event), createdAt);
}

async function continueWithoutMemories(requestId: string): Promise<void> {
  const [{ handlePermissionDialogExclude }, { chatSyncService }, { appSettingsMemoriesPermissionStore }] =
    await Promise.all([
      import('./chatSyncServiceHandlersAppSettings'),
      import('./chatSyncService'),
      import('../stores/appSettingsMemoriesPermissionStore'),
    ]);
  await handlePermissionDialogExclude(chatSyncService, requestId);
  if (appSettingsMemoriesPermissionStore.getCurrentRequestId() === requestId) {
    appSettingsMemoriesPermissionStore.clear();
  }
}

export const callPermissionPrompt = new CallPermissionPromptFlow({
  isLiveCallFor: (chatId, callId) => {
    const state = get(voiceCallController);
    return state.status === 'live' && state.chatId === chatId && (!callId || !state.callId || state.callId === callId);
  },
  playCue: () => voiceCallController.playCue('needs_you'),
  playLine: (chatId, promptId, url) => assistantSpeechController.playCallPrompt(chatId, promptId, url),
  continueWithoutMemories,
  recordTimedOut,
  now: () => Date.now(),
});

let installed = false;
/** Subscribe once; prompts of other chats or with no live call are ignored. */
export function installCallPermissionPrompt(): void {
  if (installed) return;
  installed = true;
  webSocketService.on<CallPermissionPromptPayload>('voice_call_permission_prompt', (payload) => {
    callPermissionPrompt.start(payload);
  });
  voiceCallController.subscribe((state) => {
    if (state.status !== 'live') callPermissionPrompt.dismissAll();
  });
  // A request the server withdrew (or another device answered) stops its
  // countdown and lines once its card was shown and is gone again.
  void Promise.all([
    import('../stores/appSettingsMemoriesPermissionStore'),
    import('../stores/connectedAccountPermissionStore'),
  ]).then(([memories, accounts]) => {
    const follow = (store: Readable<{ requestId?: string } | null | undefined>) => {
      let shown: string | null = null;
      store.subscribe((request) => {
        const requestId = request?.requestId ?? null;
        if (shown && shown !== requestId) callPermissionPrompt.dismiss(shown);
        shown = requestId;
      });
    };
    follow(memories.currentPermissionRequest);
    follow(accounts.currentConnectedAccountPermissionRequest);
  });
}
