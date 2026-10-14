/**
 * Dev-only E2E browser hooks for Playwright readiness and fixture seeding.
 *
 * These hooks are installed only on localhost/dev hosts. They expose small,
 * explicit test-only probes on window without initializing the full app twice.
 * Production hosts never receive these globals.
 */
import { get } from 'svelte/store';
import { chatDB } from './db';
import { draftEditorUIState } from './drafts/draftState';
import { chatMetadataCache } from './chatMetadataCache';

export type E2EDraftSelectionDecision = {
  chatId: string;
  consumer: 'active_chat' | 'chat_list';
  result: 'applied' | 'paused' | 'skipped';
};

type E2EDraftSelectionGate = {
  promise: Promise<void>;
  release: () => void;
};

function isE2EHost(): boolean {
  return typeof window !== 'undefined' && (
    window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1' ||
    window.location.hostname.endsWith('.dev.openmates.org')
  );
}

export function recordE2EDraftSelectionDecision(decision: E2EDraftSelectionDecision): void {
  if (!isE2EHost()) return;
  const testWindow = window as unknown as {
    __openmatesE2EDraftSelectionTrace?: E2EDraftSelectionDecision[];
  };
  testWindow.__openmatesE2EDraftSelectionTrace?.push(decision);
}

export async function waitForE2EDraftSelectionCommit(
  chatId: string,
  consumer: E2EDraftSelectionDecision['consumer'],
): Promise<void> {
  if (!isE2EHost()) return;
  const testWindow = window as unknown as {
    __openmatesE2EDraftSelectionGate?: E2EDraftSelectionGate;
  };
  const gate = testWindow.__openmatesE2EDraftSelectionGate;
  if (!gate) return;
  recordE2EDraftSelectionDecision({ chatId, consumer, result: 'paused' });
  await gate.promise;
}

