import { afterEach, describe, expect, it, vi } from 'vitest';
import { localReadToMessageWindow, RustHistoryRefusal, savedReadToMessages, savedReadToMessageWindow } from '../savedChatMessageRows';
import { declareRustChatHistorySource, installRustChatHistorySource, readRustChatHistoryWindow } from '../activeChatRustHistory';
import type { LocalChatReadback, SavedChatReadback, SavedMessageMetadata } from '../savedReadProtocol';
import type { Chat } from '../../../types/chat';

const chatId = '11111111-1111-4111-8111-111111111111';
const scope = 'a'.repeat(64);

function meta(id: string, createdAt: number, extra: Partial<SavedMessageMetadata> = {}): SavedMessageMetadata {
  return { id, chatId, createdAt, hasThinking: null, embedIds: null, storageId: null, sourceMessageId: null,
    clientMessageId: null, rawStatus: null, senderName: null, category: null, modelName: null, thinkingSignature: null,
    hashedUserId: null, userMessageId: null, queueMode: null, queueDispatchStatus: null, queueDispatchMode: null,
    queueDispatchTaskId: null, thinkingTokenCount: null, keyVersion: null, queueRevision: null, ...extra };
}

function read(overrides: Partial<SavedChatReadback> = {}): SavedChatReadback {
  return {
    chat: { id: chatId, title: 'Title', category: 'general', messages: [
      { id: 'm-user', role: 'user', content: 'Hello alice@example.com', sender: '', thinking: '', embeds: [] },
      { id: 'm-ai', role: 'assistant', content: 'Hi', sender: 'Mate', thinking: 'reasoning', embeds: [] },
    ] },
    chatMetadata: { id: chatId, title: null, summary: null, category: null, slug: null, activeFocusId: null, parentId: null,
      chatVisibility: null, createdAt: null, lastEditedAt: null, metadataUpdatedAt: null, isSubChat: null, isHidden: null,
      pinned: null, hasDraft: null, participantUserHashes: null, followUpSuggestions: null },
    messageMetadata: [
      meta('m-user', 100, { rawStatus: 'synced', clientMessageId: 'm-user', keyVersion: 2 }),
      meta('m-ai', 101, { rawStatus: 'processing', userMessageId: 'm-user', modelName: 'model', category: 'general', hasThinking: true, thinkingTokenCount: 7 }),
    ],
    hasMoreBefore: true, hasMoreAfter: false, anchorFound: false,
    startCursor: { chatId, scope, createdAt: 100, messageId: 'm-user' },
    endCursor: { chatId, scope, createdAt: 101, messageId: 'm-ai' },
    serverMessageCount: 2, messagesVersion: 2, oversizedMessage: false, oversizedMessageCursor: null,
    payloadBytes: 10, piiRestoration: 'page_local', historyComplete: false,
    piiMappingsByMessageId: { 'm-user': [{ placeholder: '[EMAIL_1]', original: 'alice@example.com', type: 'EMAIL' }] },
    contentMode: 'page_local', pagesRead: 1, ...overrides,
  };
}

