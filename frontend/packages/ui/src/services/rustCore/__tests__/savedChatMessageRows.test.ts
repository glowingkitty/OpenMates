import { afterEach, describe, expect, it, vi } from 'vitest';
import { isConfirmedEmptyLatestLocalWindow, localReadToMessageWindow, RustHistoryRefusal, savedReadToMessages, savedReadToMessageWindow } from '../savedChatMessageRows';
import { canPreparePersonalLatestHistory, declareRustChatHistorySource, installRustChatHistorySource, preparePersonalLatestHistory, readRustChatHistoryPage, readRustChatHistoryWindow } from '../activeChatRustHistory';
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
  // contract-test: supporting surface=gui.web assertions=app-memories.conversation.explicit-approval
  it('exposes memory-response mappings on the system row', () => {
    const mapping = { placeholder: '[EMAIL_2]', original: 'jane.doe@example.org', type: 'EMAIL' };
    const base = read();
    const rows = savedReadToMessages(read({
      chat: { ...base.chat, messages: [...base.chat.messages,
        { id: 'm-sys', role: 'system', content: '{"type":"app_settings_memories_response"}', sender: '', thinking: '', embeds: [] }] },
      messageMetadata: [...base.messageMetadata, meta('m-sys', 102)],
      piiMappingsByMessageId: { ...base.piiMappingsByMessageId, 'm-sys': [mapping] },
    }), chatId);
    expect(rows[2].role).toBe('system');
    expect(rows[2].pii_mappings).toEqual([mapping]);
  });

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
    // The opaque Rust cursors survive the mapping so the next page chains through Rust.
    expect(savedReadToMessageWindow(read(), chatId, false).startCursorRef).toEqual({ chatId, scope, createdAt: 100, messageId: 'm-user' });
    expect(savedReadToMessageWindow(read(), chatId, false).endCursorRef).toEqual({ chatId, scope, createdAt: 101, messageId: 'm-ai' });
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
    expect(window.startCursorRef).toEqual(server.startCursor);
    expect(() => localReadToMessageWindow(cached, chatId, true)).toThrow(new RustHistoryRefusal('anchor_not_found'));
    expect(() => localReadToMessageWindow({ ...cached, messageMetadata: undefined }, chatId, false)).toThrow('protocol');
  });
});

