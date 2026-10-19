/** Background chat metadata, independent of the call's audio/socket lifetime. */
import type { ChatSynchronizationService } from './chatSyncService';
import type { CallTranscriptUpdate } from './voiceCallMessages';
import { loadCallContext } from './voiceCallMessages';
import { chatDB } from './db';
import { chatKeyManager } from './encryption/ChatKeyManager';
import { decryptWithChatKey, encryptWithChatKey } from './encryption/MessageEncryptor';
import { ensureChatKeySafeForWrite } from './chatKeyWriteGuard';
import { webSocketService } from './websocketService';
import { websocketStatus } from '../stores/websocketStatusStore';
import { getWorkspaceCacheIdentity } from './workspaceQueryCache';
import { getWorkspaceCacheEpoch } from './workspaceCacheLifecycle';
import { persistGeneratedChatMetadata } from './generatedChatMetadataPersistence';
import { chatMetadataCache } from './chatMetadataCache';

type Source = { message_id: string; role: 'user' | 'assistant'; revision: number };
type MetadataResult = { updated_chat_title?: string | null; chat_summary?: string | null; error?: string };
interface Completed {
  request_id: string; call_id: string; chat_id: string; source_messages: Source[];
  source_title_v: number; source_metadata_v: number; encrypted_chat_key: string; result: MetadataResult;
}
const REFRESH_MS = 60_000;
const schedulers = new Set<VoiceCallMetadataScheduler>();
const completions = new Map<string, (generated: boolean | Error) => void>();
const applying = new Set<string>();

function waitFor(type: string, requestId: string): { promise: Promise<Record<string, unknown>>; cancel(): void } {
  let cancel = () => {};
  const promise = new Promise<Record<string, unknown>>((resolve, reject) => {
    const onStored = (value: Record<string, unknown>) => {
      if (value.request_id !== requestId) return;
      cancel(); resolve(value);
    };
    const onError = (value: Record<string, unknown>) => {
      if (value.request_id !== requestId) return;
      cancel(); reject(Object.assign(new Error('Voice metadata unavailable'), {
        code: value.code === 'metadata_stale' ? 'metadata_stale' : 'metadata_unavailable',
      }));
    };
    const timer = setTimeout(() => { cancel(); reject(new Error('Voice metadata timed out')); }, 180_000);
    cancel = () => { clearTimeout(timer); webSocketService.off(type, onStored); webSocketService.off('voice_metadata_error', onError); };
    webSocketService.on(type, onStored);
    webSocketService.on('voice_metadata_error', onError);
  });
  void promise.catch(() => {});
  return { promise, cancel };
}

/** Installed with ordinary chat sync, so cold reconnect can recover ended calls. */
export function initializeVoiceCallMetadata(service: ChatSynchronizationService): void {
  webSocketService.on<Completed>('voice_metadata_completed', payload => {
    void applyVoiceCallMetadata(service, payload)
      .catch(error => {
        console.warn('[VoiceMetadata] Update retained for recovery');
        completions.get(payload.request_id)?.(error instanceof Error ? error : new Error('Metadata storage deferred'));
        completions.delete(payload.request_id);
      });
  });
  service.addEventListener('cachePrimed', () => {
    void webSocketService.sendMessage('voice_metadata_pending', {}).catch(() => {});
  });
  let connected = false;
  websocketStatus.subscribe(({ status }) => {
    if (status === 'connected' && !connected) {
      void webSocketService.sendMessage('voice_metadata_pending', {}).catch(() => {});
      for (const scheduler of schedulers) scheduler.retry();
    }
    connected = status === 'connected';
  });
}

