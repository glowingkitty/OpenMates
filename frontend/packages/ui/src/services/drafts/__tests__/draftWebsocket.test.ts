// frontend/packages/ui/src/services/drafts/__tests__/draftWebsocket.test.ts
// Regression coverage for draft WebSocket echo handling.
// The draft service receives server echoes asynchronously, while the composer can
// keep changing locally. These tests guard the contract that a late echo must not
// overwrite newer in-editor content such as freshly inserted upload embeds.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type DraftState = {
  currentChatId: string | null;
  currentUserDraftVersion: number;
  hasUnsavedChanges: boolean;
  lastSavedContentMarkdown: string | null;
  isSwitchingContext: boolean;
  isSaveInProgress: boolean;
};

const mocks = vi.hoisted(() => {
  let state: DraftState = {
    currentChatId: 'chat-1',
    currentUserDraftVersion: 0,
    hasUnsavedChanges: false,
    lastSavedContentMarkdown: null,
    isSwitchingContext: false,
    isSaveInProgress: false,
  };
  const subscribers = new Set<(value: DraftState) => void>();
  const handlers = new Map<string, (payload: unknown) => unknown>();

  const store = {
    subscribe(fn: (value: DraftState) => void) {
      fn(state);
      subscribers.add(fn);
      return () => subscribers.delete(fn);
    },
    set(value: DraftState) {
      state = value;
      subscribers.forEach((fn) => fn(state));
    },
    update(fn: (value: DraftState) => DraftState) {
      store.set(fn(state));
    },
    reset(value: Partial<DraftState> = {}) {
      store.set({
        currentChatId: 'chat-1',
        currentUserDraftVersion: 0,
        hasUnsavedChanges: false,
        lastSavedContentMarkdown: null,
        isSwitchingContext: false,
        isSaveInProgress: false,
        ...value,
      });
    },
    getState() {
      return state;
    },
  };

  const setContent = vi.fn();
  const chain = {
    setContent: vi.fn(() => chain),
    run: vi.fn(),
  };
  const editor = {
    isEditable: true,
    getJSON: vi.fn(() => ({ markdown: 'Please read this document.\n\n[PDF]' })),
    chain: vi.fn(() => chain),
  };
  chain.setContent.mockImplementation((...args: unknown[]) => {
    setContent(...args);
    return chain;
  });

  return {
    chatDB: {
      getRawChat: vi.fn(),
      getChat: vi.fn(),
      updateChat: vi.fn(),
      deleteChat: vi.fn(),
      upsertRawChat: vi.fn(async () => {
        store.update((current) => ({
          ...current,
          currentUserDraftVersion: 1,
          lastSavedContentMarkdown: 'Please read this document.',
        }));
      }),
      getAllChats: vi.fn(),
    },
    chatListCache: { getCache: vi.fn(), removeChat: vi.fn() },
    chatSyncService: { dispatchEvent: vi.fn() },
    chatMetadataCache: { invalidateChat: vi.fn() },
    decryptWithMasterKey: vi.fn(async () => 'Please read this document.'),
    draftEditorUIState: store,
    editor,
    getEditorInstance: vi.fn(() => editor),
    handlers,
    parseMessage: vi.fn(() => ({ type: 'doc', content: [{ type: 'paragraph' }] })),
    setContent,
    tipTapToCanonicalMarkdown: vi.fn(() => 'Please read this document.\n\n[PDF]'),
    webSocketService: {
      on: vi.fn((event: string, handler: (payload: unknown) => unknown) => {
        handlers.set(event, handler);
      }),
      off: vi.fn((event: string) => {
        handlers.delete(event);
      }),
      sendMessage: vi.fn(),
    },
  };
});

vi.mock('../../db', () => ({ chatDB: mocks.chatDB }));
vi.mock('../../websocketService', () => ({ webSocketService: mocks.webSocketService }));
vi.mock('../../chatMetadataCache', () => ({ chatMetadataCache: mocks.chatMetadataCache }));
vi.mock('../../chatListCache', () => ({ chatListCache: mocks.chatListCache }));
vi.mock('../../chatSyncService', () => ({ chatSyncService: mocks.chatSyncService }));
vi.mock('../../cryptoService', () => ({ decryptWithMasterKey: mocks.decryptWithMasterKey }));
vi.mock('../draftState', () => ({ draftEditorUIState: mocks.draftEditorUIState }));
vi.mock('../draftCore', () => ({ getEditorInstance: mocks.getEditorInstance }));
vi.mock('../../../components/enter_message/utils', () => ({
  getInitialContent: () => ({ type: 'doc', content: [] }),
}));
vi.mock('../../../message_parsing/parse_message', () => ({ parse_message: mocks.parseMessage }));
vi.mock('../../../message_parsing/serializers', () => ({
  tipTapToCanonicalMarkdown: mocks.tipTapToCanonicalMarkdown,
}));

import { registerWebSocketHandlers, unregisterWebSocketHandlers } from '../draftWebsocket';