describe('confirmed empty local latest window', () => {
  const profilePage: LocalChatReadback = {
    source: 'local_profile', coverage: 'retained_only', readOnly: true, cached: true, fresh: false,
    historyComplete: false, contentMode: 'page_local', pagesRead: 0, piiRestoration: 'page_local',
    chat: { ...read().chat, messages: [] }, chatMetadata: read().chatMetadata, messageMetadata: [],
    piiMappingsByMessageId: {}, hasMoreBefore: null, hasMoreAfter: false, anchorFound: false,
    startCursor: null, endCursor: null, payloadBytes: 0,
  };

  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
  it('accepts an exact Rust latest miss but never an anchored or unsettled cache read', () => {
    expect(isConfirmedEmptyLatestLocalWindow(profilePage, chatId, null)).toBe(true);
    expect(isConfirmedEmptyLatestLocalWindow(profilePage, chatId, 'anchor')).toBe(false);
    expect(isConfirmedEmptyLatestLocalWindow(null, chatId, null)).toBe(false);
    expect(isConfirmedEmptyLatestLocalWindow({ ...profilePage, chat: read().chat }, chatId, null)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.authoritative-enforcement
  it('refuses mismatched, malformed, or cursor-bearing cache evidence', () => {
    expect(isConfirmedEmptyLatestLocalWindow(profilePage, 'other-chat', null)).toBe(false);
    expect(isConfirmedEmptyLatestLocalWindow({ ...profilePage, chatMetadata: { ...read().chatMetadata, id: 'other-chat' } }, chatId, null)).toBe(false);
    expect(isConfirmedEmptyLatestLocalWindow({ ...profilePage, messageMetadata: undefined }, chatId, null)).toBe(false);
    expect(isConfirmedEmptyLatestLocalWindow({ ...profilePage, startCursor: read().startCursor }, chatId, null)).toBe(false);
  });
});

describe('early Personal latest history', () => {
  const owner = 'current-owner';
  const chat = { chat_id: chatId, user_id: owner, messages_v: 2, encrypted_chat_key: 'fixture-wrapper',
    is_hidden: false, is_hidden_candidate: false } as Chat;

  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent,auth.session.authoritative-enforcement
  it('requires a confirmed ordinary Personal row and its current owner', () => {
    expect(canPreparePersonalLatestHistory(chat, owner)).toBe(true);
    expect(canPreparePersonalLatestHistory(chat, null)).toBe(false);
    expect(canPreparePersonalLatestHistory(chat, 'other-owner')).toBe(false);
    const unclear: Array<Partial<Chat>> = [
      { chat_id: 'example' }, { messages_v: 0 }, { encrypted_chat_key: null }, { is_hidden: true },
      { is_hidden_candidate: undefined }, { is_hidden_candidate: true }, { team_id: 'team' },
      { chat_visibility: 'direct' }, { is_incognito: true }, { is_anonymous: true }, { is_shared: true },
      { is_shared_by_others: true }, { parent_id: 'parent' }, { encrypted_draft_md: 'draft' },
      { waiting_for_metadata: true },
    ];
    for (const fields of unclear) expect(canPreparePersonalLatestHistory({ ...chat, ...fields }, owner)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent,auth.session.authoritative-enforcement
  it('starts one latest request immediately and retains a denial for later consumption', async () => {
    const failure = new Error('session_expired');
    const readWindow = vi.fn(async () => { throw failure; });
    const unregister = installRustChatHistorySource({ readWindow, readPage: vi.fn() });
    const log = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      const prepared = preparePersonalLatestHistory(chat);
      expect(readWindow).toHaveBeenCalledExactlyOnceWith({ chatId, anchorMessageId: null });
      await vi.waitFor(() => expect(log).toHaveBeenCalledExactlyOnceWith('[RustCore] saved chat history failed:', 'session_expired'));
      await expect(prepared).rejects.toBe(failure);
      expect(readWindow).toHaveBeenCalledOnce();
    } finally { unregister(); log.mockRestore(); }
  });
});

describe('readRustChatHistoryWindow', () => {
  const chat = { chat_id: chatId, messages_v: 2 } as Chat;
  const input = { anchorMessageId: null, activeTeamId: null, localInitialPending: false };
  const readPage = vi.fn(async () => savedReadToMessageWindow(read(), chatId, false));
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
    uninstall = installRustChatHistorySource({ readWindow, readPage });
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
    declareRustChatHistorySource(new Promise<void>((resolve) => { finish = () => { uninstall = installRustChatHistorySource({ readWindow, readPage }); resolve(); }; }));
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

describe('readRustChatHistoryPage', () => {
  const chat = { chat_id: chatId, messages_v: 2 } as Chat;
  const selector = { direction: 'before' as const, cursor: { chatId, scope, createdAt: 100, messageId: 'm-user' }, limit: 20, respectCompressionBoundary: false };
  let uninstall = () => {};
  afterEach(() => { uninstall(); vi.restoreAllMocks(); });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('pages through the Rust source and refuses only unowned chat shapes', async () => {
    vi.spyOn(console, 'info').mockImplementation(() => {});
    expect(await readRustChatHistoryPage(chat, { selector, activeTeamId: null })).toBeNull();
    const readPage = vi.fn(async () => savedReadToMessageWindow(read(), chatId, false));
    uninstall = installRustChatHistorySource({ readWindow: vi.fn(), readPage });
    expect((await readRustChatHistoryPage(chat, { selector, activeTeamId: null }))?.messages).toHaveLength(2);
    expect(readPage).toHaveBeenCalledWith({ chatId, selector });
    expect(await readRustChatHistoryPage({ ...chat, team_id: 'team' } as Chat, { selector, activeTeamId: null })).toBeNull();
    expect(await readRustChatHistoryPage({ ...chat, is_shared_by_others: true } as Chat, { selector, activeTeamId: null })).toBeNull();
    expect(console.info).toHaveBeenLastCalledWith('[RustCore] saved chat page refused:', 'shared_chat');
    expect(readPage).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('rethrows non-refusal page failures', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    uninstall = installRustChatHistorySource({ readWindow: vi.fn(), readPage: vi.fn(async () => { throw new Error('session_expired'); }) });
    await expect(readRustChatHistoryPage(chat, { selector, activeTeamId: null })).rejects.toThrow('session_expired');
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('an unreachable server hands older paging back to the local cache', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    for (const code of ['unavailable', 'deadline']) {
      uninstall = installRustChatHistorySource({ readWindow: vi.fn(), readPage: vi.fn(async () => { throw new Error(code); }) });
      expect(await readRustChatHistoryPage(chat, { selector, activeTeamId: null }), code).toBeNull();
      uninstall();
    }
  });
});