describe('savedReadToMessages', () => {
  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('maps Rust decrypted rows to the existing Message rows', () => {
    const [user, assistant] = savedReadToMessages(read(), chatId);
    expect(user).toEqual({ message_id: 'm-user', chat_id: chatId, role: 'user', created_at: 100, status: 'synced',
      content: 'Hello alice@example.com', client_message_id: 'm-user', key_version: 2,
      pii_mappings: [{ placeholder: '[EMAIL_1]', original: 'alice@example.com', type: 'EMAIL' }] });
    expect(assistant).toEqual({ message_id: 'm-ai', chat_id: chatId, role: 'assistant', created_at: 101, status: 'synced',
      content: 'Hi', sender_name: 'Mate', category: 'general', model_name: 'model', thinking_content: 'reasoning',
      has_thinking: true, thinking_token_count: 7, user_message_id: 'm-user' });
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('keeps meaningful stored states and queue fields', () => {
    const page = read();
    page.messageMetadata[0] = meta('m-user', 100, { rawStatus: 'queued', queueMode: 'follow_up', queueDispatchStatus: 'queued', queueRevision: 0 });
    page.messageMetadata[1] = meta('m-ai', 101, { rawStatus: 'waiting_for_user' });
    const [user, assistant] = savedReadToMessages(page, chatId);
    expect(user).toMatchObject({ status: 'queued', queue_mode: 'follow_up', queue_dispatch_status: 'queued', queue_revision: 0 });
    expect(assistant.status).toBe('waiting_for_user');
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('refuses shapes it cannot represent with fixed codes', () => {
    const status = read();
    status.messageMetadata[1] = meta('m-ai', 101, { rawStatus: 'mystery' });
    expect(() => savedReadToMessages(status, chatId)).toThrow(new RustHistoryRefusal('unsupported_message_status'));
    const role = read();
    role.chat.messages[1] = { ...role.chat.messages[1], role: 'tool' };
    expect(() => savedReadToMessages(role, chatId)).toThrow(new RustHistoryRefusal('unsupported_role'));
    const pii = read({ piiMappingsByMessageId: { 'm-user': [{ placeholder: 1 }] } });
    expect(() => savedReadToMessages(pii, chatId)).toThrow(new RustHistoryRefusal('unsupported_pii_mapping'));
    expect(() => savedReadToMessageWindow(read(), chatId, true)).toThrow(new RustHistoryRefusal('anchor_not_found'));
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('treats identity mismatches as errors, not refusals', () => {
    expect(() => savedReadToMessages(read(), '22222222-2222-4222-8222-222222222222')).toThrow('protocol');
    const page = read();
    page.messageMetadata[1] = meta('other', 101);
    let error: unknown;
    try { savedReadToMessages(page, chatId); } catch (caught) { error = caught; }
    expect(error).not.toBeInstanceOf(RustHistoryRefusal);
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('maps the page window cursors', () => {
    expect(savedReadToMessageWindow(read(), chatId, false)).toMatchObject({ hasMoreBefore: true, hasMoreAfter: false,
      startCursor: 100, startCursorMessageId: 'm-user', endCursor: 101, endCursorMessageId: 'm-ai', anchorFound: true });
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('maps a Rust cache-first page to the same rows as the server page', () => {
    const server = read();
    const cached: LocalChatReadback = { source: 'local_profile', readOnly: true, cached: true, fresh: false, historyComplete: false,
      coverage: 'retained_only', chat: server.chat, hasMoreBefore: null, hasMoreAfter: false, anchorFound: false,
      startCursor: server.startCursor, endCursor: server.endCursor, payloadBytes: 10, piiRestoration: 'page_local',
      chatMetadata: server.chatMetadata, messageMetadata: server.messageMetadata, piiMappingsByMessageId: server.piiMappingsByMessageId,
      contentMode: 'page_local', pagesRead: 0 };
    const window = localReadToMessageWindow(cached, chatId, false);
    expect(window.messages).toEqual(savedReadToMessages(server, chatId));
    expect(window).toMatchObject({ hasMoreBefore: false, hasMoreAfter: false, startCursorMessageId: 'm-user', anchorFound: true });
    expect(() => localReadToMessageWindow(cached, chatId, true)).toThrow(new RustHistoryRefusal('anchor_not_found'));
    expect(() => localReadToMessageWindow({ ...cached, messageMetadata: undefined }, chatId, false)).toThrow('protocol');
  });
});

describe('readRustChatHistoryWindow', () => {
  const chat = { chat_id: chatId, messages_v: 2 } as Chat;
  const input = { anchorMessageId: null, activeTeamId: null, localInitialPending: false };
  let uninstall = () => {};
  afterEach(() => { uninstall(); vi.restoreAllMocks(); });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('is inert without an installed source (default builds)', async () => {
    expect(await readRustChatHistoryWindow(chat, input)).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('falls back only on typed refusals and rethrows errors', async () => {
    vi.spyOn(console, 'info').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const readWindow = vi.fn(async () => ({ window: savedReadToMessageWindow(read(), chatId, false), source: 'server' as const, reconcile: null }));
    uninstall = installRustChatHistorySource({ readWindow });
    expect((await readRustChatHistoryWindow(chat, input))?.window.messages).toHaveLength(2);
    expect(await readRustChatHistoryWindow({ ...chat, team_id: 'team' } as Chat, input)).toBeNull();
    expect(await readRustChatHistoryWindow({ ...chat, messages_v: 0 } as Chat, input)).toBeNull();
    // A local E2E fixture chat has no UUID the core could address; it stays with the TS path.
    expect(await readRustChatHistoryWindow({ ...chat, chat_id: 'e2e-chat-response-parity' } as Chat, input)).toBeNull();
    expect(console.info).toHaveBeenLastCalledWith('[RustCore] saved chat history refused:', 'local_fixture_chat');
    expect(readWindow).toHaveBeenCalledTimes(1);
    readWindow.mockRejectedValueOnce(new RustHistoryRefusal('unsupported_view'));
    expect(await readRustChatHistoryWindow(chat, input)).toBeNull();
    readWindow.mockRejectedValueOnce(new Error('session_expired'));
    await expect(readRustChatHistoryWindow(chat, input)).rejects.toThrow('session_expired');
    expect(console.error).toHaveBeenCalledWith('[RustCore] saved chat history failed:', 'session_expired');
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('waits for a declared source instead of racing its install', async () => {
    const readWindow = vi.fn(async () => ({ window: savedReadToMessageWindow(read(), chatId, false), source: 'cache' as const,
      reconcile: async () => savedReadToMessageWindow(read(), chatId, false) }));
    let finish = () => {};
    declareRustChatHistorySource(new Promise<void>((resolve) => { finish = () => { uninstall = installRustChatHistorySource({ readWindow }); resolve(); }; }));
    const pending = readRustChatHistoryWindow(chat, input);
    finish();
    const result = await pending;
    expect(result?.source).toBe('cache');
    expect(result?.reconcile).not.toBeNull();
    expect(readWindow).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('keeps the TS path when a declared install provides no source', async () => {
    declareRustChatHistorySource(Promise.reject(new Error('import_failed')));
    expect(await readRustChatHistoryWindow(chat, input)).toBeNull();
  });
});
