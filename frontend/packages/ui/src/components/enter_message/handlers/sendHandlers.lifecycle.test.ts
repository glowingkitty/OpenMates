vi.mock("../../../services/voiceCall", () => ({ voiceCallController: mocks.store({ status: "idle" }) }));
vi.mock("../../../services/preparedPrivacyForSend", () => ({ registerPersonalPrivacyExclusions: vi.fn() }));
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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
    beginEmptyConnectedAccountLookup: vi.fn(async () => null),
    sendDeleteMessage: vi.fn(async () => undefined),
  };
  return {
    store,
    authState,
    profileState: { username: 'Alice', user_id: 'alice-id' },
    wsStatus,
    teamContext,
    draftState,
    chatRecord,
    chatDB,
    chatSyncService,
    getTracer: vi.fn(() => ({ startSpan: vi.fn(() => span) })),
    hasActualContent: vi.fn(() => true),
    sendTextMessage: vi.fn(),
    markAnonymousFreeUsageExhausted: vi.fn(),
    notify: vi.fn((_type?: unknown, _options?: unknown) => 'pending-notification-id'),
    notifyError: vi.fn((_message?: string) => 'privacy-error-notification-id'),
    updateNotification: vi.fn(),
    cancelNotificationAutoDismiss: vi.fn(),
    removeNotification: vi.fn(),
    resetWebPIIDetector: vi.fn(),
    scanGate: vi.fn(async () => undefined),
    webPIIEnabled: vi.fn(() => false),
    clearCurrentDraft: vi.fn(async () => undefined),
    embedStorePut: vi.fn(async (_key: string, _value: unknown, _type?: string) => undefined),
    embedStoreGet: vi.fn(async (_key?: string): Promise<Record<string, unknown> | undefined> => undefined),
    refreshAnonymousFreeUsageStatus: vi.fn(async () => ({ active: true, can_send_text: true })),
    tipTapToCanonicalMarkdown: vi.fn((_content: unknown) => 'Send these attachments'),
    createEmbedFromUrl: vi.fn(),
    privacySettings: { masterEnabled: false, categories: {} },
    getActivePIIMappingsForRewrite: vi.fn((): Array<{ placeholder: string; original: string; type: string }> => []),
    consumeClickedSuggestion: vi.fn(() => null),
    extractProjectFocusSendIntent: vi.fn(() => null),
    beginFreshProjectRoutingForSend: vi.fn(),
    forgetFreshProjectRoutingForSend: vi.fn(),
    recordSendPreparationPhase: vi.fn(),
    wrapTeamChatKey: vi.fn(async () => 'team-wrapped-key'),
    isTeamAIInvocation: vi.fn(() => false),
  };
});

