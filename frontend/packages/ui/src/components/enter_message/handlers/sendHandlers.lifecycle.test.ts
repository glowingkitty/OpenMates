import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Editor } from '@tiptap/core';
import { createHash } from 'node:crypto';
import { get } from 'svelte/store';

const mocks = vi.hoisted(() => {
  const store = <T>(value: T) => ({ subscribe(run: (current: T) => void) { run(value); return () => undefined; } });
  const span = { end: vi.fn(), setAttribute: vi.fn() };
  const authState = { isAuthenticated: false };
  const wsStatus = { status: 'connected' };
  const teamContext = { teamId: null as string | null, epoch: 0 };
  const draftState = { currentChatId: 'chat-auth' as string | null, isSaveInProgress: false };
  const chatRecord = { chat_id: 'chat-auth', team_id: null as string | null, messages_v: 3, draft_v: 1, encrypted_chat_key: 'wrapped-key', encrypted_draft_md: 'encrypted-draft', encrypted_draft_preview: 'encrypted-preview' };
  const chatDB = {
    CHATS_STORE_NAME: 'chats',
    ensureReadyForSend: vi.fn(async () => undefined),
    getTransaction: vi.fn(async (): Promise<unknown> => ({ objectStore: () => ({ get: () => {
      const request: { result: typeof chatRecord; onsuccess?: () => void; onerror?: () => void } = { result: { ...chatRecord } };
      queueMicrotask(() => request.onsuccess?.());
      return request;
    } }) })),
    getChat: vi.fn(async () => ({ ...chatRecord })),
    addChat: vi.fn(async () => undefined),
    deleteChat: vi.fn(async () => undefined),
    getMessage: vi.fn(async () => null),
    saveMessage: vi.fn(async () => undefined),
    updateChat: vi.fn(async () => undefined),
    deleteMessage: vi.fn(async () => undefined),
  };
  const chatSyncService = {
    dispatchEvent: vi.fn(),
    getActiveAITaskIdForChat: vi.fn(() => null),
    sendSetActiveChat: vi.fn(async () => undefined),
    sendNewMessage: vi.fn(),
    sendDeleteMessage: vi.fn(async () => undefined),
  };
  return {
    store,
    authState,
    wsStatus,
    teamContext,
    draftState,
    chatRecord,
    chatDB,
    chatSyncService,
    getTracer: vi.fn(() => ({ startSpan: vi.fn(() => span) })),
    hasActualContent: vi.fn(() => true),
    sendTextMessage: vi.fn(),
    clearCurrentDraft: vi.fn(async () => undefined),
    embedStorePut: vi.fn(async () => undefined),
    refreshAnonymousFreeUsageStatus: vi.fn(async () => ({ active: true, can_send_text: true })),
    tipTapToCanonicalMarkdown: vi.fn((_content: unknown) => 'Send these attachments'),
    createEmbedFromUrl: vi.fn(),
    consumeClickedSuggestion: vi.fn(() => null),
    extractProjectFocusSendIntent: vi.fn(() => null),
    wrapTeamChatKey: vi.fn(async () => 'team-wrapped-key'),
    isTeamAIInvocation: vi.fn(() => false),
  };
});

