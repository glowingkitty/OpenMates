<!-- frontend/packages/ui/src/components/ChatRecommendations.svelte
     Container of the Recommendations card for one owned chat: hydrates the chat's
     encrypted recommendations and opens drafts (Memory draft in Settings > Memories,
     Workflow draft in the side panel). Clicking an action never removes a
     recommendation; only saving the entry does (contextEntryEvents).
     Rendered only in Rust core builds (VITE_OPENMATES_RUST_CORE=1).
     Plan: docs/plans/chat-recommendations/plan.yml (D-7..D-10)
     Spec: app-memories.suggestions.post-processor, app-memories.suggestions.billing
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '../i18n/translations';
  import RecommendationsCard from './RecommendationsCard.svelte';
  import { settingsMenuVisible } from './Settings.svelte';
  import { chatRecommendations } from '../stores/chatRecommendationsStore';
  import { memoryDraftSuggestion, type MemoryDraftPayload } from '../stores/memoryDraftSuggestionStore';
  import { settingsDeepLink } from '../stores/settingsDeepLinkStore';
  import { panelState } from '../stores/panelStateStore';
  import { notificationStore } from '../stores/notificationStore';
  import { openWorkflowSidePanel } from '../stores/workflowSidePanelStore';
  import { chatKeyManager } from '../services/encryption/ChatKeyManager';
  import { chatDB } from '../services/db';
  import { chatSyncService } from '../services/chatSyncService';
  import { hydrateChatRecommendations } from '../services/chatRecommendationsPersistence';
  import { listenForWorkflowRecommendationSaves } from '../services/contextEntryEvents';
  import {
    RecommendationDraftError, buildWorkflowInstruction, loadRecommendationTurn,
    requestCreateMemoryDraft, requestUpdatePreview, updateMemoryDraft,
  } from '../services/recommendationDrafts';
  import type { ChatRecommendation } from '../types/recommendations';

  interface Props {
    chatId: string;
    /** Chat category; selects the card gradient. */
    category: string | null;
  }
  let { chatId, category }: Props = $props();

  let busyId = $state<string | null>(null);
  let upToDateId = $state<string | null>(null);
  let items = $derived($chatRecommendations[chatId]?.items ?? []);
  let statusText = $derived(
    upToDateId && items.some((item) => item.id === upToDateId) ? $text('memories.suggestion_up_to_date') : null,
  );

  let hydratedCiphertext: string | null | undefined;

  async function refresh(targetChatId: string): Promise<void> {
    const chat = await chatDB.getChat(targetChatId);
    const ciphertext = chat?.encrypted_recommendations ?? null;
    if (targetChatId !== chatId || ciphertext === hydratedCiphertext) return;
    hydratedCiphertext = ciphertext;
    await hydrateChatRecommendations(targetChatId);
  }

  function refreshQuietly(targetChatId: string): void {
    refresh(targetChatId).catch((error) =>
      console.error(`[Recommendations] Could not load recommendations for chat ${targetChatId}`, error));
  }

  $effect(() => {
    const target = chatId;
    hydratedCiphertext = undefined;
    busyId = null;
    upToDateId = null;
    refreshQuietly(target);
  });

  onMount(() => {
    const stopKeys = chatKeyManager.onKeyReady((readyChatId) => {
      if (readyChatId === chatId) { hydratedCiphertext = undefined; refreshQuietly(readyChatId); }
    });
    // Another device or a sync pass may replace the stored ciphertext.
    const onChatUpdated = (event: Event) => {
      const detail = (event as CustomEvent<{ chat_id?: string }>).detail;
      if (detail?.chat_id === chatId) refreshQuietly(chatId);
    };
    chatSyncService.addEventListener('chatUpdated', onChatUpdated);
    const stopSaves = listenForWorkflowRecommendationSaves();
    return () => {
      stopKeys();
      stopSaves();
      chatSyncService.removeEventListener('chatUpdated', onChatUpdated);
    };
  });

  function openMemoryDraft(draft: MemoryDraftPayload, recommendationId: string): void {
    memoryDraftSuggestion.set({ ...draft, origin: { chatId, recommendationId } });
    settingsMenuVisible.set(true);
    panelState.openSettings();
    settingsDeepLink.set(`memories/${encodeURIComponent(draft.id)}`);
  }

  function failureMessage(error: unknown): string {
    const code = error instanceof RecommendationDraftError ? error.code : 'request_failed';
    if (code === 'insufficient_credits') return $text('memories.suggestion_insufficient_credits');
    if (code === 'memory_not_found') return $text('memories.suggestion_not_found');
    if (code === 'network_unavailable') return $text('memories.suggestion_connection_problem');
    return $text('memories.suggestion_failed');
  }

  async function openMemory(item: ChatRecommendation): Promise<void> {
    if (item.action === 'update' && item.target_id) {
      const { document, result } = await requestUpdatePreview(chatId, item.target_id);
      if (result.status === 'unchanged') { upToDateId = item.id; return; }
      openMemoryDraft(updateMemoryDraft(document, result.body), item.id);
      return;
    }
    openMemoryDraft(await requestCreateMemoryDraft(chatId, item), item.id);
  }

  async function openWorkflow(item: ChatRecommendation): Promise<void> {
    const instruction = buildWorkflowInstruction(item, await loadRecommendationTurn(chatId));
    openWorkflowSidePanel({
      chatId, recommendationId: item.id, mode: item.action,
      workflowId: item.action === 'update' ? item.target_id : null, instruction,
    });
  }

  async function handleAction(item: ChatRecommendation): Promise<void> {
    if (busyId) return;
    busyId = item.id;
    upToDateId = null;
    try {
      if (item.kind === 'memory') await openMemory(item);
      else await openWorkflow(item);
    } catch (error) {
      console.error('[Recommendations] Could not open the recommendation draft', error);
      notificationStore.error(failureMessage(error), 5000);
    } finally {
      busyId = null;
    }
  }

</script>

<RecommendationsCard {items} {category} {busyId} {statusText}
  onAction={(item) => void handleAction(item)} />
