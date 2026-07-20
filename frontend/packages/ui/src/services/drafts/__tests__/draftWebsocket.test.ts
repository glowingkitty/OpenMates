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
      getRawChat: vi.fn(async () => ({ chat_id: 'chat-1', draft_v: 0 })),
      upsertRawChat: vi.fn(async () => {
        store.update((current) => ({
          ...current,
          currentUserDraftVersion: 1,
          lastSavedContentMarkdown: 'Please read this document.',
        }));
      }),
      getAllChats: vi.fn(async () => []),
    },
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
  });

  afterEach(() => {
    unregisterWebSocketHandlers();
  });

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
  });
});