vi.mock('../../../services/sendersChatMessages', () => ({ isPreflightAcknowledgementTimeout: vi.fn(() => false) }));
vi.mock('../services/urlMetadataService', () => ({ createEmbedFromUrl: mocks.createEmbedFromUrl }));
vi.mock('../../../stores/demoModeStore', () => ({ demoMode: mocks.store(false) }));
vi.mock('../../../i18n/translations', () => ({ text: mocks.store((key: string) => key) }));
vi.mock('../../../demo_chats/convertToChat', () => ({ isPublicChat: vi.fn(() => false) }));
vi.mock('../../../services/tracing/setup', () => ({ getTracer: mocks.getTracer }));
vi.mock('@tiptap/core', () => ({ Extension: { create: vi.fn() } }));
vi.mock('../../../services/db', () => ({ chatDB: mocks.chatDB }));
vi.mock('../../../services/encryption/ChatKeyManager', () => ({ chatKeyManager: { getKeySync: vi.fn(() => 'local-key'), createKeyForNewChat: vi.fn(() => 'local-key') } }));
vi.mock('../../../services/chatSyncService', () => ({ chatSyncService: mocks.chatSyncService }));
vi.mock('../../../services/chatListCache', () => ({ chatListCache: { setLastMessage: vi.fn(), removeChat: vi.fn() } }));
vi.mock('../../../stores/websocketStatusStore', () => ({ websocketStatus: mocks.store(mocks.wsStatus) }));
vi.mock('../utils', () => ({ hasActualContent: mocks.hasActualContent, vibrateMessageField: vi.fn() }));
vi.mock('../../../services/drafts/draftState', () => ({ draftEditorUIState: { subscribe(run: (state: typeof mocks.draftState) => void) { run(mocks.draftState); return () => undefined; }, update: vi.fn() } }));
vi.mock('../../../services/drafts/draftSave', () => ({ clearCurrentDraft: mocks.clearCurrentDraft, saveDraftDebounced: { cancel: vi.fn() } }));
vi.mock('../../../services/embedStore', () => ({ embedStore: { put: mocks.embedStorePut, registerEmbedRef: vi.fn() } }));
vi.mock('../../../message_parsing/serializers', () => ({ tipTapToCanonicalMarkdown: mocks.tipTapToCanonicalMarkdown }));
vi.mock('../../../services/anonymousChatStorage', () => ({
  AnonymousFreeUsageExhaustedError: class AnonymousFreeUsageExhaustedError extends Error {},
  anonymousChatStorage: { sendTextMessage: mocks.sendTextMessage },
}));
vi.mock('../../../stores/serverStatusStore', () => ({ refreshAnonymousFreeUsageStatus: mocks.refreshAnonymousFreeUsageStatus }));
vi.mock('../../../stores/authStore', () => ({ authStore: { subscribe(run: (state: typeof mocks.authState) => void) { run(mocks.authState); return () => undefined; } } }));
vi.mock('../../../stores/userProfile', () => ({ userProfile: mocks.store({ username: 'Alice', user_id: 'alice-id' }) }));
vi.mock('../../../stores/signupState', () => ({ forcedLogoutInProgress: mocks.store(false) }));
vi.mock('../../../stores/appSettingsMemoriesPermissionStore', () => ({ appSettingsMemoriesPermissionStore: { getCurrentRequestId: vi.fn(() => null), getCurrentChatId: vi.fn(() => null) } }));
vi.mock('../../../stores/editMessageStore', () => ({ editMessageStore: mocks.store(null), cancelEdit: vi.fn() }));
vi.mock('../../../stores/notificationStore', () => ({ notificationStore: { error: vi.fn(), addNotificationWithOptions: vi.fn() } }));
vi.mock('../../../stores/personalDataStore', () => ({ personalDataStore: { settings: mocks.store({ masterEnabled: false, categories: {} }), enabledEntries: mocks.store([]) } }));
vi.mock('../services/piiDetectionService', () => ({ detectPII: vi.fn(() => []), replacePIIWithPlaceholders: vi.fn(), createPIIMappingsForStorage: vi.fn(() => []) }));
vi.mock('../services/placeholderRewriteService', () => ({ rewriteKnownPIIPlaceholders: vi.fn() }));
vi.mock('../../../stores/embedPIIStore', () => ({ getActivePIIMappingsForRewrite: vi.fn(() => []) }));
vi.mock('../../../stores/teamStore', () => ({
  activeTeamId: mocks.store(null),
  getActiveTeamContextSnapshot: () => ({ ...mocks.teamContext }),
  isActiveTeamContext: (teamId: string | null, epoch: number) =>
    mocks.teamContext.teamId === teamId && mocks.teamContext.epoch === epoch,
}));
vi.mock('../../../services/teamService', () => ({ isTeamAIInvocation: mocks.isTeamAIInvocation, wrapTeamChatKey: mocks.wrapTeamChatKey }));
vi.mock('../../../services/cryptoService', () => ({ encryptWithChatKey: vi.fn() }));
vi.mock('../../../stores/incognitoModeStore', () => ({ incognitoMode: { get: vi.fn(() => false) } }));
vi.mock('../../../services/incognitoChatService', () => ({ incognitoChatService: { getChat: vi.fn(async () => null) } }));
vi.mock('../../../stores/suggestionTracker', () => ({ consumeClickedSuggestion: mocks.consumeClickedSuggestion }));
vi.mock('../../../services/projectFocusSendPreflight', () => ({
  extractProjectFocusSendIntent: mocks.extractProjectFocusSendIntent,
  ProjectFocusSendPreflightError: class ProjectFocusSendPreflightError extends Error {},
}));

