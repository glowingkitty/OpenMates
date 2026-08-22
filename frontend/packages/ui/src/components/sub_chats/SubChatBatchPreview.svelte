<!--
  frontend/packages/ui/src/components/sub_chats/SubChatBatchPreview.svelte

  Inline renderer for a batch of sub-chat preview cards anchored inside an
  assistant message. It loads child chats from static examples and IndexedDB,
  then refreshes when sub-chat lifecycle events update local metadata.
-->

<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { fade } from 'svelte/transition';
  import { text } from '@repo/ui';
  import ChatContextMenu from '../chats/ChatContextMenu.svelte';
  import { activeChatStore } from '../../stores/activeChatStore';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import { panelState } from '../../stores/panelStateStore';
  import { chatDB } from '../../services/db';
  import { chatSyncService } from '../../services/chatSyncService';
  import { copyChatToClipboard } from '../../services/chatExportService';
  import { downloadChatAsZip } from '../../services/zipExportService';
  import { LOCAL_CHAT_LIST_CHANGED_EVENT } from '../../services/drafts/draftConstants';
  import {
    clearSubChatsForParentCache,
    loadSubChatPreviews,
    type SubChatPreview,
  } from '../../services/subChatPreviewService';
  import { getExampleChat } from '../../demo_chats';
  import { getCategoryGradientColors, getLucideIcon, getValidIconName } from '../../utils/categoryUtils';

  interface Props {
    batchId: string;
    parentChatId: string;
    subChatIds?: string[];
    status?: 'processing' | 'finished' | 'error' | 'cancelled' | string;
  }

  type SubChatProgress = {
    type?: 'sub_chat_progress';
    chat_id?: string;
    task_id?: string;
    message_id?: string;
    execution_mode?: 'parallel' | 'sequential';
    status?: 'running' | 'stopping' | 'stopped' | 'completed' | 'error' | 'cancelled' | string;
    total?: number;
    completed?: number;
    active_sub_chat_id?: string | null;
  };

  type SubChatCardStatus = {
    label: string;
    testId: string;
    state: 'completed' | 'thinking' | 'waiting' | 'stopped' | 'attention' | 'queued';
  };

  let {
    batchId,
    parentChatId,
    subChatIds = [],
    status = 'processing',
  }: Props = $props();

  let subChats = $state<SubChatPreview[]>([]);
  let isLoading = $state(true);
  let contextMenuChat = $state<SubChatPreview | null>(null);
  let contextMenuX = $state(0);
  let contextMenuY = $state(0);
  let contextMenuVisible = $state(false);
  let downloading = $state(false);
  let prefersTouchCta = $state(false);
  let latestSubChatProgress = $state<SubChatProgress | null>(null);
  let latestLoadId = 0;
  const terminalSubChatIds = new Set<string>();
  const STATUS_MATE_NAME_MAX_LENGTH = 22;

  function getSubChatPreviewStyle(category?: string | null): string {
    const colors = getCategoryGradientColors(category || 'general_knowledge') ?? {
      start: '#4867cd',
      end: '#a0beff',
    };

    return [
      `background: linear-gradient(135deg, ${colors.start}, ${colors.end})`,
      `--orb-color-a: ${colors.start}`,
      `--orb-color-b: ${colors.end}`,
    ].join('; ');
  }

  function statusMateName(subChat: SubChatPreview): string {
    const rawName = (subChat.title || 'Mate').trim();
    if (rawName.length <= STATUS_MATE_NAME_MAX_LENGTH) return rawName;
    return `${rawName.slice(0, STATUS_MATE_NAME_MAX_LENGTH).trimEnd()}...`;
  }

  function getSubChatCardStatus(subChat: SubChatPreview): SubChatCardStatus {
    const progressStatus = latestSubChatProgress?.status || '';
    if (
      subChat.previewSummary ||
      terminalSubChatIds.has(subChat.chat_id) ||
      status === 'finished' ||
      progressStatus === 'completed'
    ) {
      return { label: 'Completed', testId: 'sub-chat-status-completed', state: 'completed' };
    }
    if (status === 'error' || progressStatus === 'error' || progressStatus === 'failed') {
      return { label: 'Needs attention', testId: 'sub-chat-status-attention', state: 'attention' };
    }
    if (status === 'cancelled' || progressStatus === 'cancelled' || progressStatus === 'stopped') {
      return { label: 'Stopped', testId: 'sub-chat-status-stopped', state: 'stopped' };
    }
    if (latestSubChatProgress?.active_sub_chat_id === subChat.chat_id) {
      return { label: `${statusMateName(subChat)} is thinking...`, testId: 'sub-chat-status-thinking', state: 'thinking' };
    }
    if (latestSubChatProgress?.execution_mode === 'sequential' && progressStatus !== 'completed') {
      return { label: 'Waiting its turn', testId: 'sub-chat-status-waiting', state: 'waiting' };
    }
    if (status === 'processing' || progressStatus === 'running' || progressStatus === 'stopping') {
      return { label: `${statusMateName(subChat)} is thinking...`, testId: 'sub-chat-status-thinking', state: 'thinking' };
    }
    return { label: 'Queued', testId: 'sub-chat-status-queued', state: 'queued' };
  }

  async function load(forceRefresh = false): Promise<void> {
    if (!parentChatId) return;
    const loadId = ++latestLoadId;
    isLoading = true;
    try {
      if (forceRefresh) clearSubChatsForParentCache(parentChatId);
      const previews = await loadSubChatPreviews(parentChatId, {
        subChatIds,
        forceRefresh,
        allowUnsyncedAssistantSummary: status !== 'processing',
        terminalSubChatIds,
      });
      if (loadId !== latestLoadId) return;

      const previousById = new Map(subChats.map((subChat) => [subChat.chat_id, subChat]));
      subChats = previews.map((preview) => {
        const previous = previousById.get(preview.chat_id);
        if (!previous?.previewSummary || preview.previewSummary) return preview;
        return { ...preview, previewSummary: previous.previewSummary };
      });
    } catch (error) {
      if (loadId === latestLoadId) {
        console.error('[SubChatBatchPreview] Failed to load sub-chat previews:', error);
      }
    } finally {
      if (loadId === latestLoadId) {
        isLoading = false;
      }
    }
  }

  function handleContextMenu(event: MouseEvent, subChat: SubChatPreview): void {
    event.preventDefault();
    event.stopPropagation();
    contextMenuChat = subChat;
    contextMenuX = event.clientX;
    contextMenuY = event.clientY;
    contextMenuVisible = true;
  }

  async function openSubChat(subChat: SubChatPreview): Promise<void> {
    activeChatStore.setActiveChat(subChat.chat_id);
    const exampleChat = getExampleChat(subChat.chat_id);
    if (exampleChat) {
      window.dispatchEvent(new CustomEvent('demoChatSelected', {
        detail: { chat: exampleChat },
        bubbles: true,
        composed: true,
      }));
    }
  }

  async function handleMenuAction(event: CustomEvent<string>): Promise<void> {
    const action = event.detail;
    const subChat = contextMenuChat;
    if (action === 'close') {
      contextMenuVisible = false;
      return;
    }
    if (!subChat) return;

    try {
      if (action === 'download' || action === 'copy') {
        const messages = await chatDB.getMessagesForChat(subChat.chat_id);
        if (action === 'download') {
          downloading = true;
          await downloadChatAsZip(subChat, messages);
        } else {
          await copyChatToClipboard(subChat, messages);
          const { notificationStore } = await import('../../stores/notificationStore');
          notificationStore.success('Chat copied to clipboard');
        }
      } else if (action === 'delete') {
        await chatDB.deleteChat(subChat.chat_id);
        chatSyncService.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id: subChat.chat_id } }));
        await chatSyncService.sendDeleteChat(subChat.chat_id);
        await load(true);
      } else if (action === 'share') {
        activeChatStore.setActiveChat(subChat.chat_id);
        settingsDeepLink.set('shared/share');
        panelState.openSettings();
      }
    } catch (error) {
      console.error('[SubChatBatchPreview] Context menu action failed:', action, error);
      const { notificationStore } = await import('../../stores/notificationStore');
      notificationStore.error('Failed to perform action');
    } finally {
      downloading = false;
      contextMenuVisible = false;
    }
  }

  function shouldRefreshFromDetail(detail: Record<string, unknown> | undefined): boolean {
    if (!detail) return true;
    return detail.chat_id === parentChatId || detail.parent_id === parentChatId;
  }

  function shouldRefreshFromChatUpdate(detail: Record<string, unknown> | undefined): boolean {
    if (!detail) return false;
    const chatId = typeof detail.chat_id === 'string' ? detail.chat_id : null;
    return Boolean(chatId && subChatIds.includes(chatId));
  }

  onMount(() => {
    const pointerQuery = window.matchMedia('(pointer: coarse)');
    const updatePointerCta = () => {
      prefersTouchCta = pointerQuery.matches || navigator.maxTouchPoints > 0;
    };
    updatePointerCta();
    pointerQuery.addEventListener('change', updatePointerCta);
    void load();

    const handleListChange = (event: Event) => {
      const detail = (event as CustomEvent<Record<string, unknown>>).detail;
      if (!shouldRefreshFromDetail(detail)) return;
      void load(true);
    };
    const handleSubChatLifecycle = (event: Event) => {
      const detail = (event as CustomEvent<Record<string, unknown>>).detail;
      if (!shouldRefreshFromDetail(detail)) return;
      if (detail?.type === 'sub_chat_progress') {
        latestSubChatProgress = detail as SubChatProgress;
      }
      if (detail?.type === 'sub_chat_completed' && typeof detail.chat_id === 'string') {
        terminalSubChatIds.add(detail.chat_id);
      }
      void load(true);
    };
    const handleChatUpdated = (event: Event) => {
      const detail = (event as CustomEvent<Record<string, unknown>>).detail;
      if (!shouldRefreshFromChatUpdate(detail)) return;
      if (typeof detail.chat_id === 'string') {
        terminalSubChatIds.add(detail.chat_id);
      }
      void load(true);
    };

    window.addEventListener(LOCAL_CHAT_LIST_CHANGED_EVENT, handleListChange);
    window.addEventListener('subChatProgress', handleSubChatLifecycle);
    window.addEventListener('subChatCompleted', handleSubChatLifecycle);
    chatSyncService.addEventListener('chatUpdated', handleChatUpdated);

    return () => {
      window.removeEventListener(LOCAL_CHAT_LIST_CHANGED_EVENT, handleListChange);
      window.removeEventListener('subChatProgress', handleSubChatLifecycle);
      window.removeEventListener('subChatCompleted', handleSubChatLifecycle);
      chatSyncService.removeEventListener('chatUpdated', handleChatUpdated);
      pointerQuery.removeEventListener('change', updatePointerCta);
    };
  });

  onDestroy(() => {
    latestLoadId++;
    contextMenuVisible = false;
  });