export async function applyVoiceCallMetadata(service: ChatSynchronizationService, payload: Completed): Promise<void> {
  if (!payload?.request_id || !payload.chat_id || !Array.isArray(payload.source_messages) ||
      !payload.result || applying.has(payload.request_id)) return;
  applying.add(payload.request_id);
  const owner = getWorkspaceCacheIdentity(), epoch = getWorkspaceCacheEpoch();
  const current = () => owner === getWorkspaceCacheIdentity() && epoch === getWorkspaceCacheEpoch();
  try {
    const chat = await chatDB.getChat(payload.chat_id);
    const key = await chatKeyManager.getKey(payload.chat_id);
    if (!chat || !key || !current() || chat.encrypted_chat_key !== payload.encrypted_chat_key ||
        !await ensureChatKeySafeForWrite(payload.chat_id, key, 'voice metadata')) return;
    let sourcesCurrent = true;
    for (const source of payload.source_messages) {
      const row = await chatDB.getMessage(source.message_id);
      if (row && (row.queue_revision ?? 1) !== source.revision) sourcesCurrent = false;
    }
    const encrypted: Record<string, string> = {};
    if (sourcesCurrent && Math.max(chat.metadata_v ?? 0, chat.title_v ?? 0) === payload.source_metadata_v) {
      if (typeof payload.result.chat_summary === 'string' && payload.result.chat_summary.trim() && payload.result.chat_summary.length <= 1000) {
        encrypted.encrypted_chat_summary = await encryptWithChatKey(payload.result.chat_summary, key);
      }
      if ((chat.title_v ?? 0) === payload.source_title_v && typeof payload.result.updated_chat_title === 'string' &&
          payload.result.updated_chat_title.trim() && payload.result.updated_chat_title.length <= 200) {
        encrypted.encrypted_title = await encryptWithChatKey(payload.result.updated_chat_title, key);
      }
    }
    if (!current()) return;
    const stored = waitFor('voice_metadata_stored', payload.request_id);
    let receipt: Record<string, unknown>;
    try {
      await webSocketService.sendMessage('voice_metadata_commit', { request_id: payload.request_id, encrypted_metadata: encrypted });
      receipt = await stored.promise;
    } finally { stored.cancel(); }
    if (!current()) return;
    const fields = receipt.encrypted_metadata as Record<string, string>;
    const versions = receipt.versions as { metadata_v: number; title_v: number };
    const baseline = await chatDB.getChat(payload.chat_id);
    if (baseline && fields && Object.keys(fields).length && Number.isSafeInteger(versions?.metadata_v) && Number.isSafeInteger(versions?.title_v)) {
      const saved = await persistGeneratedChatMetadata(chatDB, baseline, { ...fields, ...versions }, current);
      if (saved && current()) {
        chatMetadataCache.invalidateChat(payload.chat_id);
        service.dispatchEvent(new CustomEvent('chatUpdated', { detail: {
          chat_id: payload.chat_id, chat: saved, type: 'post_processing_metadata',
        } }));
      }
    }
    completions.get(payload.request_id)?.(Boolean(payload.result.chat_summary || payload.result.updated_chat_title));
    completions.delete(payload.request_id);
  } finally { applying.delete(payload.request_id); }
}

export class VoiceCallMetadataScheduler {
  private sources = new Map<string, Source>();
  private included = '';
  private lastUpdate = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private inFlight = false;
  private ended = false;
  private finalRetries = 0;
  private staleRetries = 0;
  private owner = getWorkspaceCacheIdentity();
  private epoch = getWorkspaceCacheEpoch();

  constructor(private chatId: string, private callId: string) { schedulers.add(this); }
  private current(): boolean { return this.owner === getWorkspaceCacheIdentity() && this.epoch === getWorkspaceCacheEpoch(); }
  private signature(): string { return JSON.stringify([...this.sources.values()]); }

  async observe(event: CallTranscriptUpdate): Promise<void> {
    if (!event.final || !event.text.trim() || !this.current()) return;
    const row = await chatDB.getMessage(event.messageId);
    if (!row || !this.current()) return;
    if (this.sources.get(event.messageId)?.revision !== (row.queue_revision ?? 1)) this.staleRetries = 0;
    this.sources.set(event.messageId, { message_id: event.messageId, role: event.role, revision: row.queue_revision ?? 1 });
    while (this.sources.size > 64) this.sources.delete(this.sources.keys().next().value!);
    this.schedule();
  }

  finish(): void { this.ended = true; this.schedule(); }
  retry(): void { this.schedule(); }
  private schedule(): void {
    if (this.timer) { clearTimeout(this.timer); this.timer = null; }
    if (!this.current()) { schedulers.delete(this); return; }
    if (this.inFlight) return;
    const source = [...this.sources.values()];
    if (!source.some(row => row.role === 'user') || (!this.ended && !source.some(row => row.role === 'assistant'))) {
      if (this.ended) schedulers.delete(this);
      return;
    }
    if (this.signature() === this.included) { if (this.ended) schedulers.delete(this); return; }
    // Give late final ASR a short settling window. End-of-call flush bypasses
    // the periodic throttle but never generates an already included snapshot.
    const delay = this.ended ? 0 : Math.max(750, this.lastUpdate + REFRESH_MS - Date.now());
    this.timer = setTimeout(() => { this.timer = null; void this.flush(); }, delay);
  }