vi.mock('../../../services/sendersChatMessages', () => ({ isPreflightAcknowledgementTimeout: vi.fn(() => false) }));
vi.mock('../../../services/earlyProjectRoutingForSend', () => ({
  beginFreshProjectRoutingForSend: mocks.beginFreshProjectRoutingForSend,
  forgetFreshProjectRoutingForSend: mocks.forgetFreshProjectRoutingForSend,
}));
vi.mock('../services/urlMetadataService', () => ({ createEmbedFromUrl: mocks.createEmbedFromUrl }));
vi.mock('../../../stores/demoModeStore', () => ({ demoMode: mocks.store(false) }));
vi.mock('../../../i18n/translations', () => ({ text: mocks.store((key: string) => key) }));
vi.mock('../../../demo_chats/convertToChat', () => ({ isPublicChat: vi.fn(() => false) }));
vi.mock('../../../services/tracing/setup', () => ({ getTracer: mocks.getTracer }));
vi.mock('@tiptap/core', () => ({ Extension: { create: vi.fn() } }));
vi.mock('../../../services/db', () => ({ chatDB: mocks.chatDB }));
vi.mock('../../../services/encryption/ChatKeyManager', () => ({ chatKeyManager: { getKeySync: vi.fn(() => 'local-key'), createKeyForNewChat: vi.fn(() => 'local-key') } }));
vi.mock('../../../services/chatSyncService', () => ({
  chatSyncService: mocks.chatSyncService,
  recordSendPreparationPhase: mocks.recordSendPreparationPhase,
}));
vi.mock('../../../services/chatListCache', () => ({ chatListCache: { setLastMessage: vi.fn(), removeChat: vi.fn() } }));
vi.mock('../../../stores/websocketStatusStore', () => ({ websocketStatus: mocks.store(mocks.wsStatus) }));
vi.mock('../utils', () => ({ hasActualContent: mocks.hasActualContent, vibrateMessageField: vi.fn() }));
vi.mock('../../../services/drafts/draftState', () => ({ draftEditorUIState: { subscribe(run: (state: typeof mocks.draftState) => void) { run(mocks.draftState); return () => undefined; }, update: vi.fn() } }));
vi.mock('../../../services/drafts/draftSave', () => ({ clearCurrentDraft: mocks.clearCurrentDraft, saveDraftDebounced: { cancel: vi.fn() } }));
vi.mock('../../../services/embedStore', () => ({ embedStore: { put: mocks.embedStorePut, get: mocks.embedStoreGet, registerEmbedRef: vi.fn() } }));
vi.mock('../../../message_parsing/serializers', () => ({ tipTapToCanonicalMarkdown: mocks.tipTapToCanonicalMarkdown }));
vi.mock('../../../services/anonymousChatStorage', () => ({
  AnonymousFreeUsageExhaustedError: class AnonymousFreeUsageExhaustedError extends Error {},
  anonymousChatStorage: { sendTextMessage: mocks.sendTextMessage },
}));
vi.mock('../../../stores/serverStatusStore', () => ({ refreshAnonymousFreeUsageStatus: mocks.refreshAnonymousFreeUsageStatus, markAnonymousFreeUsageExhausted: mocks.markAnonymousFreeUsageExhausted }));
vi.mock('../../../stores/authStore', () => ({ authStore: { subscribe(run: (state: typeof mocks.authState) => void) { run(mocks.authState); return () => undefined; } } }));
vi.mock('../../../stores/userProfile', () => ({ userProfile: mocks.store(mocks.profileState) }));
vi.mock('../../../stores/signupState', () => ({ forcedLogoutInProgress: mocks.store(false) }));
vi.mock('../../../stores/appSettingsMemoriesPermissionStore', () => ({ appSettingsMemoriesPermissionStore: { getCurrentRequestId: vi.fn(() => null), getCurrentChatId: vi.fn(() => null) } }));
vi.mock('../../../stores/editMessageStore', () => ({ editMessageStore: mocks.store(null), cancelEdit: vi.fn() }));
vi.mock('../../../stores/incognitoModeStore', () => ({ incognitoMode: { get: vi.fn(() => false) } }));
vi.mock('../../../stores/notificationStore', () => ({ notificationStore: { error: mocks.notifyError, addNotificationWithOptions: mocks.notify, updateNotification: mocks.updateNotification, cancelAutoDismiss: mocks.cancelNotificationAutoDismiss, removeNotification: mocks.removeNotification } }));
vi.mock('../../../stores/personalDataStore', () => ({ personalDataStore: { settings: mocks.store(mocks.privacySettings), enabledEntries: mocks.store([]) } }));
vi.mock('../services/piiDetectionService', async (importOriginal) => ({
  ...await importOriginal<typeof import('../services/piiDetectionService')>(),
  detectPII: vi.fn(() => []), replacePIIWithPlaceholders: vi.fn(), createPIIMappingsForStorage: vi.fn(() => []),
}));
vi.mock('../services/webPIIDetectionService', () => ({
  createWebPIIScanContext: () => ({ purpose: 'send' as const }),
  isWebPIIModelEnabled: mocks.webPIIEnabled,
  resetWebPIIDetector: mocks.resetWebPIIDetector,
  detectPIIForWeb: vi.fn(async (value: string, options: unknown) => {
    // A rejection represents a facade failure after both model and regex protection fail.
    await mocks.scanGate();
    const { detectPII } = await import('../services/piiDetectionService');
    return detectPII(value, options as never);
  }),
}));
vi.mock('../services/placeholderRewriteService', () => ({ rewriteKnownPIIPlaceholders: vi.fn((markdown: string) => ({ markdown, appliedMappings: [] })) }));
vi.mock('../../../stores/embedPIIStore', () => ({ getActivePIIMappingsForRewrite: mocks.getActivePIIMappingsForRewrite }));
vi.mock('../../../stores/teamStore', () => ({
  activeTeamContext: mocks.store({ teamId: null, epoch: 0 }),
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

import { dispatchPendingSendWithPrivacyRetry, executeDeferredSend, handleSend, prepareQueuedMessageRevision, detectUrlsInText } from './sendHandlers';
import { addPendingSend, claimPendingSendPrivacy, getReadyPendingSend, markPendingSendPrivacyFailure, pendingUploadStore, removePendingSend } from '../../../stores/pendingUploadStore';

beforeEach(() => {
  mocks.webPIIEnabled.mockReturnValue(false);
  mocks.scanGate.mockImplementation(async () => undefined);
  mocks.getActivePIIMappingsForRewrite.mockReturnValue([]);
});

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
    view: { dom: { blur, contains: vi.fn(() => false) }, state: { doc: { descendants(callback: (node: { type: { name: string }; attrs: Record<string, unknown> }) => boolean): void {
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
    view: { dom: { blur, contains: vi.fn(() => false) } },
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

  // contract-test: supporting surface=gui.web assertions=billing.anonymous.hard-capped-provider-metering,message-input.privacy-context
  it('shows signup and disables guest send after a limit while retaining the accepted turn', async () => {
    mocks.sendTextMessage.mockResolvedValue({ rejectionReason: 'anonymous_usage_limit' });
    const { editor } = makeEditor(false);

    expect(await handleSend(editor, vi.fn(), vi.fn())).toBe(true);

    expect(mocks.markAnonymousFreeUsageExhausted).toHaveBeenCalledOnce();
    expect(mocks.notify).toHaveBeenCalledWith('warning', expect.objectContaining({
      message: 'chat.anonymous_free_usage.daily_credits_exhausted',
      actionLabel: 'signup.sign_up',
    }));
    expect(mocks.refreshAnonymousFreeUsageStatus).toHaveBeenCalledOnce();
    expect(mocks.chatDB.deleteChat).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=billing.anonymous.hard-capped-provider-metering,message-input.send.ownership
  it('applies a completed usage limit even if subsequent draft cleanup rejects', async () => {
    mocks.sendTextMessage.mockImplementation(async ({ onPending }: { onPending: (pending: unknown) => Promise<void> }) => {
      await onPending({ userMessage: { message_id: 'anonymous-1', chat_id: 'anonymous-chat' }, isNewChat: false });
      return { rejectionReason: 'anonymous_usage_limit' };
    });
    mocks.clearCurrentDraft.mockRejectedValueOnce(new Error('draft cleanup unavailable'));
    const { editor } = makeEditor(false);

    expect(await handleSend(editor, vi.fn(), vi.fn())).toBe(true);
    expect(mocks.clearCurrentDraft).toHaveBeenCalledOnce();
    expect(mocks.markAnonymousFreeUsageExhausted).toHaveBeenCalledOnce();
    expect(mocks.notify).toHaveBeenCalledOnce();
    expect(mocks.chatDB.deleteChat).not.toHaveBeenCalled();
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

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it('sends a followup when active-chat PII mappings contain reactive proxies', async () => {
    mocks.chatSyncService.sendNewMessage.mockResolvedValue(undefined);
    mocks.chatDB.getMessage.mockResolvedValue(null);
    const seed = makeEditor(false);
    expect(await handleSend(seed.editor, vi.fn(), vi.fn(), 'chat-auth')).toBe(true);
    const originalMapping = { placeholder: '[EMAIL_1_com]', original: 'owner@example.test', type: 'EMAIL' };
    const mapping = new Proxy({ ...originalMapping }, {});
    expect(() => structuredClone(mapping)).toThrow();
    mocks.getActivePIIMappingsForRewrite.mockReturnValue([mapping]);
    const followup = makeEditor(false);
    mocks.privacySettings.masterEnabled = true;
    try {
      expect(await handleSend(followup.editor, vi.fn(), vi.fn(), 'chat-auth')).toBe(true);
      expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledTimes(2);
      const { rewriteKnownPIIPlaceholders } = await import('../services/placeholderRewriteService');
      const snapshot = vi.mocked(rewriteKnownPIIPlaceholders).mock.calls.at(-1)![1].mappings;
      expect(structuredClone(snapshot)).toEqual([originalMapping]);
      mapping.original = 'newer@example.test';
      expect(snapshot).toEqual([originalMapping]);
    } finally {
      mocks.privacySettings.masterEnabled = false;
    }
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it('releases the send guard when synchronous privacy capture fails before pipeline setup', async () => {
    mocks.getActivePIIMappingsForRewrite.mockImplementationOnce(() => { throw new Error('snapshot unavailable'); });
    const rejected = makeEditor(false);
    await expect(handleSend(rejected.editor, vi.fn(), vi.fn(), 'chat-auth')).rejects.toThrow('snapshot unavailable');
    expect(rejected.clearContent).not.toHaveBeenCalled();
    expect(mocks.chatSyncService.sendNewMessage).not.toHaveBeenCalled();
    const retry = makeEditor(false);
    expect(await handleSend(retry.editor, vi.fn(), vi.fn(), 'chat-auth')).toBe(true);
    expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledOnce();
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it.each([
    ['transport', 'send_new_message_started'],
    ['admission read', 'send_admission_read_started'],
    ['draft cleanup', 'send_draft_cleanup_started'],
  ] as const)('retains the owning %s phase when rejecting duplicate sends', async (pendingOperation, phase) => {
    let release!: () => void;
    const pending = new Promise<void>((resolve) => { release = resolve; });
    mocks.chatSyncService.sendNewMessage.mockResolvedValue(undefined);
    mocks.chatDB.getMessage.mockResolvedValue(null);
    mocks.clearCurrentDraft.mockResolvedValue(undefined);
    if (pendingOperation === 'transport') mocks.chatSyncService.sendNewMessage.mockImplementationOnce(() => pending);
    if (pendingOperation === 'admission read') mocks.chatDB.getMessage.mockImplementationOnce(async () => { await pending; return null; });
    if (pendingOperation === 'draft cleanup') mocks.clearCurrentDraft.mockImplementationOnce(() => pending);
    const debugWindow = window as Window & {
      __openmatesLastSendDebug?: { step: string; timestamp: string; details: Record<string, unknown> };
    };
    const { editor } = makeEditor(false);
    const firstSend = handleSend(editor, vi.fn(), vi.fn(), 'chat-auth');
    try {
      const pendingMock = pendingOperation === 'transport' ? mocks.chatSyncService.sendNewMessage
        : pendingOperation === 'admission read' ? mocks.chatDB.getMessage : mocks.clearCurrentDraft;
      await vi.waitFor(() => expect(pendingMock).toHaveBeenCalledOnce());
      const duplicate = makeEditor(false);
      let phaseStartedAt: unknown;
      for (let attempt = 0; attempt < 2; attempt += 1) {
        await handleSend(duplicate.editor, vi.fn(), vi.fn(), 'chat-auth');
        if (attempt === 0) {
          phaseStartedAt = debugWindow.__openmatesLastSendDebug?.details.activeSendPhaseStartedAt;
          expect(phaseStartedAt).toEqual(expect.any(String));
        }
        expect(debugWindow.__openmatesLastSendDebug).toMatchObject({
          step: 'send_guard_rejected',
          details: { activeSendPhase: phase, activeSendPhaseStartedAt: phaseStartedAt },
        });
      }
      expect(duplicate.clearContent).not.toHaveBeenCalled();
      expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledOnce();
    } finally {
      release();
      await firstSend;
    }
    expect(debugWindow.__openmatesLastSendDebug?.step).toBe('send_guard_released');
    const next = makeEditor(false);
    expect(await handleSend(next.editor, vi.fn(), vi.fn(), 'chat-auth')).toBe(true);
    expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,drafts.persistence.local-first-encrypted
  it('restores an ordinary photo draft when the sender resolves with a failed message', async () => {
    mocks.chatDB.getMessage.mockResolvedValueOnce({ status: 'failed' } as never);
    const { editor, document } = makeEditor();
    const original = structuredClone(document);
    const result = await handleSend(editor, vi.fn(), vi.fn(), 'chat-auth');
    expect(result).toBe(false);
    expect(document).toEqual(original);
    expect(mocks.clearCurrentDraft).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.selection-after-acceptance,message-input.send.ownership
  it('begins one exact-message Project read before local DB readiness and discards it after failure', async () => {
    mocks.draftState.currentChatId = null;
    mocks.chatDB.ensureReadyForSend.mockRejectedValueOnce(new Error('storage unavailable'));
    const { editor } = makeEditor(false);
    const dispatch = vi.fn();
    expect(await handleSend(editor, dispatch, vi.fn())).toBe(false);
    expect(mocks.beginFreshProjectRoutingForSend).toHaveBeenCalledOnce();
    const input = mocks.beginFreshProjectRoutingForSend.mock.calls[0][0];
    expect(input.chatId).toBeTruthy();
    expect(input.messageId).toBeTruthy();
    expect(input.draftChatId).toBeNull();
    expect(mocks.forgetFreshProjectRoutingForSend).toHaveBeenCalledWith(input.messageId);
  });

  // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.selection-after-acceptance,message-input.send.ownership
  it('starts the fresh Project read for a preallocated or persisted draft-only first turn', async () => {
    mocks.chatDB.ensureReadyForSend.mockRejectedValueOnce(new Error('storage unavailable'));
    const { editor } = makeEditor(false);
    const dispatch = vi.fn();
    expect(await handleSend(editor, dispatch, vi.fn(), 'chat-auth', new Set(), false,
      () => false, undefined, undefined, { firstTurnContextAtClick: true })).toBe(false);
    expect(mocks.beginFreshProjectRoutingForSend).toHaveBeenCalledOnce();
    expect(mocks.recordSendPreparationPhase).toHaveBeenCalledWith('project_read_gate_eligible');
    const input = mocks.beginFreshProjectRoutingForSend.mock.calls[0][0];
    expect(input.chatId).toBe('chat-auth');
    expect(input.draftChatId).toBe('chat-auth');
    expect(mocks.forgetFreshProjectRoutingForSend).toHaveBeenCalledWith(input.messageId);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,teams.context.full-switch-local
  it('keeps saved chats, Team turns, and attachments outside click-time Project reading', async () => {
    for (const restricted of ['saved-chat', 'team', 'attachment'] as const) {
      vi.clearAllMocks();
      mocks.chatDB.ensureReadyForSend.mockRejectedValueOnce(new Error('storage unavailable'));
      mocks.teamContext.teamId = restricted === 'team' ? 'team-one' : null;
      const { editor } = makeEditor(restricted === 'attachment');
      await handleSend(editor, vi.fn(), vi.fn(), 'chat-auth', new Set(), false,
        () => false, undefined, undefined, { firstTurnContextAtClick: restricted !== 'saved-chat' });
      expect(mocks.beginFreshProjectRoutingForSend).not.toHaveBeenCalled();
      expect(mocks.recordSendPreparationPhase).toHaveBeenCalledWith(
        `project_read_gate_${restricted === 'saved-chat' ? 'not_first_turn' : restricted === 'team' ? 'team' : 'attachments'}`);
    }
    mocks.teamContext.teamId = null;
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
      expect.any(Promise),
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

    const setHasContent = vi.fn((value: boolean) => {
      if (!value) expect(state.doc.content).toEqual([]);
    });
    const pending = handleSend(editor, dispatch, setHasContent, 'chat-auth');
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
      null, undefined, undefined, false, expect.any(Promise),
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
      null, undefined, undefined, false, expect.any(Promise),
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
      null, undefined, undefined, false, expect.any(Promise),
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

// The real URL serializer is exercised while transport/storage remain bounded mocks.
describe('literal Apps result URL data', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.privacySettings.masterEnabled = false;
    mocks.authState.isAuthenticated = true;
    mocks.teamContext.teamId = null;
    mocks.teamContext.epoch = 0;
    mocks.chatRecord.team_id = null;
    mocks.draftState.currentChatId = 'chat-auth';
    mocks.chatDB.ensureReadyForSend.mockResolvedValue(undefined);
    mocks.chatSyncService.sendNewMessage.mockResolvedValue(undefined);
  });
  afterEach(() => { mocks.privacySettings.masterEnabled = false; });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('keeps context URL data literal without exempting its text from ordinary PII processing', async () => {
    const { appsWorkspaceContextOnlyUrls, appsRequestContextText } = await import('../../../services/appsWorkspaceChatHandoffService');
    const pii = await import('../services/piiDetectionService');
    const rewrite = await import('../services/placeholderRewriteService');
    const request = { text: 'Explain these appointments', context: { result: { practice_url: 'https://example.test/appointments/one', email: 'person@example.test' } } };
    const literal = appsRequestContextText(request);
    mocks.tipTapToCanonicalMarkdown.mockReturnValue(literal);
    mocks.privacySettings.masterEnabled = true;
    vi.mocked(rewrite.rewriteKnownPIIPlaceholders).mockReturnValue({ markdown: literal, appliedMappings: [] });
    vi.mocked(pii.detectPII).mockReturnValue([{ type: 'EMAIL', match: 'person@example.test', startIndex: literal.indexOf('person@'), endIndex: literal.indexOf('person@') + 19, placeholder: '[EMAIL_1]', id: 'email' }]);
    vi.mocked(pii.replacePIIWithPlaceholders).mockReturnValue(literal.replace('person@example.test', '[EMAIL_1]'));
    const prepared = await prepareQueuedMessageRevision({}, new Set(), appsWorkspaceContextOnlyUrls(request, detectUrlsInText));
    expect(mocks.createEmbedFromUrl).not.toHaveBeenCalled();
    expect(prepared.content).toContain('https://example.test/appointments/one');
    expect(prepared.content).not.toContain('person@example.test');
    expect(prepared.content).toContain('[EMAIL_1]');
    expect(pii.detectPII).toHaveBeenCalledWith(literal, expect.anything());
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('still processes an explicit request URL using the same normalized detector matches', async () => {
    const { appsWorkspaceContextOnlyUrls, appsRequestContextText } = await import('../../../services/appsWorkspaceChatHandoffService');
    const request = { text: 'Summarize youtu.be/abc', context: { result: { url: 'https://youtu.be/abc', practice_url: 'https://example.test/practice' } } };
    mocks.tipTapToCanonicalMarkdown.mockReturnValue(appsRequestContextText(request));
    mocks.createEmbedFromUrl.mockResolvedValue(null);
    await prepareQueuedMessageRevision({}, new Set(), appsWorkspaceContextOnlyUrls(request, detectUrlsInText));
    expect(mocks.createEmbedFromUrl.mock.calls.map(([url]) => url)).toEqual(['https://youtu.be/abc', 'https://youtu.be/abc']);
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('captures URL ignores before an optimistic clear or a rejected send mutates the caller set', async () => {
    const literal = 'Explain result {"practice_url":"https://example.test/practice"}';
    mocks.tipTapToCanonicalMarkdown.mockReturnValue(literal);
    mocks.chatDB.ensureReadyForSend.mockRejectedValueOnce(new Error('storage unavailable'));
    const ignored = new Set(['https://example.test/practice']);
    const { editor } = makeEditor(false);
    expect(await handleSend(editor, vi.fn(), vi.fn(), 'chat-auth', new Set(), false, () => false,
      undefined, undefined, { ignoredEmbedUrls: ignored })).toBe(false);
    mocks.chatDB.ensureReadyForSend.mockResolvedValue(undefined);
    const retry = handleSend(editor, vi.fn(), vi.fn(), 'chat-auth', new Set(), false, () => false,
      undefined, undefined, { ignoredEmbedUrls: ignored });
    ignored.clear();
    expect(await retry).toBe(true);
    expect(mocks.createEmbedFromUrl).not.toHaveBeenCalled();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('retains the exact ignored URL snapshot through an upload-delayed send', async () => {
    const literal = 'Explain result {"practice_url":"https://example.test/practice"}';
    mocks.tipTapToCanonicalMarkdown.mockReturnValue(literal);
    const { editor, document } = makeEditor();
    (document.content[1] as { attrs: Record<string, unknown> }).attrs.status = 'uploading';
    (document.content[1] as { attrs: Record<string, unknown> }).attrs.contentRef = null;
    const ignored = new Set(['https://example.test/practice']);
    expect(await handleSend(editor, vi.fn(), vi.fn(), 'chat-auth', new Set(), false, () => false,
      undefined, undefined, { ignoredEmbedUrls: ignored })).toBe(true);
    const context = [...get(pendingUploadStore).values()].flat().at(-1)!;
    try {
      expect(context.ignoredEmbedUrls).toEqual(['https://example.test/practice']);
      ignored.clear();
      await executeDeferredSend(context);
      expect(mocks.createEmbedFromUrl).not.toHaveBeenCalled();
      expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledWith(expect.objectContaining({ content: literal }), undefined, undefined, undefined, expect.anything());
    } finally { removePendingSend(context.chatId, context.pendingId); }
  });
});


describe('on-device send privacy preparation', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    mocks.webPIIEnabled.mockReturnValue(true);
    mocks.privacySettings.masterEnabled = true;
    mocks.authState.isAuthenticated = true;
    mocks.teamContext.teamId = null;
    mocks.teamContext.epoch = 0;
    mocks.chatRecord.team_id = null;
    mocks.profileState.user_id = 'alice-id';
    mocks.draftState.currentChatId = 'chat-auth';
    mocks.chatDB.ensureReadyForSend.mockResolvedValue(undefined);
    mocks.chatSyncService.sendNewMessage.mockResolvedValue(undefined);
    mocks.embedStoreGet.mockResolvedValue(undefined);
    mocks.tipTapToCanonicalMarkdown.mockReturnValue('Send these attachments');
    const pii = await import('../services/piiDetectionService');
    const rewrite = await import('../services/placeholderRewriteService');
    vi.mocked(pii.detectPII).mockReturnValue([]);
    vi.mocked(rewrite.rewriteKnownPIIPlaceholders).mockImplementation((markdown) => ({ markdown, appliedMappings: [] }));
  });
  afterEach(() => { mocks.privacySettings.masterEnabled = false; });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,message-input.send.ownership
  it('sends a regex-protected payload when the model is unavailable and the facade returns its baseline', async () => {
    const facade = await import('../services/webPIIDetectionService');
    const pii = await import('../services/piiDetectionService');
    const basic = await vi.importActual<typeof import('../services/piiDetectionService')>('../services/piiDetectionService');
    const original = 'Please email person@example.test';
    const fallbackMatches = basic.detectPII(original);
    expect(fallbackMatches).toContainEqual(expect.objectContaining({ type: 'EMAIL', match: 'person@example.test' }));
    // The facade owns model-error recovery; the send path receives the complete regex baseline.
    vi.mocked(facade.detectPIIForWeb).mockResolvedValueOnce(fallbackMatches);
    vi.mocked(pii.replacePIIWithPlaceholders).mockImplementation(basic.replacePIIWithPlaceholders);
    vi.mocked(pii.createPIIMappingsForStorage).mockImplementation(basic.createPIIMappingsForStorage);
    mocks.tipTapToCanonicalMarkdown.mockReturnValue(original);
    const { editor, setContent } = makeEditor(false);
    expect(await handleSend(editor, vi.fn(), vi.fn(), 'chat-auth')).toBe(true);
    expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledTimes(1);
    const sent = mocks.chatSyncService.sendNewMessage.mock.calls[0][0] as { content: string; pii_mappings: Array<{ original: string; placeholder: string }> };
    expect(sent.content).not.toContain('person@example.test');
    expect(sent.content).toBe(basic.replacePIIWithPlaceholders(original, fallbackMatches));
    expect(sent.pii_mappings).toContainEqual(expect.objectContaining({ original: 'person@example.test' }));
    expect(mocks.notifyError).not.toHaveBeenCalled();
    expect(setContent).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,pii.outbound.known-original-rewrite
  it('preserves a known semantic exclusion when the bounded scan returns only basic matches', async () => {
    const { modelPIIMatchId } = await import('../services/webPIIMatches');
    const rewrite = await import('../services/placeholderRewriteService');
    const original = 'Maple Avenue';
    const mapping = { type: 'ADDRESS', original, placeholder: '[ADDRESS_1_existing]' };
    mocks.getActivePIIMappingsForRewrite.mockReturnValue([mapping]);
    mocks.tipTapToCanonicalMarkdown.mockReturnValue(`Send deliveries to ${original}`);
    const { editor } = makeEditor(false);
    expect(await handleSend(editor, vi.fn(), vi.fn(), 'chat-auth', new Set([
      modelPIIMatchId('ADDRESS', original),
    ]))).toBe(true);
    const rewriteOptions = vi.mocked(rewrite.rewriteKnownPIIPlaceholders).mock.calls.at(-1)![1];
    expect(rewriteOptions.excludedOriginals).toEqual(new Set([original]));
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,message-input.privacy-context,message-input.send.ownership
  it('rejects when both privacy detectors fail before transport and restores the submitted draft', async () => {
    mocks.scanGate.mockRejectedValueOnce(new Error('Both detectors failed containing private input'));
    const { editor, document, setContent } = makeEditor(false);
    const original = structuredClone(document);
    const dispatch = vi.fn();
    expect(await handleSend(editor, dispatch, vi.fn(), 'chat-auth')).toBe(false);
    expect(mocks.chatSyncService.sendNewMessage).not.toHaveBeenCalled();
    expect(mocks.sendTextMessage).not.toHaveBeenCalled();
    expect(setContent).toHaveBeenCalledWith(original);
    expect(mocks.notifyError).toHaveBeenCalledWith('enter_message.pii.enhanced_scan_failed');
    expect(dispatch).toHaveBeenCalledWith('sendMessageRejected', expect.anything());
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,message-input.privacy-context,message-input.send.ownership
  it('preserves newer typing when both pending privacy detectors fail', async () => {
    let rejectScan!: (error: Error) => void;
    mocks.scanGate.mockImplementationOnce(() => new Promise<void>((_resolve, reject) => { rejectScan = reject; }));
    const { editor, setContent } = makeEditor(false);
    const sending = handleSend(editor, vi.fn(), vi.fn(), 'chat-auth');
    await vi.waitFor(() => expect(mocks.scanGate).toHaveBeenCalled());
    const nextDraft = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'New thought' }] }] };
    editor.commands.setContent(nextDraft);
    rejectScan(new Error('private combined detector error'));
    expect(await sending).toBe(false);
    expect(setContent).toHaveBeenCalledTimes(1);
    expect(editor.getJSON()).toEqual(nextDraft);
    expect(mocks.chatSyncService.sendNewMessage).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,message-input.privacy-context
  it.each(['settings', 'team', 'account'] as const)('does not send a scan result after %s change', async (change) => {
    let finishScan!: () => void;
    mocks.scanGate.mockImplementationOnce(() => new Promise<void>((resolve) => { finishScan = resolve; }));
    const { editor } = makeEditor(false);
    const sending = handleSend(editor, vi.fn(), vi.fn(), 'chat-auth');
    await vi.waitFor(() => expect(mocks.scanGate).toHaveBeenCalled());
    if (change === 'settings') mocks.privacySettings.masterEnabled = false;
    else if (change === 'team') mocks.teamContext.epoch++;
    else mocks.profileState.user_id = 'other-account';
    finishScan();
    expect(await sending).toBe(false);
    expect(mocks.chatSyncService.sendNewMessage).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,message-input.privacy-context
  it('rejects queued revisions and deferred sends when both privacy detectors fail', async () => {
    mocks.scanGate.mockRejectedValue(new Error('model and basic detector unavailable'));
    await expect(prepareQueuedMessageRevision({}, new Set())).rejects.toThrow('On-device privacy scan failed');
    await expect(executeDeferredSend({
      pendingId: 'pending-privacy', messageId: 'message-privacy', chatId: 'chat-auth',
      editorSnapshot: { type: 'doc', content: [{ type: 'paragraph' }] },
      embedSnapshots: new Map(), piiExclusions: new Set(), piiRewriteMappings: [],
    } as never)).rejects.toThrow('On-device privacy scan failed');
    expect(mocks.chatSyncService.sendNewMessage).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,message-input.privacy-context
  it('redacts recording text in TOON while preserving opaque upload metadata and encrypted mappings', async () => {
    const facade = await import('../services/webPIIDetectionService');
    const pii = await import('../services/piiDetectionService');
    vi.mocked(pii.detectPII).mockImplementation((value) => value.includes('person@example.test') ? [{
      id: 'email', type: 'EMAIL', match: 'person@example.test', placeholder: '[EMAIL_1]',
      startIndex: value.indexOf('person@example.test'), endIndex: value.indexOf('person@example.test') + 19,
    }] : []);
    vi.mocked(pii.replacePIIWithPlaceholders).mockImplementation((value) => value.replaceAll('person@example.test', '[EMAIL_1]'));
    vi.mocked(pii.createPIIMappingsForStorage).mockImplementation((matches) => matches.map((match) => ({
      type: match.type, original: match.match, placeholder: match.placeholder,
    })));
    const { editor, document } = makeEditor();
    Object.assign((document.content[2] as { attrs: Record<string, unknown> }).attrs, {
      uploadEmbedId: 'audio-1', title: 'From person@example.test', filename: 'person@example.test.wav',
      transcript: 'Email person@example.test', transcriptOriginal: 'Original person@example.test',
      transcriptCorrected: 'Corrected person@example.test', aesKey: 'opaque-person@example.test',
      s3Files: { audio: 'opaque-s3-key' },
    });
    expect(await handleSend(editor, vi.fn(), vi.fn(), 'chat-auth')).toBe(true);
    const recording = mocks.embedStorePut.mock.calls.find(([key]) => key === 'embed:audio-1')?.[1] as unknown as { content: string; text_preview: string };
    const { decode } = await import('@toon-format/toon');
    const content = decode(recording.content) as Record<string, unknown>;
    for (const field of ['title', 'filename', 'transcript', 'transcript_original', 'transcript_corrected']) {
      expect(content[field]).toContain('[EMAIL_1]');
      expect(content[field]).not.toContain('person@example.test');
    }
    expect(content.aes_key).toBe('opaque-person@example.test');
    expect(content.files).toEqual({ audio: 'opaque-s3-key' });
    expect(recording.text_preview).not.toContain('person@example.test');
    expect(mocks.chatSyncService.sendNewMessage.mock.calls[0][0].pii_mappings).toContainEqual({
      type: 'EMAIL', original: 'person@example.test', placeholder: '[EMAIL_1]',
    });
    expect(pii.detectPII).not.toHaveBeenCalledWith('opaque-person@example.test', expect.anything());
    // Multiple transcript variants and the final message share one budget;
    // giving each field its own timeout would multiply send latency.
    const scanContexts = vi.mocked(facade.detectPIIForWeb).mock.calls.map(call => call[2]);
    expect(scanContexts.length).toBeGreaterThan(3);
    expect(scanContexts[0]).toEqual({ purpose: 'send' });
    expect(scanContexts.every(context => context === scanContexts[0])).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,message-input.privacy-context
  it('redacts cached recording TOON for a queued revision and keeps originals in owner-only mapping storage', async () => {
    const pii = await import('../services/piiDetectionService');
    vi.mocked(pii.detectPII).mockImplementation((value) => value.includes('person@example.test') ? [{
      id: 'email', type: 'EMAIL', match: 'person@example.test', placeholder: '[EMAIL_1]',
      startIndex: value.indexOf('person@example.test'), endIndex: value.indexOf('person@example.test') + 19,
    }] : []);
    vi.mocked(pii.replacePIIWithPlaceholders).mockImplementation((value) => value.replaceAll('person@example.test', '[EMAIL_1]'));
    vi.mocked(pii.createPIIMappingsForStorage).mockImplementation((matches) => matches.map((match) => ({
      type: match.type, original: match.match, placeholder: match.placeholder,
    })));
    const { encode, decode } = await import('@toon-format/toon');
    mocks.embedStoreGet.mockImplementation(async (key?: string) => key === 'embed:audio-cached' ? {
      content: encode({ transcript: 'Email person@example.test', aes_key: 'opaque-key', files: { audio: 's3-object' } }),
      text_preview: 'person@example.test',
    } : undefined);
    const revision = await prepareQueuedMessageRevision({ type: 'doc', content: [
      { type: 'embed', attrs: { type: 'recording', contentRef: 'embed:audio-cached' } },
    ] }, new Set());
    const mapping = { type: 'EMAIL', original: 'person@example.test', placeholder: '[EMAIL_1]' };
    expect(revision.piiMappings).toContainEqual(mapping);
    expect(mocks.embedStorePut).toHaveBeenCalledWith('embed_pii:audio-cached', expect.objectContaining({ pii_mappings: [mapping] }), 'audio-recording');
    const cached = mocks.embedStorePut.mock.calls.find(([key]) => key === 'embed:audio-cached')?.[1] as { content: string };
    expect(decode(cached.content)).toEqual({ transcript: 'Email [EMAIL_1]', aes_key: 'opaque-key', files: { audio: 's3-object' } });
  });


  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,message-input.privacy-context
  it('keeps different originals unambiguous across independently scanned recording fields and markdown', async () => {
    const pii = await import('../services/piiDetectionService');
    vi.mocked(pii.detectPII).mockImplementation((value) => ['Alice', 'Bob', 'Carol'].filter((name) => value.includes(name)).map((name) => ({
      id: `person-${name}`, type: 'PERSON_NAME', match: name, placeholder: '[PERSON_NAME_1]',
      startIndex: value.indexOf(name), endIndex: value.indexOf(name) + name.length,
    })));
    vi.mocked(pii.replacePIIWithPlaceholders).mockImplementation((value, matches) => matches.reduce((result, match) => result.replaceAll(match.match, match.placeholder), value));
    vi.mocked(pii.createPIIMappingsForStorage).mockImplementation((matches) => matches.map((match) => ({
      type: match.type, original: match.match, placeholder: match.placeholder,
    })));
    mocks.tipTapToCanonicalMarkdown.mockReturnValue('Carol');
    const { editor, document } = makeEditor();
    Object.assign((document.content[2] as { attrs: Record<string, unknown> }).attrs, {
      uploadEmbedId: 'audio-1', title: 'Alice', transcript: 'Bob',
    });
    expect(await handleSend(editor, vi.fn(), vi.fn(), 'chat-auth')).toBe(true);
    const sent = mocks.chatSyncService.sendNewMessage.mock.calls[0][0] as { content: string; pii_mappings: Array<{ original: string; placeholder: string }> };
    expect(new Set(sent.pii_mappings.map((mapping) => mapping.placeholder)).size).toBe(3);
    expect(sent.pii_mappings.map((mapping) => mapping.original)).toEqual(['Alice', 'Bob', 'Carol']);
    expect(sent.content).toBe(sent.pii_mappings.find((mapping) => mapping.original === 'Carol')?.placeholder);
  });


  async function queueTrialUpload() {
    const { editor, document } = makeEditor();
    document.content.splice(2); // Keep one upload, without an unrelated recording.
    const image = (document.content[1] as { attrs: Record<string, unknown> }).attrs;
    image.status = 'uploading';
    image.contentRef = null;
    expect(await handleSend(editor, vi.fn(), vi.fn(), 'chat-auth')).toBe(true);
    const context = [...get(pendingUploadStore).values()].flat().at(-1)!;
    context.blockingEmbedIds.clear();
    return context;
  }

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,message-input.send.ownership
  it('keeps a failed deferred scan recoverable and adopts fresh settings only on explicit retry', async () => {
    const context = await queueTrialUpload();
    try {
      expect(claimPendingSendPrivacy(context)).toBe(true);
      mocks.scanGate.mockRejectedValueOnce(new Error('model and basic detector unavailable'));
      await expect(executeDeferredSend(context)).rejects.toThrow('On-device privacy scan failed');
      markPendingSendPrivacyFailure(context);
      expect(get(pendingUploadStore).get(context.chatId)?.[0]).toBe(context);
      expect(getReadyPendingSend(context.chatId)).toBeUndefined();
      expect(mocks.chatSyncService.sendNewMessage).not.toHaveBeenCalled();
      expect(claimPendingSendPrivacy(context, true)).toBe(true);
      mocks.scanGate.mockRejectedValueOnce(new Error('model and basic detector retry unavailable'));
      await expect(executeDeferredSend(context, { retryPrivacy: true })).rejects.toThrow('On-device privacy scan failed');
      markPendingSendPrivacyFailure(context);
      expect(context.privacyScanState).toBe('failed');
      expect(mocks.chatSyncService.sendNewMessage).not.toHaveBeenCalled();
      mocks.privacySettings.masterEnabled = false;
      expect(claimPendingSendPrivacy(context)).toBe(false);
      await expect(executeDeferredSend(context)).rejects.toThrow('Send context changed');
      expect(claimPendingSendPrivacy(context, true)).toBe(true);
      await executeDeferredSend(context, { retryPrivacy: true });
      expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledTimes(1);
      expect(get(pendingUploadStore).get(context.chatId)?.[0]).toBe(context);
    } finally { removePendingSend(context.chatId, context.pendingId); }
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  it.each(['account', 'team'] as const)('rejects deferred privacy retry after its original %s authority changes', async (change) => {
    const context = await queueTrialUpload();
    try {
      expect(claimPendingSendPrivacy(context)).toBe(true);
      mocks.scanGate.mockRejectedValueOnce(new Error('model and basic detector unavailable'));
      await expect(executeDeferredSend(context)).rejects.toThrow('On-device privacy scan failed');
      markPendingSendPrivacyFailure(context);
      if (change === 'account') mocks.profileState.user_id = 'different-account';
      else mocks.teamContext.epoch++;
      mocks.scanGate.mockClear();
      expect(claimPendingSendPrivacy(context, true)).toBe(true);
      await expect(executeDeferredSend(context, { retryPrivacy: true })).rejects.toThrow('Send context changed');
      markPendingSendPrivacyFailure(context);
      expect(context.privacyScanState).toBe('failed');
      expect(mocks.scanGate).not.toHaveBeenCalled();
      expect(mocks.chatSyncService.sendNewMessage).not.toHaveBeenCalled();
    } finally { removePendingSend(context.chatId, context.pendingId); }
  });


  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,message-input.send.ownership
  it('continues the ready FIFO after the immediate upload-completion head finishes scanning', async () => {
    let finishScan!: () => void;
    mocks.scanGate.mockImplementationOnce(() => new Promise<void>((resolve) => { finishScan = resolve; }));
    const { editor, document } = makeEditor();
    document.content.splice(2);
    // The upload reference became available before its status update arrived.
    (document.content[1] as { attrs: Record<string, unknown> }).attrs.status = 'uploading';
    expect(await handleSend(editor, vi.fn(), vi.fn(), 'chat-auth')).toBe(true);
    await vi.waitFor(() => expect(mocks.scanGate).toHaveBeenCalled());
    const first = get(pendingUploadStore).get('chat-auth')![0];
    const second = {
      pendingId: 'next-ready-pending', messageId: 'next-ready-message', chatId: 'chat-auth',
      editorSnapshot: { type: 'doc', content: [{ type: 'paragraph' }] },
      embedSnapshots: new Map(), blockingEmbedIds: new Set(['next-upload']), embedProgress: new Map(),
      createdAt: Date.now(), piiExclusions: new Set<string>(), piiRewriteMappings: [], partialMarkdown: '',
    };
    addPendingSend(second);
    second.blockingEmbedIds.clear();
    try {
      expect(first.privacyScanState).toBe('scanning');
      expect(getReadyPendingSend('chat-auth')).toBeUndefined();
      finishScan();
      await vi.waitFor(() => expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledTimes(2));
      expect(mocks.chatSyncService.sendNewMessage.mock.calls.map(([message]) => message.message_id)).toEqual([first.messageId, second.messageId]);
      await vi.waitFor(() => expect(get(pendingUploadStore).has('chat-auth')).toBe(false));
    } finally {
      removePendingSend(first.chatId, first.pendingId);
      removePendingSend(second.chatId, second.pendingId);
    }
  });


  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,message-input.send.ownership
  it('converts the failed scan toast into one persistent retry action and preserves original account authority', async () => {
    const context = await queueTrialUpload();
    try {
      mocks.scanGate.mockRejectedValueOnce(new Error('both privacy detectors failed'));
      await dispatchPendingSendWithPrivacyRetry(context);
      expect(context.privacyScanState).toBe('failed');
      expect(mocks.chatSyncService.sendNewMessage).not.toHaveBeenCalled();
      expect(mocks.notifyError).toHaveBeenCalledTimes(1);
      expect(mocks.notify).not.toHaveBeenCalled();
      expect(mocks.cancelNotificationAutoDismiss).toHaveBeenCalledWith('privacy-error-notification-id');
      const toast = mocks.updateNotification.mock.calls.at(-1)![1] as { duration: number; message: string; actionLabel: string; onAction: () => void };
      expect(toast).toMatchObject({ duration: 0, dismissible: false, message: 'enter_message.pii.model_pending_error', actionLabel: 'enter_message.pii.model_retry_message' });
      await dispatchPendingSendWithPrivacyRetry(context);
      expect(mocks.notifyError).toHaveBeenCalledTimes(1);
      mocks.profileState.user_id = 'different-account';
      toast.onAction();
      await vi.waitFor(() => expect(mocks.resetWebPIIDetector).toHaveBeenCalledTimes(1));
      await vi.waitFor(() => expect(mocks.updateNotification).toHaveBeenCalledTimes(3));
      expect(context.privacyScanState).toBe('failed');
      expect(get(pendingUploadStore).get(context.chatId)?.[0]).toBe(context);
      expect(mocks.chatSyncService.sendNewMessage).not.toHaveBeenCalled();
      expect(mocks.notifyError).toHaveBeenCalledTimes(1);
      expect(mocks.notify).not.toHaveBeenCalled();
    } finally { removePendingSend(context.chatId, context.pendingId); }
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,message-input.send.ownership
  it('retries the retained submission through the notification action and removes its toast after acceptance', async () => {
    const context = await queueTrialUpload();
    try {
      mocks.scanGate.mockRejectedValueOnce(new Error('both privacy detectors failed'));
      await dispatchPendingSendWithPrivacyRetry(context);
      const toast = mocks.updateNotification.mock.calls.at(-1)![1] as { onAction: () => void };
      toast.onAction();
      await vi.waitFor(() => expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledTimes(1));
      await vi.waitFor(() => expect(get(pendingUploadStore).has(context.chatId)).toBe(false));
      expect(mocks.resetWebPIIDetector).toHaveBeenCalledTimes(1);
      expect(mocks.removeNotification).toHaveBeenCalledWith('privacy-error-notification-id');
      expect(mocks.clearCurrentDraft).toHaveBeenCalledWith(expect.objectContaining({ chatId: context.chatId, document: expect.anything() }));
      expect(mocks.notifyError).toHaveBeenCalledTimes(1);
    } finally { removePendingSend(context.chatId, context.pendingId); }
  });


  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude,message-input.send.ownership
  it.each(['other chat', 'newer document'] as const)('preserves a draft owned by %s when a queued privacy retry succeeds', async (change) => {
    const { editor, document } = makeEditor();
    document.content.splice(2);
    Object.assign((document.content[1] as { attrs: Record<string, unknown> }).attrs, { status: 'uploading', contentRef: null });
    expect(await handleSend(editor, vi.fn(), vi.fn(), 'chat-auth')).toBe(true);
    const context = get(pendingUploadStore).get('chat-auth')![0];
    context.blockingEmbedIds.clear();
    try {
      mocks.scanGate.mockRejectedValueOnce(new Error('both privacy detectors failed'));
      await dispatchPendingSendWithPrivacyRetry(context);
      const retryToast = mocks.updateNotification.mock.calls.at(-1)![1] as { onAction: () => void };
      const nextDraft = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Keep this new draft' }] }] };
      editor.commands.setContent(nextDraft);
      if (change === 'other chat') mocks.draftState.currentChatId = 'chat-other';
      mocks.clearCurrentDraft.mockClear();
      retryToast.onAction();
      await vi.waitFor(() => expect(mocks.chatSyncService.sendNewMessage).toHaveBeenCalledTimes(1));
      await vi.waitFor(() => expect(get(pendingUploadStore).has(context.chatId)).toBe(false));
      expect(mocks.clearCurrentDraft).not.toHaveBeenCalled();
      expect(editor.getJSON()).toEqual(nextDraft);
    } finally { removePendingSend(context.chatId, context.pendingId); }
  });

});