</script>

{#if isLoading && subChats.length === 0}
  <div class="sub-chat-batch-loading" data-testid="sub-chats-carousel" data-batch-id={batchId}>
    Loading sub-chats...
  </div>
{:else if subChats.length > 0}
  <div class="sub-chats-carousel" data-testid="sub-chats-carousel" data-batch-id={batchId} data-status={status}>
    {#each subChats as sc (sc.chat_id)}
      {@const subChatCategory = sc.previewCategory || 'general_knowledge'}
      {@const SubChatIcon = getLucideIcon(sc.previewIcon || getValidIconName('', subChatCategory))}
      {@const subChatStatus = getSubChatCardStatus(sc)}
      <button
        type="button"
        class="sub-chat-card sub-chat-large-card"
        data-testid="sub-chat-card"
        data-chat-id={sc.chat_id}
        data-category={subChatCategory}
        data-icon={sc.previewIcon || getValidIconName('', subChatCategory)}
        style={getSubChatPreviewStyle(subChatCategory)}
        oncontextmenu={(event) => handleContextMenu(event, sc)}
        onclick={() => openSubChat(sc)}
      >
        <div
          class="sub-chat-status-pill"
          data-testid={subChatStatus.testId}
          data-status-state={subChatStatus.state}
        >
          {subChatStatus.label}
        </div>
        <div class="sub-chat-large-orbs" aria-hidden="true">
          <div class="sub-chat-orb sub-chat-orb-1"></div>
          <div class="sub-chat-orb sub-chat-orb-2"></div>
          <div class="sub-chat-orb sub-chat-orb-3"></div>
        </div>
        <div class="sub-chat-large-deco sub-chat-large-deco-left" aria-hidden="true">
          <SubChatIcon size={80} color="white" />
        </div>
        <div class="sub-chat-large-deco sub-chat-large-deco-right" aria-hidden="true">
          <SubChatIcon size={80} color="white" />
        </div>
        <div class="sub-chat-large-content">
          <div class="sub-chat-large-icon" aria-hidden="true">
            <SubChatIcon size={32} color="white" />
          </div>
          <span class="sub-chat-large-title" data-testid="sub-chat-title">
            {sc.title || 'Autonomous Task'}
          </span>
          {#if sc.previewSummary}
            <p class="sub-chat-large-summary" data-testid="sub-chat-summary" transition:fade={{ duration: 180 }}>{sc.previewSummary}</p>
          {:else}
            <p class="sub-chat-open-cta" data-testid="sub-chat-open-cta" transition:fade={{ duration: 180 }}>
              {$text(prefersTouchCta ? 'chats.chat.sub_chats.tap_to_open' : 'chats.chat.sub_chats.click_to_open')}
            </p>
          {/if}
        </div>
      </button>
    {/each}
  </div>
{/if}

{#if contextMenuVisible && contextMenuChat}
  <ChatContextMenu
    x={contextMenuX}
    y={contextMenuY}
    show={contextMenuVisible}
    chat={contextMenuChat}
    hideSelect={true}
    hideVisibility={true}
    hidePin={true}
    hideReadStatus={true}
    selectMode={false}
    selectedChatIds={new Set<string>()}
    downloading={downloading}
    on:close={handleMenuAction}
    on:download={handleMenuAction}
    on:copy={handleMenuAction}
    on:delete={handleMenuAction}
    on:share={handleMenuAction}
  />
{/if}

<style>
  .sub-chat-batch-loading {
    width: min(100%, 640px);
    margin: var(--spacing-6) 0;
    padding: var(--spacing-6) var(--spacing-8);
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-7);
    color: var(--color-grey-70);
    background: var(--color-grey-0);
    font-size: var(--font-size-small);
  }

  .sub-chats-carousel {
    display: flex;
    gap: var(--spacing-8);
    overflow-x: auto;
    overflow-y: hidden;
    padding: var(--spacing-6) var(--spacing-2) var(--spacing-8);
    margin: var(--spacing-4) 0 var(--spacing-6);
    scrollbar-width: none;
    -ms-overflow-style: none;
  }

  .sub-chats-carousel::-webkit-scrollbar {
    display: none;
  }

  .sub-chat-card {
    position: relative;
    flex: 0 0 300px;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 300px;
    min-width: 300px;
    max-width: 300px;
    height: 200px;
    min-height: 200px;
    max-height: 200px;
    padding: 0;
    border: none;
    border-radius: 30px;
    background-color: transparent;
    cursor: pointer;
    overflow: hidden;
    user-select: none;
    -webkit-user-select: none;
    -webkit-touch-callout: none;
    box-shadow:
      0 8px 24px rgba(0, 0, 0, 0.16),
      0 2px 6px rgba(0, 0, 0, 0.1);
    transition:
      transform 0.15s ease-out,
      box-shadow 0.2s ease-out;
  }

  .sub-chat-card:hover,
  .sub-chat-card:active {
    background-color: transparent;
    filter: none;
    scale: 1;
  }

  .sub-chat-card:hover {
    transform: scale(0.98);
    box-shadow:
      0 4px 12px rgba(0, 0, 0, 0.12),
      0 1px 3px rgba(0, 0, 0, 0.08);
  }

  .sub-chat-card:active {
    transform: scale(0.96) !important;
    transition: transform 0.05s ease-out;
  }

  .sub-chat-card:focus {
    outline: 2px solid rgba(255, 255, 255, 0.5);
    outline-offset: 2px;
  }

  .sub-chat-status-pill {
    position: absolute;
    top: var(--spacing-8);
    left: var(--spacing-8);
    z-index: var(--z-index-raised-4);
    padding: 4px 9px;
    border-radius: 999px;
    background: rgba(0, 0, 0, 0.28);
    border: 1px solid rgba(255, 255, 255, 0.22);
    color: rgba(255, 255, 255, 0.92);
    font-size: var(--font-size-xxs);
    font-weight: 800;
    line-height: 1;
    max-width: calc(100% - var(--spacing-16));
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .sub-chat-large-content {
    position: relative;
    z-index: var(--z-index-raised-3);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-2);
    width: 100%;
    max-width: 260px;
    padding: var(--spacing-8) var(--spacing-12);
    text-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
  }

  .sub-chat-large-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    flex-shrink: 0;
  }

  .sub-chat-large-title {
    max-width: 100%;
    color: var(--color-font-button);
    font-size: var(--font-size-p);
    font-weight: 700;
    line-height: 1.3;
    text-align: center;
    overflow-wrap: anywhere;
  }

  .sub-chat-large-summary {
    margin: 2px 0 0;
    color: rgba(255, 255, 255, 0.85);
    font-size: var(--font-size-xxs);
    font-weight: 500;
    line-height: 1.4;
    text-align: center;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .sub-chat-open-cta {
    margin: 2px 0 0;
    color: rgba(255, 255, 255, 0.85);
    font-size: var(--font-size-xxs);
    font-weight: 600;
    line-height: 1.4;
    text-align: center;
  }

  .sub-chat-large-orbs {
    position: absolute;
    inset: 0;
    z-index: -1;
    overflow: hidden;
    pointer-events: none;
    border-radius: 30px;
  }

  .sub-chat-orb {
    position: absolute;
    width: 280px;
    height: 240px;
    background: radial-gradient(
      ellipse at center,
      var(--orb-color-b) 0%,
      var(--orb-color-b) 40%,
      transparent 85%
    );
    filter: blur(22px);
    opacity: 0.35;
    will-change: transform, border-radius;
  }

  .sub-chat-orb-1 {
    top: -60px;
    left: -70px;
    animation:
      orbMorph1 11s ease-in-out infinite,
      resumeOrbDrift1 19s ease-in-out infinite;
  }

  .sub-chat-orb-2 {
    right: -80px;
    bottom: -80px;
    width: 260px;
    height: 220px;
    animation:
      orbMorph2 13s ease-in-out infinite,
      resumeOrbDrift2 23s ease-in-out infinite;
  }

  .sub-chat-orb-3 {
    top: -10px;
    left: 25%;
    width: 200px;
    height: 180px;
    opacity: 0.38;
    animation:
      orbMorph3 17s ease-in-out infinite,
      resumeOrbDrift3 29s ease-in-out infinite;
  }

  .sub-chat-large-deco {
    position: absolute;
    z-index: var(--z-index-raised);
    display: flex;
    align-items: center;
    justify-content: center;
    width: 80px;
    height: 80px;
    pointer-events: none;
    --float-rx: 7px;
    --float-ry: 8px;
    --deco-target-opacity: 0.3;
    animation:
      decoEnter 0.6s ease-out 0.1s both,
      decoFloat 16s linear 0.7s infinite;
  }

  .sub-chat-large-deco-left {
    left: -10px;
    bottom: -8px;
    --deco-rotate: -15deg;
  }

  .sub-chat-large-deco-right {
    right: -10px;
    bottom: -8px;
    --deco-rotate: 15deg;
    animation-delay: 0.1s, -8s;
  }

  .sub-chat-large-deco :global(svg) {
    width: 80px !important;
    height: 80px !important;
  }

  @media (max-width: 680px) {
    .sub-chat-card {
      flex-basis: 260px;
      width: 260px;
      min-width: 260px;
      max-width: 260px;
      height: 188px;
      min-height: 188px;
      max-height: 188px;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .sub-chat-orb,
    .sub-chat-large-deco {
      animation: none !important;
    }
  }
</style>