  private async flush(): Promise<void> {
    if (this.inFlight || !this.current()) return;
    this.inFlight = true;
    const signature = this.signature();
    const sources = [...this.sources.values()];
    let requestId = '';
    let completionTimer: ReturnType<typeof setTimeout> | null = null;
    let succeeded = false;
    let retryDelay = REFRESH_MS;
    try {
      const context = await loadCallContext(this.chatId);
      // A compression checkpoint can already cover the entire latest exchange.
      // Retain that exchange explicitly so metadata can still identify this
      // call's substantive topic, independently of the call context boundary.
      const history = [...context.history];
      for (const role of ['user', 'assistant'] as const) {
        const source = sources.filter(row => row.role === role).at(-1);
        if (!source || history.some(row => row.message_id === source.message_id)) continue;
        const row = await chatDB.getMessage(source.message_id);
        if (row?.status === 'synced' && (row.queue_revision ?? 1) === source.revision && row.content?.trim()) {
          history.push({ role, text: row.content, message_id: source.message_id, created_at: row.created_at });
        }
      }
      history.sort((a, b) => (a.created_at ?? 0) - (b.created_at ?? 0));
      while (history.length > 30) history.shift();
      const contextIds = new Set(history.map(row => row.message_id));
      const currentSources = sources.filter(row => contextIds.has(row.message_id));
      if (!currentSources.some(row => row.role === 'user')) return;
      const chat = await chatDB.getChat(this.chatId);
      const key = await chatKeyManager.getKey(this.chatId);
      if (!chat || !key || !this.current()) return;
      const title = chat.encrypted_title ? await decryptWithChatKey(chat.encrypted_title, key) : '';
      const summary = chat.encrypted_chat_summary ? await decryptWithChatKey(chat.encrypted_chat_summary, key) : '';
      if (!this.current()) return;
      requestId = crypto.randomUUID();
      const done = new Promise<boolean>((resolve, reject) => {
        completions.set(requestId, outcome => outcome instanceof Error ? reject(outcome) : resolve(outcome));
        completionTimer = setTimeout(() => reject(new Error('Voice metadata completion timed out')), 180_000);
      });
      void done.catch(() => {});
      const accepted = waitFor('voice_metadata_accepted', requestId);
      try {
        await webSocketService.sendMessage('voice_metadata_request', {
          request_id: requestId, call_id: this.callId, chat_id: this.chatId, source_messages: currentSources,
          context: { summary: context.summary ?? '', messages: history.map(row => ({ role: row.role, content: row.text,
            call_turn: currentSources.some(source => source.message_id === row.message_id) })) },
          current_title: title ?? '', current_summary: summary ?? '',
          source_title_v: chat.title_v ?? 0, source_metadata_v: Math.max(chat.metadata_v ?? 0, chat.title_v ?? 0),
          encrypted_chat_key: chat.encrypted_chat_key, final: this.ended,
        });
        const response = await accepted.promise;
        if (typeof response.accepted_request_id === 'string' && response.accepted_request_id !== requestId) {
          const resolve = completions.get(requestId)!;
          completions.delete(requestId); requestId = response.accepted_request_id;
          completions.set(requestId, resolve);
        }
      } finally { accepted.cancel(); }
      const generated = await done;
      this.included = signature;
      this.lastUpdate = generated ? Date.now() : 0;
      succeeded = true;
    } catch (error) {
      // Optional metadata must never end a call or mark its transcript failed.
      console.warn('[VoiceMetadata] Request deferred', error instanceof Error ? error.name : 'unknown');
      if (error instanceof Error && 'code' in error && error.code === 'metadata_stale' && this.staleRetries++ < 2) {
        // The server sent its current encrypted baseline before this rejection.
        // Retry only unpaid admission, after normal metadata sync can finish.
        retryDelay = 750;
      }
      this.lastUpdate = retryDelay === 750 ? 0 : Date.now();
    } finally {
      if (completionTimer) clearTimeout(completionTimer);
      if (requestId) completions.delete(requestId);
      this.inFlight = false;
      if (this.ended && this.signature() !== this.included) {
        if (succeeded || retryDelay === 750 || this.finalRetries++ < 1) {
          // A successful older snapshot flushes new content immediately; an
          // outage gets one retry inside final transcript admission grace.
          this.timer = setTimeout(() => { this.timer = null; void this.flush(); }, succeeded ? 0 : retryDelay);
        } else schedulers.delete(this);
      } else this.schedule();
    }
  }
}