import { executeDeferredSend, handleSend } from './sendHandlers';
import { pendingUploadStore, removePendingSend } from '../../../stores/pendingUploadStore';

function makeEditor(includeEmbeds = true) {
  const document = {
    type: 'doc',
    content: [
      { type: 'paragraph', content: [{ type: 'text', text: 'Send these attachments' }] },
      { type: 'embed', attrs: { id: 'image-1', type: 'image', status: 'finished', contentRef: 'embed:image-1' } },
      { type: 'embed', attrs: { id: 'audio-1', type: 'recording', status: 'finished', contentRef: 'embed:audio-1' } },
    ],
  };
  if (!includeEmbeds) document.content.splice(1);
  const clearContent = vi.fn(() => {
    document.content = [] as typeof document.content;
    editor.state.doc = { ...document };
  });
  const setContent = vi.fn((content: typeof document) => {
    document.content = structuredClone(content.content);
    editor.state.doc = { ...document };
  });
  const blur = vi.fn();
  const editor = {
    isDestroyed: false,
    isEmpty: false,
    state: { doc: document },
    getText: vi.fn(() => 'Send these attachments'),
    getJSON: vi.fn(() => structuredClone(document)),
    view: { state: { doc: { descendants(callback: (node: { type: { name: string }; attrs: Record<string, unknown> }) => boolean): void {
      for (const item of document.content) {
        if (item.type === 'embed' && 'attrs' in item) {
          callback({ type: { name: 'embed' }, attrs: item.attrs });
        }
      }
    } } } },
    commands: { clearContent, setContent, blur, focus: vi.fn() },
  };
  return { editor: editor as unknown as Editor, document, clearContent, setContent, blur };
}

