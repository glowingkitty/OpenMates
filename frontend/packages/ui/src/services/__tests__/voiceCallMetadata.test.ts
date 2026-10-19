import { beforeEach, describe, expect, it, vi } from 'vitest';

const m = vi.hoisted(() => {
  const handlers = new Map<string, Set<(value: Record<string, unknown>) => void>>();
  const emit = (type: string, data: Record<string, unknown>) => handlers.get(type)?.forEach(fn => fn(data));
  const chat = { chat_id: 'chat', encrypted_chat_key: 'wrapped-key', encrypted_title: null as string | null,
    encrypted_chat_summary: null as string | null, title_v: 0, metadata_v: 0 };
  const rows = new Map<string, { queue_revision: number; status?: string; content?: string; created_at?: number }>();
  const send = vi.fn(async (type: string, data: Record<string, unknown>) => {
    if (type === 'voice_metadata_request') {
      const acceptedId = crypto.randomUUID();
      queueMicrotask(() => {
        emit('voice_metadata_accepted', { request_id: data.request_id, accepted_request_id: acceptedId });
        emit('voice_metadata_completed', { ...data, request_id: acceptedId, result: { updated_chat_title: 'Ramen planning', chat_summary: 'Discussed ramen.' } });
      });
    }
    if (type === 'voice_metadata_commit') queueMicrotask(() => emit('voice_metadata_stored', {
      request_id: data.request_id, encrypted_metadata: data.encrypted_metadata,
      versions: { title_v: chat.title_v + 1, metadata_v: chat.metadata_v + 1 },
    }));
  });
  return { handlers, emit, chat, rows, send, epoch: 0,
    history: [{ role: 'user', text: 'How do I make ramen?', message_id: 'user' },
      { role: 'assistant', text: 'Use vegetable broth.', message_id: 'assistant' }],
    persist: vi.fn(async (_db, _baseline, patch) => Object.assign(chat, patch)),
    service: { addEventListener: vi.fn(), dispatchEvent: vi.fn() },
  };
});
vi.mock('../db', () => ({ chatDB: { getChat: vi.fn(async () => ({ ...m.chat })), getMessage: vi.fn(async id => m.rows.get(id)) } }));
vi.mock('../voiceCallMessages', () => ({ loadCallContext: vi.fn(async () => ({ summary: 'Earlier vegetarian preference.', history: m.history })) }));
vi.mock('../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKey: vi.fn(async () => new Uint8Array(32)) } }));
vi.mock('../encryption/MessageEncryptor', () => ({ encryptWithChatKey: vi.fn(async text => `cipher:${text}`),
  decryptWithChatKey: vi.fn(async text => text.slice(7)) }));
vi.mock('../chatKeyWriteGuard', () => ({ ensureChatKeySafeForWrite: vi.fn(async () => true) }));
vi.mock('../workspaceQueryCache', () => ({ getWorkspaceCacheIdentity: () => 'owner' }));
vi.mock('../workspaceCacheLifecycle', () => ({ getWorkspaceCacheEpoch: () => m.epoch }));
vi.mock('../generatedChatMetadataPersistence', () => ({ persistGeneratedChatMetadata: m.persist }));
vi.mock('../chatMetadataCache', () => ({ chatMetadataCache: { invalidateChat: vi.fn() } }));
vi.mock('../../stores/websocketStatusStore', () => ({ websocketStatus: { subscribe: vi.fn(() => () => {}) } }));
vi.mock('../websocketService', () => ({ webSocketService: {
  on: (type, fn) => { if (!m.handlers.has(type)) m.handlers.set(type, new Set()); m.handlers.get(type)!.add(fn); },
  off: (type, fn) => m.handlers.get(type)?.delete(fn), sendMessage: m.send,
} }));

import { VoiceCallMetadataScheduler, initializeVoiceCallMetadata, applyVoiceCallMetadata } from '../voiceCallMetadata';
import type { ChatSynchronizationService } from '../chatSyncService';
import type { CallTranscriptUpdate } from '../voiceCallMessages';
const service = m.service as unknown as ChatSynchronizationService;
function turn(role: 'user' | 'assistant', id = role): CallTranscriptUpdate {
  return { callId: 'call', chatId: 'chat', messageId: id, role, text: 'Ramen discussion', final: true };
}
const requests = () => m.send.mock.calls.filter(([type]) => type === 'voice_metadata_request');

describe('voice call metadata lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers(); vi.setSystemTime(100_000); vi.clearAllMocks(); m.epoch++;
    m.handlers.clear(); m.rows.clear(); m.rows.set('user', { queue_revision: 1 }); m.rows.set('assistant', { queue_revision: 1 });
    m.history.splice(0, m.history.length, { role: 'user', text: 'How do I make ramen?', message_id: 'user' },
      { role: 'assistant', text: 'Use vegetable broth.', message_id: 'assistant' });
    Object.assign(m.chat, { encrypted_title: null, encrypted_chat_summary: null, title_v: 0, metadata_v: 0 });
    initializeVoiceCallMetadata(service);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.metadata-generation,video-call.chat.metadata-lifecycle
  it('creates metadata after a persisted exchange, includes earlier context and stores only encrypted fields', async () => {
    const scheduler = new VoiceCallMetadataScheduler('chat', 'call');
    await scheduler.observe(turn('user'));
    await vi.advanceTimersByTimeAsync(1000);
    expect(requests()).toHaveLength(0);
    await scheduler.observe(turn('assistant'));
    await vi.advanceTimersByTimeAsync(750);
    expect(requests()).toHaveLength(1);
    expect(requests()[0][1]).toMatchObject({ context: { summary: 'Earlier vegetarian preference.' }, source_metadata_v: 0 });
    expect(m.persist).toHaveBeenCalledWith(expect.anything(), expect.anything(), {
      encrypted_title: 'cipher:Ramen planning', encrypted_chat_summary: 'cipher:Discussed ramen.', title_v: 1, metadata_v: 1,
    }, expect.any(Function));
    scheduler.finish(); await vi.advanceTimersByTimeAsync(0);
    expect(requests()).toHaveLength(1);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.metadata-generation,video-call.chat.metadata-lifecycle
  it('coalesces finalized revisions within a minute and flushes dirty content immediately on hangup', async () => {
    const scheduler = new VoiceCallMetadataScheduler('chat', 'call');
    await scheduler.observe(turn('user')); await scheduler.observe(turn('assistant'));
    await vi.advanceTimersByTimeAsync(750);
    m.rows.set('user', { queue_revision: 2 });
    await scheduler.observe(turn('user'));
    await vi.advanceTimersByTimeAsync(10_000);
    expect(requests()).toHaveLength(1);
    scheduler.finish(); await vi.advanceTimersByTimeAsync(0);
    expect(requests()).toHaveLength(2);
    expect(requests()[1][1]).toMatchObject({ final: true, source_title_v: 1, source_metadata_v: 1,
      source_messages: expect.arrayContaining([{ message_id: 'user', role: 'user', revision: 2 }]) });
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.metadata-generation,video-call.chat.metadata-lifecycle
  it('can finalize substantive user-only speech but does no work for an empty call', async () => {
    const empty = new VoiceCallMetadataScheduler('chat', 'empty'); empty.finish();
    const scheduler = new VoiceCallMetadataScheduler('chat', 'call');
    await scheduler.observe(turn('user')); scheduler.finish();
    await vi.advanceTimersByTimeAsync(0);
    expect(requests()).toHaveLength(1);
    expect(requests()[0][1]).toMatchObject({ final: true });
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.metadata-generation,video-call.chat.metadata-lifecycle
  it('rejects late metadata after an account change', async () => {
    const scheduler = new VoiceCallMetadataScheduler('chat', 'call');
    await scheduler.observe(turn('user')); await scheduler.observe(turn('assistant'));
    m.epoch++;
    await vi.advanceTimersByTimeAsync(1000);
    expect(requests()).toHaveLength(0);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.metadata-generation,video-call.chat.metadata-lifecycle
  it('retains the latest persisted exchange after compression covers the call history', async () => {
    m.history.length = 0;
    m.rows.set('user', { queue_revision: 1, status: 'synced', content: 'How do I make ramen?', created_at: 1 });
    m.rows.set('assistant', { queue_revision: 1, status: 'synced', content: 'Use vegetable broth.', created_at: 2 });
    const scheduler = new VoiceCallMetadataScheduler('chat', 'call');
    await scheduler.observe(turn('user')); await scheduler.observe(turn('assistant'));
    scheduler.finish(); await vi.advanceTimersByTimeAsync(0);
    expect(requests()).toHaveLength(1);
    expect(requests()[0][1]).toMatchObject({ context: { summary: 'Earlier vegetarian preference.', messages: [
      { role: 'user', content: 'How do I make ramen?', call_turn: true },
      { role: 'assistant', content: 'Use vegetable broth.', call_turn: true },
    ] } });
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.metadata-lifecycle
  it('retries unpaid stale admission after the encrypted baseline refresh, including after hangup', async () => {
    m.send.mockImplementationOnce(async (type, data) => {
      expect(type).toBe('voice_metadata_request');
      Object.assign(m.chat, { metadata_v: 1, encrypted_chat_summary: 'cipher:Earlier call summary.' });
      m.emit('voice_metadata_error', { request_id: data.request_id, code: 'metadata_stale' });
    });
    const scheduler = new VoiceCallMetadataScheduler('chat', 'call');
    await scheduler.observe(turn('user')); await scheduler.observe(turn('assistant'));
    scheduler.finish(); await vi.advanceTimersByTimeAsync(0);
    expect(requests()).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(750);
    expect(requests()).toHaveLength(2);
    expect(requests()[1][1]).toMatchObject({ source_metadata_v: 1, current_summary: 'Earlier call summary.' });
    expect(m.persist).toHaveBeenCalledOnce();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.metadata-lifecycle
  it('bounds rapid stale-admission retries for one unchanged source snapshot', async () => {
    for (let i = 0; i < 3; i++) m.send.mockImplementationOnce(async (_type, data) => {
      m.emit('voice_metadata_error', { request_id: data.request_id, code: 'metadata_stale' });
    });
    const scheduler = new VoiceCallMetadataScheduler('chat', 'call');
    await scheduler.observe(turn('user')); await scheduler.observe(turn('assistant'));
    await vi.advanceTimersByTimeAsync(15_000);
    expect(requests()).toHaveLength(3);
    expect(m.persist).not.toHaveBeenCalled();
    scheduler.finish();
    await vi.advanceTimersByTimeAsync(0);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.metadata-generation,video-call.chat.metadata-lifecycle
  it('acknowledges a recovered stale result without encrypting over newer manual metadata', async () => {
    Object.assign(m.chat, { title_v: 2, metadata_v: 3, encrypted_title: 'cipher:My title' });
    await applyVoiceCallMetadata(service, { request_id: 'recovered', call_id: 'ended-call', chat_id: 'chat',
      source_messages: [{ message_id: 'user', role: 'user', revision: 1 }], source_title_v: 0, source_metadata_v: 0,
      encrypted_chat_key: 'wrapped-key', result: { updated_chat_title: 'Generated title', chat_summary: 'Old summary.' } });
    expect(m.send).toHaveBeenCalledWith('voice_metadata_commit', { request_id: 'recovered', encrypted_metadata: {} });
    expect(m.persist).not.toHaveBeenCalled();
  });
});
