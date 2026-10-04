import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Editor } from '@tiptap/core';

const mocks = vi.hoisted(() => {
  const store = <T>(value: T) => ({ subscribe(run: (current: T) => void) { run(value); return () => undefined; } });
  const span = { end: vi.fn(), setAttribute: vi.fn() };
  const authState = { isAuthenticated: false };
  const draftState = { currentChatId: 'chat-auth', isSaveInProgress: false };
  const chatRecord = { chat_id: 'chat-auth', messages_v: 3, draft_v: 1, encrypted_chat_key: 'wrapped-key', encrypted_draft_md: 'encrypted-draft', encrypted_draft_preview: 'encrypted-preview' };
  const chatDB = {
    CHATS_STORE_NAME: 'chats',
    getTransaction: vi.fn(async () => ({ objectStore: () => ({ get: () => {
      const request: { result: typeof chatRecord; onsuccess?: () => void; onerror?: () => void } = { result: { ...chatRecord } };
      queueMicrotask(() => request.onsuccess?.());
      return request;
    } }) })),
    getChat: vi.fn(async () => ({ ...chatRecord })),
    saveMessage: vi.fn(async () => undefined),
    updateChat: vi.fn(async () => undefined),
    deleteMessage: vi.fn(async () => undefined),
  };
  const chatSyncService = {
    getActiveAITaskIdForChat: vi.fn(() => null),
    sendSetActiveChat: vi.fn(async () => undefined),
    sendNewMessage: vi.fn(),
    sendDeleteMessage: vi.fn(async () => undefined),
  };
  return {
    store,
    authState,
    draftState,
    chatDB,
    chatSyncService,
    getTracer: vi.fn(() => ({ startSpan: vi.fn(() => span) })),
    hasActualContent: vi.fn(() => true),
    sendTextMessage: vi.fn(),
    clearCurrentDraft: vi.fn(async () => undefined),
    refreshAnonymousFreeUsageStatus: vi.fn(async () => ({ active: true, can_send_text: true })),
    tipTapToCanonicalMarkdown: vi.fn(() => 'Send these attachments'),
    consumeClickedSuggestion: vi.fn(() => null),
    extractProjectFocusSendIntent: vi.fn(() => null),
  };
});