describe('draftWebsocket chat_draft_updated', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.handlers.clear();
    mocks.draftEditorUIState.reset();
    mocks.chatDB.getRawChat.mockResolvedValue({ chat_id: 'chat-1', draft_v: 0 });
    mocks.chatDB.getAllChats.mockResolvedValue([]);
    mocks.chatDB.deleteChat.mockResolvedValue({ deletedEmbedIds: [] });
    mocks.chatListCache.getCache.mockReturnValue(null);
  });

  afterEach(() => {
    unregisterWebSocketHandlers();
  });

  // contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.persistence.local-first-encrypted
  it('preserves newer local editor content when a stale server echo arrives after an embed insert', async () => {
    registerWebSocketHandlers();
    const handler = mocks.handlers.get('chat_draft_updated');
    expect(handler).toBeTruthy();

    await handler?.({
      chat_id: 'chat-1',
      data: {
        encrypted_draft_md: '<encrypted prompt only>',
        encrypted_draft_preview: null,
      },
      versions: { draft_v: 1 },
      last_edited_overall_timestamp: 100,
    });

    expect(mocks.setContent).not.toHaveBeenCalled();
    expect(mocks.chatDB.upsertRawChat).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
  it('preserves a local draft newer than the reconnect tombstone', async () => {
    mocks.chatDB.getRawChat.mockResolvedValue({
      chat_id: 'chat-1',
      encrypted_draft_md: 'new-local-draft',
      encrypted_draft_preview: 'new-local-preview',
      draft_v: 5,
    });
    registerWebSocketHandlers();
    const handler = mocks.handlers.get('draft_versions_response');
    expect(handler).toBeTruthy();

    await handler?.({
      versions: { 'chat-1': 0 },
      tombstone_versions: { 'chat-1': 4 },
    });

    expect(mocks.chatDB.updateChat).not.toHaveBeenCalled();
    expect(mocks.chatDB.deleteChat).not.toHaveBeenCalled();
    expect(mocks.chatMetadataCache.invalidateChat).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
  it('removes a draft-only shell cleared on another device while offline', async () => {
    mocks.chatDB.getRawChat.mockResolvedValue({
      chat_id: 'chat-1', encrypted_draft_md: 'master-key-ciphertext',
      draft_v: 1, messages_v: 0, title_v: 0,
    });
    registerWebSocketHandlers();

    await mocks.handlers.get('draft_versions_response')?.({
      versions: { 'chat-1': 0 }, tombstone_versions: { 'chat-1': 2 },
    });

    expect(mocks.chatDB.deleteChat).toHaveBeenCalledWith('chat-1');
    expect(mocks.chatDB.updateChat).not.toHaveBeenCalled();
    expect(mocks.chatListCache.removeChat).toHaveBeenCalledWith('chat-1');
    expect(mocks.chatSyncService.dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'chatDeleted', detail: { chat_id: 'chat-1' } }),
    );
  });

  // contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative,drafts.established-chat.presentation-unchanged
  it.each([{ messages_v: 1 }, { encrypted_title: 'encrypted-title', title_v: 1 }])(
    'retains established chat history while clearing an offline draft with %j', async (metadata) => {
      mocks.chatDB.getRawChat.mockResolvedValue({
        chat_id: 'chat-1', encrypted_draft_md: 'master-key-ciphertext',
        draft_v: 1, messages_v: 0, title_v: 0, ...metadata,
      });
      registerWebSocketHandlers();

      await mocks.handlers.get('draft_versions_response')?.({
        versions: { 'chat-1': 0 }, tombstone_versions: { 'chat-1': 2 },
      });

      expect(mocks.chatDB.deleteChat).not.toHaveBeenCalled();
      expect(mocks.chatDB.updateChat).toHaveBeenCalledWith(expect.objectContaining({
        ...metadata, encrypted_draft_md: null, encrypted_draft_preview: null,
        draft_v: 0, cleared_draft_v: 2,
      }));
    },
  );

  // contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative,drafts.persistence.local-first-encrypted
  it('preserves unsaved editor text during reconnect deletion reconciliation', async () => {
    mocks.draftEditorUIState.reset({ hasUnsavedChanges: true });
    mocks.chatDB.getRawChat.mockResolvedValue({
      chat_id: 'chat-1', encrypted_draft_md: 'older-saved-draft', draft_v: 1,
    });
    registerWebSocketHandlers();

    await mocks.handlers.get('draft_versions_response')?.({
      versions: { 'chat-1': 0 }, tombstone_versions: { 'chat-1': 2 },
    });

    expect(mocks.chatDB.deleteChat).not.toHaveBeenCalled();
    expect(mocks.chatDB.updateChat).not.toHaveBeenCalled();
    expect(mocks.chatSyncService.dispatchEvent).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=drafts.draft-only.lifecycle,drafts.sync.version-authoritative
  it('removes an already-cleared empty shell even after the server tombstone expires', async () => {
    mocks.chatDB.getRawChat.mockResolvedValue({
      chat_id: 'chat-1', encrypted_draft_md: null, encrypted_draft_preview: null,
      draft_v: 0, cleared_draft_v: 2, messages_v: 0, title_v: 0,
    });
    registerWebSocketHandlers();

    await mocks.handlers.get('draft_versions_response')?.({ versions: { 'chat-1': 0 } });

    expect(mocks.chatDB.deleteChat).toHaveBeenCalledWith('chat-1');
    expect(mocks.chatListCache.removeChat).toHaveBeenCalledWith('chat-1');
  });

  // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle,drafts.established-chat.presentation-unchanged
  it('reconciles old empty draft shells on reconnect while excluding cleared established chats', async () => {
    mocks.draftEditorUIState.reset({ currentChatId: null });
    mocks.chatDB.getAllChats.mockResolvedValue([
      { chat_id: 'old-empty-draft', draft_v: 0, cleared_draft_v: 2, messages_v: 0, title_v: 0 },
      { chat_id: 'chat-with-history', draft_v: 0, cleared_draft_v: 2, messages_v: 1 },
      { chat_id: 'generated-chat', draft_v: 0, cleared_draft_v: 2, encrypted_title: 'encrypted-title' },
    ]);
    registerWebSocketHandlers();

    await mocks.handlers.get('open')?.(undefined);

    expect(mocks.webSocketService.sendMessage).toHaveBeenCalledExactlyOnceWith('get_draft_versions', {
      chats: [{ chat_id: 'old-empty-draft', client_draft_v: 0 }],
    });
  });
});