export async function installE2ETestHooks() {
  if (typeof window === 'undefined') return;
  const isDevHost =
    window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1' ||
    window.location.hostname.endsWith('.dev.openmates.org');
  if (!isDevHost) return;

  const testWindow = window as unknown as {
    __openmatesE2ESeedChat?: (input: {
      chat: Record<string, unknown>;
      messages: Record<string, unknown>[];
    }) => Promise<{ chatId: string; messageCount: number }>;
    __openmatesE2ESeedSavedEmbedMemory?: (input: {
      embedId: string;
      title: string;
    }) => Promise<{ entryId: string }>;
    __openmatesE2ESetDraftPreview?: (chatId: string, preview: string, markdown?: string) => Promise<void>;
    __openmatesE2EChatConnectionState?: () => Promise<{
      online: boolean;
      websocketConnected: boolean;
      cachePrimed: boolean;
      teamContextActive: boolean;
      contextSyncCompleted: boolean;
    }>;
    __openmatesE2EReplayDraftSelection?: (chatId: string, pauseBeforeCommit?: boolean) => void;
    __openmatesE2EPauseNextDraftSelection?: () => void;
    __openmatesE2EReleaseDraftSelection?: () => void;
    __openmatesE2EDraftSelectionGate?: E2EDraftSelectionGate;
    __openmatesE2EDraftSelectionTrace?: E2EDraftSelectionDecision[];
    __openmatesE2EDraftState?: () => Record<string, unknown>;
    __openmatesE2EReplayCanonicalEmbedWrite?: (input: {
      chatId: string; embedId: string; changeContent?: boolean;
    }) => Promise<{ pending: boolean; connected: boolean }>;
    __openmatesE2EExampleEmbedCollision?: (input: {
      exampleChatId: string; seedPrivate?: boolean;
      sourceProbe?: { chatId: string; embedId: string; cleanup?: boolean };
    }) => Promise<{
      privateCachePreserved: boolean; privateResolverPreserved: boolean; publicResolverSelected: boolean;
      missingPublicFixtureBlocked: boolean; privateRefIndexPreserved: boolean; privatePiiPreserved: boolean;
    } | { sourceProbeMounted: boolean; sourceDiffersFromActive: boolean }>;
  };

  // Synthetic owner-cache collision against a checked-in public example UUID.
  // Return only booleans; private/cache content never leaves the browser.
  let cleanupSourceProbe: (() => Promise<void>) | null = null;
  testWindow.__openmatesE2EExampleEmbedCollision = async ({ exampleChatId, seedPrivate = false, sourceProbe }) => {
    if (sourceProbe) {
      const { activeChatStore } = await import('../stores/activeChatStore');
      const { authStore } = await import('../stores/authState');
      const sourceDiffersFromActive = !!activeChatStore.get() && activeChatStore.get() !== sourceProbe.chatId;
      if (!get(authStore).isAuthenticated) throw new Error('Source probe requires the authenticated test owner');
      const uuid = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;
      if (!uuid.test(sourceProbe.chatId) || !uuid.test(sourceProbe.embedId)) throw new Error('Source probe requires fixture UUIDs');
      await cleanupSourceProbe?.(); cleanupSourceProbe = null;
      if (sourceProbe.cleanup) return { sourceProbeMounted: false, sourceDiffersFromActive };
      if (!sourceDiffersFromActive) throw new Error('Source probe must preserve a different active chat');
      const { mount, unmount } = await import('svelte');
      const { default: EmbedReferencePreview } = await import('../components/embeds/EmbedReferencePreview.svelte');
      const { EMBED_SOURCE_CHAT_CONTEXT } = await import('../types/embedFullscreen');
      const target = document.createElement('div');
      target.dataset.testid = 'e2e-source-context-preview';
      // This gated component integration host stays inside recorded viewports,
      // below the public chat header. It does not navigate a fullscreen route.
      Object.assign(target.style, {
        position: 'fixed', top: '160px', left: '16px',
        width: 'min(480px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 184px)',
        boxSizing: 'border-box', padding: '12px', overflow: 'auto', zIndex: '2147483000',
        background: 'Canvas', color: 'CanvasText', border: '1px solid currentColor', borderRadius: '8px',
      });
      const proofLabel = document.createElement('div');
      proofLabel.textContent = 'Source fetch · component integration';
      proofLabel.style.marginBottom = '8px';
      target.appendChild(proofLabel);
      document.body.appendChild(target);
      const component = mount(EmbedReferencePreview, {
        target, props: { embedRef: sourceProbe.embedId, embedId: sourceProbe.embedId },
        context: new Map([[EMBED_SOURCE_CHAT_CONTEXT, { chatId: sourceProbe.chatId }]]),
      });
      cleanupSourceProbe = async () => { await unmount(component); target.remove(); };
      return { sourceProbeMounted: true, sourceDiffersFromActive };
    }

    const { getExampleChatEmbed, getExampleChatEmbeds, resolveExampleChatEmbedRef } = await import('../demo_chats/exampleChatStore');
    const { embedStore } = await import('./embedStore');
    const { resolveEmbed } = await import('./embedResolver');
    const embedId = getExampleChatEmbeds(exampleChatId).find((embed) =>
      embed.type === 'app_skill_use' && !!embed.content)?.embed_id;
    if (!embedId) throw new Error('No admitted example parent embed for collision test');
    const fixture = getExampleChatEmbed(embedId, exampleChatId);
    if (!fixture) throw new Error('E2E collision fixture is outside the example chat');
    const sentinel = 'E2E_PRIVATE_COLLISION_SENTINEL';
    const missingId = '11111111-1111-4111-8111-111111111111';
    if (seedPrivate) {
      embedStore.setInMemoryOnly(`embed:${embedId}`, {
        embed_id: embedId, type: fixture.type, status: 'finished', content: sentinel,
      });
      embedStore.setInMemoryOnly(`embed:${missingId}`, {
        embed_id: missingId, type: fixture.type, status: 'finished', content: sentinel,
      });
      embedStore.setInMemoryOnly(`embed_pii:${embedId}`, {
        embed_id: embedId, pii_mappings: [{ placeholder: sentinel }],
      });
      embedStore.registerEmbedRef(embedId, missingId, 'private');
    }
    const cached = await embedStore.get(`embed:${embedId}`);
    const privateEmbed = await resolveEmbed(embedId, { chatId: 'e2e-private-source-chat' });
    const publicEmbed = await resolveEmbed(embedId, { chatId: exampleChatId });
    const missingPublicEmbed = await resolveEmbed(missingId, { chatId: exampleChatId });
    const privatePii = await embedStore.get(`embed_pii:${embedId}`);
    const privatePiiMappings = privatePii && typeof privatePii === 'object'
      ? privatePii.pii_mappings : null;
    return {
      privateCachePreserved: typeof cached === 'object' && cached?.content === sentinel,
      privateResolverPreserved: privateEmbed?.content === sentinel,
      publicResolverSelected: publicEmbed?.content === fixture.content,
      missingPublicFixtureBlocked: missingPublicEmbed === null,
      privateRefIndexPreserved: embedStore.resolveByRef(embedId) === missingId
        && resolveExampleChatEmbedRef(embedId, exampleChatId)?.embedId === embedId,
      privatePiiPreserved: Array.isArray(privatePiiMappings)
        && privatePiiMappings[0]?.placeholder === sentinel,
    };
  };

  testWindow.__openmatesE2ESeedChat = async ({ chat, messages }) => {
    const chatId = String(chat.chat_id || '');
    if (!chatId.startsWith('e2e-')) {
      throw new Error('E2E seed chat IDs must start with e2e-');
    }

    const { chatKeyManager } = await import('./encryption/ChatKeyManager');
    chatKeyManager.createKeyForNewChat(chatId);
    await chatDB.addChat(chat as unknown as Parameters<typeof chatDB.addChat>[0]);
    // Persist the fixture key so another tab can decrypt the same local chat.
    await chatKeyManager.createAndPersistKey(chatId);
    for (const message of messages) {
      await chatDB.saveMessage(
        message as unknown as Parameters<typeof chatDB.saveMessage>[0],
      );
    }
    window.dispatchEvent(new CustomEvent('localChatListChanged', { detail: { chat_id: chatId } }));
    return { chatId, messageCount: messages.length };
  };

  testWindow.__openmatesE2ESeedSavedEmbedMemory = async ({ embedId, title }) => {
    if (!embedId.startsWith('e2e-')) throw new Error('E2E embed IDs must start with e2e-');
    const { encryptWithMasterKey } = await import('./cryptoService');
    const { appSettingsMemoriesStore } = await import('../stores/appSettingsMemoriesStore');
    const encrypted = await encryptWithMasterKey(JSON.stringify({
      embed_id: embedId, title, settings_group: 'saved_events', _original_item_key: title,
    }));
    if (!encrypted) throw new Error('Could not encrypt E2E saved memory fixture');
    const entryId = crypto.randomUUID();
    const now = Math.floor(Date.now() / 1000);
    await chatDB.storeAppSettingsMemoriesEntries([{
      id: entryId,
      app_id: 'events',
      item_key: `e2e-${entryId}`,
      item_type: 'saved_events',
      encrypted_item_json: encrypted,
      encrypted_app_key: '',
      created_at: now,
      updated_at: now,
      item_version: 1,
    }]);
    await appSettingsMemoriesStore.loadEntries();
    return { entryId };
  };

  testWindow.__openmatesE2ESetDraftPreview = async (chatId, preview, markdown) => {
    const chat = await chatDB.getRawChat(chatId);
    if (!chat?.encrypted_draft_md || Number(chat.messages_v ?? 0) > 0) {
      throw new Error('E2E draft preview fixture requires a saved draft-only chat');
    }
    const { encryptWithMasterKey } = await import('./cryptoService');
    const encryptedPreview = await encryptWithMasterKey(preview);
    if (!encryptedPreview) throw new Error('Could not encrypt E2E draft preview fixture');
    const encryptedMarkdown = markdown ? await encryptWithMasterKey(markdown) : chat.encrypted_draft_md;
    if (!encryptedMarkdown) throw new Error('Could not encrypt E2E draft markdown fixture');
    await chatDB.addChat({ ...chat, encrypted_draft_md: encryptedMarkdown, encrypted_draft_preview: encryptedPreview });
    chatMetadataCache.invalidateChat(chatId);
    window.dispatchEvent(new CustomEvent('localChatListChanged', { detail: { chat_id: chatId } }));
    const { chatSyncService } = await import('./chatSyncService');
    chatSyncService.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: chatId, type: 'draft' } }));
  };

  testWindow.__openmatesE2EChatConnectionState = async () => {
    const { chatSyncService } = await import('./chatSyncService');
    const { activeTeamId } = await import('../stores/teamStore');
    return {
      online: window.navigator.onLine,
      websocketConnected: chatSyncService.webSocketConnected_FOR_SENDERS_ONLY,
      cachePrimed: chatSyncService.cachePrimed_FOR_HANDLERS_ONLY,
      teamContextActive: Boolean(get(activeTeamId)),
      // Team switches reset this flag. Stale completion frames are rejected by
      // chatSyncService's context/epoch guard before they can set it again.
      contextSyncCompleted: chatSyncService.hasCompletedInitialSync_FOR_HANDLERS_ONLY,
    };
  };

  testWindow.__openmatesE2EReplayDraftSelection = (chatId: string, pauseBeforeCommit = false) => {
    testWindow.__openmatesE2EDraftSelectionTrace = [];
    if (pauseBeforeCommit) {
      let release = () => undefined;
      const promise = new Promise<void>((resolve) => {
        release = resolve;
      });
      testWindow.__openmatesE2EDraftSelectionGate = { promise, release };
    }
    draftEditorUIState.update((state) => ({
      ...state,
      newlyCreatedChatIdToSelect: chatId,
    }));
  };

  testWindow.__openmatesE2EPauseNextDraftSelection = () => {
    testWindow.__openmatesE2EDraftSelectionTrace = [];
    let release = () => undefined;
    const promise = new Promise<void>((resolve) => {
      release = resolve;
    });
    testWindow.__openmatesE2EDraftSelectionGate = { promise, release };
  };

  testWindow.__openmatesE2EReleaseDraftSelection = () => {
    testWindow.__openmatesE2EDraftSelectionGate?.release();
    delete testWindow.__openmatesE2EDraftSelectionGate;
  };

  testWindow.__openmatesE2EDraftState = () => structuredClone(
    get(draftEditorUIState) as unknown as Record<string, unknown>,
  );

  // Exercise the real sender against an owner-authorized recovered head. Return
  // only queue state; neither the plaintext nor encrypted material reaches E2E logs.
  testWindow.__openmatesE2EReplayCanonicalEmbedWrite = async ({ chatId, embedId, changeContent = false }) => {
    const { getApiEndpoint, storageArchiveFetch } = await import('../config/api');
    const { embedStore } = await import('./embedStore');
    const { decryptWithEmbedKey, encryptWithEmbedKey } = await import('./encryption/MetadataEncryptor');
    const { chatSyncService } = await import('./chatSyncService');
    const { sendStoreEmbedImpl } = await import('./embedSenders');
    const chat = await chatDB.getRawChat(chatId);
    if (!chat) throw new Error('E2E canonical replay chat is unavailable');
    const query = chat.team_id ? `?team_id=${encodeURIComponent(chat.team_id)}` : '';
    const response = await storageArchiveFetch(getApiEndpoint(
      `/v1/embeds/chats/${encodeURIComponent(chatId)}/embeds/${encodeURIComponent(embedId)}${query}`,
    ), { credentials: 'include' });
    if (!response.ok) throw new Error(`E2E canonical replay head read failed (${response.status})`);
    const page = await response.json() as { embed?: Record<string, unknown> };
    const head = page.embed;
    if (!head || head.embed_id !== embedId || typeof head.hashed_chat_id !== 'string'
      || typeof head.encrypted_content !== 'string' || typeof head.encrypted_type !== 'string') {
      throw new Error('E2E canonical replay head is incomplete');
    }
    const key = await embedStore.getEmbedKey(embedId, head.hashed_chat_id);
    if (!key) throw new Error('E2E canonical replay key is unavailable');
    const content = await decryptWithEmbedKey(head.encrypted_content, key);
    const type = await decryptWithEmbedKey(head.encrypted_type, key);
    if (content === null || type === null) throw new Error('E2E canonical replay decryption failed');
    const encryptedContent = await encryptWithEmbedKey(
      changeContent ? `${content}\nE2E changed logical content` : content, key,
    );
    const encryptedType = await encryptWithEmbedKey(type, key);
    if (encryptedContent === head.encrypted_content || encryptedType === head.encrypted_type) {
      throw new Error('E2E canonical replay did not generate fresh ciphertext');
    }
    const connected = chatSyncService.webSocketConnected_FOR_SENDERS_ONLY;
    if (!connected) throw new Error('E2E canonical replay WebSocket is disconnected');
    await sendStoreEmbedImpl(chatSyncService, {
      embed_id: embedId, chat_id: chatId, team_id: chat.team_id ?? null,
      encrypted_content: encryptedContent, encrypted_type: encryptedType,
      encrypted_text_preview: head.encrypted_text_preview as string | undefined,
      status: head.status as string,
      hashed_chat_id: head.hashed_chat_id,
      hashed_message_id: head.hashed_message_id as string,
      hashed_task_id: head.hashed_task_id as string | undefined,
      hashed_user_id: head.hashed_user_id as string,
      app_id: head.app_id as string | undefined,
      skill_id: head.skill_id as string | undefined,
      embed_ids: head.embed_ids as string[] | undefined,
      parent_embed_id: head.parent_embed_id as string | undefined,
      version_number: head.version_number as number | undefined,
      is_private: head.is_private as boolean | undefined,
      is_shared: head.is_shared as boolean | undefined,
      created_at: head.created_at as number,
      updated_at: head.updated_at as number,
    } as Parameters<typeof sendStoreEmbedImpl>[1]);
    const pending = (await chatDB.getPendingEmbedOperations()).some((operation) => operation.embed_id === embedId);
    return { pending, connected };
  };
}