vi.mock('../../../services/sendersChatMessages', () => ({ isPreflightAcknowledgementTimeout: vi.fn(() => false) }));
vi.mock('../services/urlMetadataService', () => ({ createEmbedFromUrl: vi.fn() }));
vi.mock('../../../stores/demoModeStore', () => ({ demoMode: mocks.store(false) }));
vi.mock('../../../i18n/translations', () => ({ text: mocks.store((key: string) => key) }));
vi.mock('../../../demo_chats/convertToChat', () => ({ isPublicChat: vi.fn(() => false) }));
vi.mock('../../../services/tracing/setup', () => ({ getTracer: mocks.getTracer }));
vi.mock('@tiptap/core', () => ({ Extension: { create: vi.fn() } }));
vi.mock('../../../services/db', () => ({ chatDB: mocks.chatDB }));
vi.mock('../../../services/encryption/ChatKeyManager', () => ({ chatKeyManager: { getKeySync: vi.fn(() => 'local-key') } }));
vi.mock('../../../services/chatSyncService', () => ({ chatSyncService: mocks.chatSyncService }));
vi.mock('../../../services/chatListCache', () => ({ chatListCache: { setLastMessage: vi.fn() } }));
vi.mock('../../../stores/websocketStatusStore', () => ({ websocketStatus: mocks.store('connected') }));
vi.mock('../utils', () => ({ hasActualContent: mocks.hasActualContent, vibrateMessageField: vi.fn() }));
vi.mock('../../../services/drafts/draftState', () => ({ draftEditorUIState: { subscribe(run: (state: typeof mocks.draftState) => void) { run(mocks.draftState); return () => undefined; }, update: vi.fn() } }));
vi.mock('../../../services/drafts/draftSave', () => ({ clearCurrentDraft: mocks.clearCurrentDraft, saveDraftDebounced: { cancel: vi.fn() } }));
vi.mock('../../../message_parsing/serializers', () => ({ tipTapToCanonicalMarkdown: mocks.tipTapToCanonicalMarkdown }));
vi.mock('../../../services/anonymousChatStorage', () => ({
  AnonymousFreeUsageExhaustedError: class AnonymousFreeUsageExhaustedError extends Error {},
  anonymousChatStorage: { sendTextMessage: mocks.sendTextMessage },
}));
vi.mock('../../../stores/serverStatusStore', () => ({ refreshAnonymousFreeUsageStatus: mocks.refreshAnonymousFreeUsageStatus }));
vi.mock('../../../stores/authStore', () => ({ authStore: { subscribe(run: (state: typeof mocks.authState) => void) { run(mocks.authState); return () => undefined; } } }));
vi.mock('../../../stores/signupState', () => ({ forcedLogoutInProgress: mocks.store(false) }));
vi.mock('../../../stores/appSettingsMemoriesPermissionStore', () => ({ appSettingsMemoriesPermissionStore: { getCurrentRequestId: vi.fn(() => null), getCurrentChatId: vi.fn(() => null) } }));
vi.mock('../../../stores/editMessageStore', () => ({ editMessageStore: mocks.store(null), cancelEdit: vi.fn() }));
vi.mock('../../../stores/notificationStore', () => ({ notificationStore: { error: vi.fn(), addNotificationWithOptions: vi.fn() } }));
vi.mock('../../../stores/personalDataStore', () => ({ personalDataStore: { settings: mocks.store({ masterEnabled: false, categories: {} }), enabledEntries: mocks.store([]) } }));
vi.mock('../services/piiDetectionService', () => ({ detectPII: vi.fn(() => []), replacePIIWithPlaceholders: vi.fn(), createPIIMappingsForStorage: vi.fn(() => []) }));
vi.mock('../services/placeholderRewriteService', () => ({ rewriteKnownPIIPlaceholders: vi.fn() }));
vi.mock('../../../stores/embedPIIStore', () => ({ getActivePIIMappingsForRewrite: vi.fn(() => []) }));
vi.mock('../../../stores/teamStore', () => ({ activeTeamId: mocks.store(null) }));
vi.mock('../../../services/teamService', () => ({ isTeamAIInvocation: vi.fn(() => false), wrapTeamChatKey: vi.fn() }));
vi.mock('../../../services/cryptoService', () => ({ encryptWithChatKey: vi.fn() }));
vi.mock('../../../stores/incognitoModeStore', () => ({ incognitoMode: { get: vi.fn(() => false) } }));
vi.mock('../../../services/incognitoChatService', () => ({ incognitoChatService: { getChat: vi.fn(async () => null) } }));
vi.mock('../../../stores/suggestionTracker', () => ({ consumeClickedSuggestion: mocks.consumeClickedSuggestion }));
vi.mock('../../../services/projectFocusSendPreflight', () => ({
  extractProjectFocusSendIntent: mocks.extractProjectFocusSendIntent,
  ProjectFocusSendPreflightError: class ProjectFocusSendPreflightError extends Error {},
}));

import { handleSend } from './sendHandlers';

function makeEditor() {
  const document = {
    type: 'doc',
    content: [
      { type: 'paragraph', content: [{ type: 'text', text: 'Send these attachments' }] },
      { type: 'embed', attrs: { id: 'image-1', type: 'image', status: 'finished', contentRef: 'embed:image-1' } },
      { type: 'embed', attrs: { id: 'audio-1', type: 'recording', status: 'finished', contentRef: 'embed:audio-1' } },
    ],
  };
  const clearContent = vi.fn(() => { document.content = [] as typeof document.content; });
  const blur = vi.fn();
  const editor = {
    isDestroyed: false,
    isEmpty: false,
    getText: vi.fn(() => 'Send these attachments'),
    getJSON: vi.fn(() => document),
    view: { state: { doc: { descendants(callback: (node: { type: { name: string }; attrs: Record<string, unknown> }) => boolean): void {
      for (const item of document.content) {
        if (item.type === 'embed' && 'attrs' in item) {
          callback({ type: { name: 'embed' }, attrs: item.attrs });
        }
      }
    } } } },
    commands: { clearContent, blur, focus: vi.fn() },
  };
  return { editor: editor as unknown as Editor, document, clearContent, blur };
}

async function waitForTransportCall() {
  await vi.waitFor(() => expect(mocks.sendTextMessage).toHaveBeenCalledTimes(1));
}