function makeUploadedImageEditor(contentRef: string | null = null) {
  type Node = { type: string; attrs?: Record<string, unknown>; content?: Array<{ type: string; text: string }> };
  type Document = { type: string; content: Node[] };
  const initialDocument: Document = { type: 'doc', content: [
    { type: 'paragraph', content: [{ type: 'text', text: 'Team photo' }] },
    { type: 'embed', attrs: { id: 'local-image', type: 'image', status: 'finished', uploadEmbedId: 'uploaded-image', contentRef } },
  ] };
  const state = { doc: initialDocument };
  const clearContent = vi.fn(() => { state.doc = { type: 'doc', content: [] }; });
  const setContent = vi.fn((content: Document) => { state.doc = structuredClone(content); });
  const blur = vi.fn();
  const editor = {
    isDestroyed: false, isEmpty: false, state,
    getText: vi.fn(() => 'Team photo'),
    getJSON: vi.fn(() => structuredClone(state.doc)),
    commands: { clearContent, setContent, blur, focus: vi.fn() },
  };
  const editDocument = () => {
    state.doc = { type: 'doc', content: [
      { type: 'paragraph', content: [{ type: 'text', text: 'New thought while sending' }] },
    ] };
  };
  return { editor: editor as unknown as Editor, state, clearContent, blur, editDocument };
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
  it('clears when anonymous storage accepts a pending row', async () => {
    mocks.sendTextMessage.mockImplementation(async ({ onPending }: { onPending: (pending: unknown) => Promise<void> }) => {
      await onPending({ userMessage: { message_id: 'anonymous-1', chat_id: 'anonymous-chat', content: 'Send these attachments', status: 'sending' }, isNewChat: false });
    });
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
    mocks.wsStatus.status = 'connected';
    mocks.chatDB.ensureReadyForSend.mockResolvedValue(undefined);
    mocks.draftState.currentChatId = 'chat-auth';
    mocks.chatRecord.team_id = null;
    mocks.teamContext.teamId = null;
    mocks.teamContext.epoch = 0;
    mocks.isTeamAIInvocation.mockReturnValue(false);
    mocks.tipTapToCanonicalMarkdown.mockReturnValue('Send these attachments');
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it('shows a text submission and clears the field while URL metadata is still pending', async () => {
    let releaseUrl!: (value: null) => void;
    mocks.tipTapToCanonicalMarkdown.mockReturnValue('Look at https://example.com');
    mocks.createEmbedFromUrl.mockImplementation(() => new Promise((resolve) => { releaseUrl = resolve; }));
    mocks.chatSyncService.sendNewMessage.mockResolvedValue(undefined);
    const { editor, clearContent } = makeEditor(false);
    const dispatch = vi.fn();

    const result = handleSend(editor, dispatch, vi.fn(), 'chat-auth');
    expect(dispatch).toHaveBeenCalledWith('sendMessage', expect.objectContaining({
      message: expect.objectContaining({ content: 'Look at https://example.com', status: 'sending' }),
    }));
    expect(clearContent).toHaveBeenCalledWith(false);
    expect(mocks.chatDB.saveMessage).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(releaseUrl).toBeDefined());
    expect(mocks.chatDB.saveMessage).not.toHaveBeenCalled();
    releaseUrl(null);
    expect(await result).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership,teams.context.full-switch-local
  it('removes an early row if the Team changes during local readiness', async () => {
    let releaseReady!: () => void;
    mocks.teamContext.teamId = 'team-one';
    mocks.chatDB.ensureReadyForSend.mockImplementationOnce(() => new Promise<void>((resolve) => { releaseReady = resolve; }));
    const { editor, document, clearContent, setContent } = makeEditor(false);
    const dispatch = vi.fn();

    const pending = handleSend(editor, dispatch, vi.fn(), 'chat-auth');
    expect(dispatch).toHaveBeenCalledWith('sendMessage', expect.anything());
    expect(clearContent).toHaveBeenCalledWith(false);
    mocks.teamContext.teamId = null;
    mocks.teamContext.epoch++;
    await vi.waitFor(() => expect(releaseReady).toBeDefined());
    releaseReady();
    expect(await pending).toBeUndefined();
    expect(dispatch).toHaveBeenCalledWith('sendMessageRejected', expect.anything());
    expect(setContent).not.toHaveBeenCalled();
    expect(document.content).toEqual([]);
    expect(mocks.chatDB.saveMessage).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it('restores the untouched snapshot if local storage rejects the early row', async () => {
    mocks.chatDB.ensureReadyForSend.mockRejectedValueOnce(new Error('storage unavailable'));
    const { editor, document, setContent } = makeEditor(false);
    const original = structuredClone(document);
    const dispatch = vi.fn();

    expect(await handleSend(editor, dispatch, vi.fn(), 'chat-auth')).toBe(false);
    expect(document).toEqual(original);
    expect(setContent).toHaveBeenCalledWith(original);
    expect(dispatch).toHaveBeenCalledWith('sendMessageRejected', expect.anything());
    expect(mocks.chatDB.saveMessage).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it('keeps the same durable waiting row when offline sending is queued', async () => {
    mocks.wsStatus.status = 'disconnected';
    mocks.chatSyncService.sendNewMessage.mockResolvedValue(undefined);
    const { editor, document, setContent } = makeEditor(false);
    const dispatch = vi.fn();

    expect(await handleSend(editor, dispatch, vi.fn(), 'chat-auth')).toBe(true);
    const optimistic = dispatch.mock.calls.find(([type]) => type === 'sendMessage')?.[1]?.message;
    expect(optimistic).toMatchObject({ status: 'waiting_for_internet', content: 'Send these attachments' });
    expect(mocks.chatDB.saveMessage).toHaveBeenCalledWith(expect.objectContaining({ message_id: optimistic.message_id }));
    expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledWith(
      expect.objectContaining({ message_id: optimistic.message_id }), null, undefined, undefined, false,
    );
    expect(document.content).toEqual([]);
    expect(setContent).not.toHaveBeenCalled();
    expect(dispatch).not.toHaveBeenCalledWith('sendMessageRejected', expect.anything());
  });

  // contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked,message-input.send.ownership
  it('carries new Team chat provenance through an upload-delayed first AI invocation', async () => {
    mocks.teamContext.teamId = 'team-one';
    mocks.isTeamAIInvocation.mockReturnValue(true);
    mocks.tipTapToCanonicalMarkdown.mockReturnValue('@OpenMates summarize');
    mocks.draftState.currentChatId = null;
    mocks.chatDB.getChat.mockResolvedValueOnce(null);
    mocks.chatSyncService.sendNewMessage.mockResolvedValue(undefined);
    const { editor, document } = makeEditor();
    (document.content[1] as { attrs: Record<string, unknown> }).attrs.status = 'uploading';
    (document.content[1] as { attrs: Record<string, unknown> }).attrs.contentRef = null;
    const dispatch = vi.fn();

    expect(await handleSend(editor, dispatch, vi.fn())).toBe(true);
    const queued = [...get(pendingUploadStore).values()].flat();
    expect(queued).toHaveLength(1);
    const context = queued[0];
    expect(context.newLocalChat).toBe(true);
    expect(mocks.chatSyncService.sendNewMessage).not.toHaveBeenCalled();

    try {
      await executeDeferredSend(context);
      expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledWith(
        expect.objectContaining({ chat_id: context.chatId, message_id: context.messageId,
          content: '@OpenMates summarize' }),
        undefined, undefined, undefined, true,
      );
    } finally {
      removePendingSend(context.chatId, context.pendingId);
    }
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it('moves the submitted image and audio snapshot before sendNewMessage settles', async () => {
    let accept!: () => void;
    mocks.chatSyncService.sendNewMessage.mockImplementation(() => new Promise<void>((resolve) => { accept = resolve; }));
    const { editor, document, clearContent, blur } = makeEditor();
    const setHasContent = vi.fn();
    const dispatch = vi.fn();

    const result = handleSend(editor, dispatch, setHasContent, 'chat-auth');
    await vi.waitFor(() => expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledTimes(1));
    expect(document.content).toEqual([]);
    expect(clearContent).toHaveBeenCalledWith(false);
    expect(blur).toHaveBeenCalledOnce();
    expect(setHasContent).toHaveBeenCalledWith(false);
    expect(dispatch).toHaveBeenCalledWith('sendMessage', expect.objectContaining({
      message: expect.objectContaining({ status: 'sending', content: 'Send these attachments' }),
    }));

    accept();
    await result;
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it('restores complete editor JSON when sendNewMessage rejects', async () => {
    mocks.chatSyncService.sendNewMessage.mockRejectedValue(new Error('synthetic transport failure'));
    const { editor, document, clearContent, setContent } = makeEditor();
    const original = structuredClone(document);
    const setHasContent = vi.fn();
    const dispatch = vi.fn();

    const result = await handleSend(editor, dispatch, setHasContent, 'chat-auth');

    expect(result).toBeUndefined();
    expect(document).toEqual(original);
    expect(clearContent).toHaveBeenCalledWith(false);
    expect(setContent).toHaveBeenCalledWith(original);
    expect(setHasContent).toHaveBeenCalledWith(true);
    expect(dispatch).toHaveBeenCalledWith('sendMessageRejected', expect.anything());
    expect(mocks.chatDB.deleteMessage).toHaveBeenCalledWith(expect.any(String));
    expect(mocks.clearCurrentDraft).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it('does not replace a newer draft when the previous transport rejects', async () => {
    let rejectSend!: (error: Error) => void;
    mocks.chatSyncService.sendNewMessage.mockImplementation(() => new Promise<void>((_, reject) => { rejectSend = reject; }));
    const { editor, document, setContent } = makeEditor(false);
    const dispatch = vi.fn();

    const pending = handleSend(editor, dispatch, vi.fn(), 'chat-auth');
    await vi.waitFor(() => expect(rejectSend).toBeDefined());
    document.content.push({ type: 'paragraph', content: [{ type: 'text', text: 'New draft' }] });
    (editor as unknown as { state: { doc: unknown } }).state.doc = structuredClone(document);
    rejectSend(new Error('transport unavailable'));
    expect(await pending).toBeUndefined();
    expect(document.content).toContainEqual({ type: 'paragraph', content: [{ type: 'text', text: 'New draft' }] });
    expect(setContent).not.toHaveBeenCalled();
    expect(dispatch).toHaveBeenCalledWith('sendMessageRejected', expect.anything());
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it('clears and blurs before sendNewMessage accepts the unchanged document', async () => {
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
  it('shows the canonical uploaded image reference before Team registration finishes', async () => {
    let finishRegistration!: () => void;
    mocks.teamContext.teamId = 'team-one';
    mocks.chatRecord.team_id = 'team-one';
    mocks.embedStorePut.mockImplementationOnce(() => new Promise<void>((resolve) => { finishRegistration = resolve; }));
    mocks.chatSyncService.sendNewMessage.mockResolvedValue(undefined);
    mocks.tipTapToCanonicalMarkdown.mockImplementation((content) =>
      String((content as { content: Array<{ attrs?: Record<string, unknown> }> }).content[1].attrs?.contentRef));
    const { editor, state, clearContent } = makeUploadedImageEditor();
    const dispatch = vi.fn();

    const pending = handleSend(editor, dispatch, vi.fn(), 'chat-auth');
    expect(dispatch).toHaveBeenCalledWith('sendMessage', expect.objectContaining({
      message: expect.objectContaining({ content: 'embed:uploaded-image', status: 'sending' }),
    }));
    expect(clearContent).toHaveBeenCalledWith(false);
    expect(state.doc.content).toEqual([]);
    await vi.waitFor(() => expect(finishRegistration).toBeDefined());
    finishRegistration();
    expect(await pending).toBe(true);
    expect(mocks.embedStorePut).toHaveBeenCalledOnce();
    expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledWith(
      expect.objectContaining({ content: 'embed:uploaded-image' }),
      null, undefined, undefined, false,
    );
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it('keeps an existing uploaded image reference without a second rewrite', async () => {
    mocks.chatSyncService.sendNewMessage.mockResolvedValue(undefined);
    mocks.tipTapToCanonicalMarkdown.mockImplementation((content) =>
      String((content as { content: Array<{ attrs?: Record<string, unknown> }> }).content[1].attrs?.contentRef));
    const { editor, state } = makeUploadedImageEditor('embed:uploaded-image');
    const dispatch = vi.fn();

    expect(await handleSend(editor, dispatch, vi.fn(), 'chat-auth')).toBe(true);
    expect(mocks.tipTapToCanonicalMarkdown.mock.calls.every(([content]) =>
      (content as { content: Array<{ attrs?: Record<string, unknown> }> }).content[1].attrs?.contentRef === 'embed:uploaded-image')).toBe(true);
    expect(mocks.embedStorePut).toHaveBeenCalledOnce();
    expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledWith(
      expect.objectContaining({ content: 'embed:uploaded-image' }),
      null, undefined, undefined, false,
    );
    expect(state.doc.content).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it('keeps a newer draft typed while uploaded image registration is pending', async () => {
    let finishRegistration!: () => void;
    mocks.embedStorePut.mockImplementationOnce(() => new Promise<void>((resolve) => { finishRegistration = resolve; }));
    mocks.chatSyncService.sendNewMessage.mockResolvedValue(undefined);
    mocks.tipTapToCanonicalMarkdown.mockImplementation((content) =>
      (content as { content: Array<{ content?: Array<{ text: string }> }> }).content
        .map((node) => node.content?.map((part) => part.text).join('') ?? '').join(''));
    const { editor, state, clearContent, editDocument } = makeUploadedImageEditor();
    const pending = handleSend(editor, vi.fn(), vi.fn(), 'chat-auth');
    expect(clearContent).toHaveBeenCalledWith(false);
    await vi.waitFor(() => expect(finishRegistration).toBeDefined());
    editDocument();
    finishRegistration();

    expect(await pending).toBe(true);
    expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledWith(
      expect.objectContaining({ content: 'Team photo' }),
      null, undefined, undefined, false,
    );
    expect(state.doc.content[0]?.content?.[0].text).toBe('New thought while sending');
    expect(clearContent).toHaveBeenCalledOnce();
    expect(mocks.clearCurrentDraft).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  it('keeps a new draft typed while transport is pending after acceptance', async () => {
    let accept!: () => void;
    mocks.chatSyncService.sendNewMessage.mockImplementation(() => new Promise<void>((resolve) => { accept = resolve; }));
    const { editor, document, clearContent, blur } = makeEditor();
    const setHasContent = vi.fn();

    const result = handleSend(editor, vi.fn(), setHasContent, 'chat-auth');
    await vi.waitFor(() => expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledTimes(1));
    document.content.push({ type: 'paragraph', content: [{ type: 'text', text: 'New thought while sending' }] });
    (editor as unknown as { state: { doc: unknown } }).state.doc = structuredClone(document);
    const editedDocument = structuredClone(document);
    accept();
    expect(await result).toBe(true);

    expect(document).toEqual(editedDocument);
    expect(clearContent).toHaveBeenCalledWith(false);
    expect(blur).toHaveBeenCalledOnce();
    expect(setHasContent).toHaveBeenCalledWith(false);
    expect(mocks.clearCurrentDraft).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=teams.chat.sender-identity-layout
  it('keeps the real Team member name for encrypted sender attribution', async () => {
    mocks.teamContext.teamId = 'team-one';
    mocks.chatRecord.team_id = 'team-one';
    mocks.chatSyncService.sendNewMessage.mockResolvedValue(undefined);
    vi.spyOn(crypto.subtle, 'digest').mockResolvedValue(
      Uint8Array.from(createHash('sha256').update('alice-id').digest()).buffer,
    );
    const dispatch = vi.fn();
    const { editor } = makeEditor();

    expect(await handleSend(editor, dispatch, vi.fn(), 'chat-auth')).toBe(true);
    expect(dispatch).toHaveBeenCalledWith('sendMessagePrepared', expect.objectContaining({
      message: expect.objectContaining({
        sender_name: 'Alice',
        hashed_user_id: createHash('sha256').update('alice-id').digest('hex'),
      }),
    }));
  });

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local
  it('drops a send when the Team context switches during chat classification', async () => {
    mocks.teamContext.teamId = 'team-one';
    let releaseLookup!: () => void;
    mocks.chatDB.getTransaction.mockImplementationOnce(() => new Promise((resolve) => {
      releaseLookup = () => resolve({ objectStore: () => ({ get: () => {
        const request: { result: unknown; onsuccess?: () => void } = {
          result: { chat_id: 'chat-auth', team_id: 'team-one', messages_v: 3, encrypted_chat_key: 'wrapped-key' },
        };
        queueMicrotask(() => request.onsuccess?.());
        return request;
      } }) });
    }));
    const { editor, document, clearContent } = makeEditor();
    const original = structuredClone(document);
    const dispatch = vi.fn();
    const pending = handleSend(editor, dispatch, vi.fn(), 'chat-auth');
    await vi.waitFor(() => expect(releaseLookup).toBeDefined());
    mocks.teamContext.teamId = null;
    mocks.teamContext.epoch++;
    releaseLookup();

    expect(await pending).toBeUndefined();
    expect(mocks.chatDB.saveMessage).not.toHaveBeenCalled();
    expect(mocks.chatSyncService.sendNewMessage).not.toHaveBeenCalled();
    expect(dispatch).toHaveBeenCalledWith('sendMessageRejected', expect.anything());
    expect(document).toEqual({ ...original, content: [] });
    expect(clearContent).toHaveBeenCalledWith(false);
  });

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local
  it('does not create a Team chat after switching to Personal while wrapping its key', async () => {
    mocks.teamContext.teamId = 'team-one';
    mocks.draftState.currentChatId = null;
    mocks.chatDB.getTransaction.mockImplementationOnce(async () => ({ objectStore: () => ({ get: () => {
      const request: { result: null; onsuccess?: () => void } = { result: null };
      queueMicrotask(() => request.onsuccess?.());
      return request;
    } }) }));
    let releaseWrap!: (value: string) => void;
    mocks.wrapTeamChatKey.mockImplementationOnce(() => new Promise((resolve) => { releaseWrap = resolve; }));
    const { editor, document, clearContent } = makeEditor();
    const original = structuredClone(document);
    const dispatch = vi.fn();
    const pending = handleSend(editor, dispatch, vi.fn());
    await vi.waitFor(() => expect(releaseWrap).toBeDefined());
    mocks.teamContext.teamId = null;
    mocks.teamContext.epoch++;
    releaseWrap('team-wrapped-key');

    expect(await pending).toBeUndefined();
    expect(mocks.chatDB.saveMessage).not.toHaveBeenCalled();
    expect(mocks.chatSyncService.sendNewMessage).not.toHaveBeenCalled();
    expect(dispatch).toHaveBeenCalledWith('sendMessageRejected', expect.anything());
    expect(document).toEqual({ ...original, content: [] });
    expect(clearContent).toHaveBeenCalledWith(false);
  });
});
