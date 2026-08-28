// frontend/packages/ui/src/services/drafts/__tests__/draftCore.test.ts
// Unit tests for draftCore context switching behavior.
// Guards against delayed empty-draft restores wiping text that a user already
// typed into the composer before the async draft restore finished.
// The real editor is mocked so tests exercise only the draft service contract:
// context may update, but typed content must not be cleared for the same pending context.
// contract-test-file: tooling

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => {
  type DraftState = {
    currentChatId: string | null;
    currentUserDraftVersion: number;
    hasUnsavedChanges: boolean;
    lastSavedContentMarkdown: string | null;
    isSwitchingContext: boolean;
  };

  let state: DraftState = {
    currentChatId: null,
    currentUserDraftVersion: 0,
    hasUnsavedChanges: false,
    lastSavedContentMarkdown: null,
    isSwitchingContext: false,
  };
  const subscribers = new Set<(value: DraftState) => void>();

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
        currentChatId: null,
        currentUserDraftVersion: 0,
        hasUnsavedChanges: false,
        lastSavedContentMarkdown: null,
        isSwitchingContext: false,
        ...value,
      });
    },
  };

  return {
    draftEditorUIState: store,
    flushSaveDraft: vi.fn(),
    isContentEmptyExceptMention: vi.fn(),
    registerWebSocketHandlers: vi.fn(),
    unregisterWebSocketHandlers: vi.fn(),
  };
});

vi.mock('../draftState', () => ({
  draftEditorUIState: mocks.draftEditorUIState,
  initialDraftEditorState: {},
}));

vi.mock('../draftWebsocket', () => ({
  registerWebSocketHandlers: mocks.registerWebSocketHandlers,
  unregisterWebSocketHandlers: mocks.unregisterWebSocketHandlers,
}));

vi.mock('../draftSave', () => ({
  flushSaveDraft: mocks.flushSaveDraft,
  saveDraftDebounced: { cancel: vi.fn() },
}));

vi.mock('../../../stores/authStore', () => ({
  authStore: {
    subscribe(fn: (value: { isAuthenticated: boolean }) => void) {
      fn({ isAuthenticated: true });
      return () => {};
    },
  },
}));

vi.mock('../../../components/enter_message/utils', () => ({
  getInitialContent: () => ({ type: 'doc', content: [] }),
  isContentEmptyExceptMention: mocks.isContentEmptyExceptMention,
}));

import {
  cleanupDraftService,
  initializeDraftService,
  reconcilePreservedDraftVersion,
  setCurrentChatContext,
  shouldPreserveSameChatDraftRestore,
} from '../draftCore';

function createEditorMock() {
  const chain = {
    setContent: vi.fn(() => chain),
    run: vi.fn(),
  };
  return {
    editor: {
      chain: vi.fn(() => chain),
      getText: vi.fn(() => 'max@posteo.de'),
    },
    chain,
  };
}

describe('draftCore setCurrentChatContext', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    mocks.draftEditorUIState.reset();
    mocks.isContentEmptyExceptMention.mockReturnValue(false);
  });

  afterEach(() => {
    cleanupDraftService();
    vi.useRealTimers();
  });

  it('does not clear already typed content during a delayed empty draft restore', async () => {
    const { editor, chain } = createEditorMock();
    initializeDraftService(editor as never);

    await setCurrentChatContext('chat-1', null, 0);

    expect(chain.setContent).not.toHaveBeenCalled();
  });

  it('still clears the editor when switching to a different chat without a draft', async () => {
    const { editor, chain } = createEditorMock();
    mocks.draftEditorUIState.reset({ currentChatId: 'chat-1' });
    initializeDraftService(editor as never);

    const contextPromise = setCurrentChatContext('chat-2', null, 0);
    await vi.advanceTimersByTimeAsync(50);
    await contextPromise;

    expect(chain.setContent).toHaveBeenCalledWith(
      { type: 'doc', content: [] },
      { emitUpdate: false },
    );
  });
});

describe('shouldPreserveSameChatDraftRestore', () => {
  it('preserves editor content changed after the incoming snapshot was saved', () => {
    expect(shouldPreserveSameChatDraftRestore('chat-1', '@', '@wiki:AlbertEin', {
      currentChatId: 'chat-1',
      currentUserDraftVersion: 1,
      hasUnsavedChanges: false,
      lastSavedContentMarkdown: '@',
      isSwitchingContext: false,
      isSaveInProgress: false,
      newlyCreatedChatIdToSelect: null,
    })).toBe(true);
  });

  it('allows incoming content when switching chat context', () => {
    expect(shouldPreserveSameChatDraftRestore('chat-2', 'restored', 'local', {
      currentChatId: 'chat-1',
      currentUserDraftVersion: 1,
      hasUnsavedChanges: true,
      lastSavedContentMarkdown: 'local',
      isSwitchingContext: false,
      isSaveInProgress: true,
      newlyCreatedChatIdToSelect: null,
    })).toBe(false);
  });

  it('advances the same-chat version without clearing local draft flags', () => {
    const state = {
      currentChatId: 'chat-1',
      currentUserDraftVersion: 1,
      hasUnsavedChanges: true,
      lastSavedContentMarkdown: '@',
      isSwitchingContext: false,
      isSaveInProgress: true,
      newlyCreatedChatIdToSelect: null,
    };

    expect(reconcilePreservedDraftVersion(state, 'chat-1', 2)).toEqual({
      ...state,
      currentUserDraftVersion: 2,
    });
  });
});