describe('handleSend anonymous acceptance lifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.authState.isAuthenticated = false;
    mocks.refreshAnonymousFreeUsageStatus.mockResolvedValue({ active: true, can_send_text: true });
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it('keeps image and audio composer nodes while transport acceptance is pending', async () => {
    let accept!: () => void;
    mocks.sendTextMessage.mockImplementation(() => new Promise<void>((resolve) => { accept = resolve; }));
    const { editor, document, clearContent, blur } = makeEditor();
    const original = structuredClone(document);
    const setHasContent = vi.fn();

    const result = handleSend(editor, vi.fn(), setHasContent);
    await waitForTransportCall();
    expect(document).toEqual(original);
    expect(clearContent).not.toHaveBeenCalled();
    expect(blur).not.toHaveBeenCalled();

    accept();
    await result;
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it('preserves complete editor JSON and focus when transport rejects', async () => {
    mocks.sendTextMessage.mockRejectedValue(new Error('synthetic transport failure'));
    const { editor, document, clearContent, blur } = makeEditor();
    const original = structuredClone(document);
    const setHasContent = vi.fn();

    const result = await handleSend(editor, vi.fn(), setHasContent);

    expect(result).toBeUndefined();
    expect(document).toEqual(original);
    expect(clearContent).not.toHaveBeenCalled();
    expect(blur).not.toHaveBeenCalled();
    expect(setHasContent).not.toHaveBeenCalledWith(false);
    expect(mocks.clearCurrentDraft).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it('clears and blurs only after transport accepts', async () => {
    mocks.sendTextMessage.mockResolvedValue(undefined);
    const { editor, clearContent, blur } = makeEditor();
    const setHasContent = vi.fn();

    const result = await handleSend(editor, vi.fn(), setHasContent);

    expect(result).toBe(true);
    expect(clearContent).toHaveBeenCalledWith(false);
    expect(blur).toHaveBeenCalledOnce();
    expect(setHasContent).toHaveBeenCalledWith(false);
    expect(mocks.clearCurrentDraft).toHaveBeenCalledOnce();
  });
});

describe('handleSend authenticated acceptance lifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.authState.isAuthenticated = true;
    mocks.draftState.currentChatId = 'chat-auth';
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it('keeps image and audio nodes while sendNewMessage is pending', async () => {
    let accept!: () => void;
    mocks.chatSyncService.sendNewMessage.mockImplementation(() => new Promise<void>((resolve) => { accept = resolve; }));
    const { editor, document, clearContent, blur } = makeEditor();
    const original = structuredClone(document);
    const setHasContent = vi.fn();

    const result = handleSend(editor, vi.fn(), setHasContent, 'chat-auth');
    await vi.waitFor(() => expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledTimes(1));
    expect(document).toEqual(original);
    expect(clearContent).not.toHaveBeenCalled();
    expect(blur).not.toHaveBeenCalled();
    expect(setHasContent).not.toHaveBeenCalledWith(false);

    accept();
    await result;
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it('preserves complete editor JSON and focus when sendNewMessage rejects', async () => {
    mocks.chatSyncService.sendNewMessage.mockRejectedValue(new Error('synthetic transport failure'));
    const { editor, document, clearContent, blur } = makeEditor();
    const original = structuredClone(document);
    const setHasContent = vi.fn();

    const result = await handleSend(editor, vi.fn(), setHasContent, 'chat-auth');

    expect(result).toBeUndefined();
    expect(document).toEqual(original);
    expect(clearContent).not.toHaveBeenCalled();
    expect(blur).not.toHaveBeenCalled();
    expect(setHasContent).not.toHaveBeenCalledWith(false);
    expect(mocks.clearCurrentDraft).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it('clears and blurs after sendNewMessage accepts the unchanged document', async () => {
    mocks.chatSyncService.sendNewMessage.mockResolvedValue(undefined);
    const { editor, clearContent, blur } = makeEditor();
    const setHasContent = vi.fn();

    const result = await handleSend(editor, vi.fn(), setHasContent, 'chat-auth');

    expect(result).toBe(true);
    expect(clearContent).toHaveBeenCalledWith(false);
    expect(blur).toHaveBeenCalledOnce();
    expect(setHasContent).toHaveBeenCalledWith(false);
    expect(mocks.clearCurrentDraft).toHaveBeenCalledOnce();
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it('keeps content typed while transport is pending after acceptance', async () => {
    let accept!: () => void;
    mocks.chatSyncService.sendNewMessage.mockImplementation(() => new Promise<void>((resolve) => { accept = resolve; }));
    const { editor, document, clearContent, blur } = makeEditor();
    const setHasContent = vi.fn();

    const result = handleSend(editor, vi.fn(), setHasContent, 'chat-auth');
    await vi.waitFor(() => expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledTimes(1));
    document.content.push({ type: 'paragraph', content: [{ type: 'text', text: 'New thought while sending' }] });
    const editedDocument = structuredClone(document);
    accept();
    expect(await result).toBe(true);

    expect(document).toEqual(editedDocument);
    expect(clearContent).not.toHaveBeenCalled();
    expect(blur).not.toHaveBeenCalled();
    expect(setHasContent).not.toHaveBeenCalledWith(false);
    expect(mocks.clearCurrentDraft).not.toHaveBeenCalled();
  });
});
