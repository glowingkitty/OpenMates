<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { text } from '@repo/ui';
  import { userProfile } from '../../stores/userProfile';
  import { activeTeamContext } from '../../stores/teamStore';
  import { processingChatIds } from '../../stores/chatActivityStore';
  import { chatSyncService } from '../../services/chatSyncService';
  import { CHAT_METADATA_KEY_READY_EVENT } from '../../services/chatMetadataCache';
  import { loadProjectChatPresentation, type ProjectChatPresentation } from '../../services/projectChatPreviewService';
  import type { ProjectItemViewModel } from '../../services/projectService';
  import WorkspaceContinueCard from '../workspace/WorkspaceContinueCard.svelte';
  import ProcessingWheel from '../chats/ProcessingWheel.svelte';
  import { getResumeCardGradientStyle, getContinueGradientColors } from '../activeChatUtils';
  import { getLucideIcon, getValidIconName } from '../../utils/categoryUtils';

  let { item, viewMode = 'tile', presentation: suppliedPresentation, processing: suppliedProcessing }: {
    item: ProjectItemViewModel;
    viewMode?: 'tile' | 'list';
    presentation?: ProjectChatPresentation | null;
    processing?: boolean;
  } = $props();
  let presentation = $state<ProjectChatPresentation | null>(null);
  let loading = $state(true);
  let failed = $state(false);
  let request = 0;
  let processing = $derived(suppliedProcessing ?? $processingChatIds.has(item.target_id));
  let title = $derived(presentation?.title || item.displayName || $text('common.untitled_chat'));
  let href = $derived(presentation ? `/#chat-id=${encodeURIComponent(item.target_id)}${presentation.teamId ? `&team-id=${encodeURIComponent(presentation.teamId)}` : ''}` : null);
  let iconName = $derived(getValidIconName(presentation?.icon || '', presentation?.category || 'general_knowledge'));
  let IconComponent = $derived(getLucideIcon(iconName));

  async function refresh(force = false): Promise<void> {
    const current = ++request;
    loading = true; failed = false; presentation = null;
    try {
      const result = suppliedPresentation !== undefined ? suppliedPresentation : await loadProjectChatPresentation(item.target_id, force);
      if (current === request) presentation = result;
    } catch {
      if (current === request) failed = true;
    } finally {
      if (current === request) loading = false;
    }
  }
  $effect(() => {
    // Re-read on an account or team epoch change before presenting local metadata.
    void item.target_id; void suppliedPresentation; void $userProfile.user_id; void $activeTeamContext.epoch;
    untrack(() => { void refresh(); });
    return () => { request += 1; };
  });
  onMount(() => {
    const changed = (event: Event) => {
      const detail = (event as CustomEvent<{ chat_id?: string; chatId?: string }>).detail;
      if ((detail?.chat_id ?? detail?.chatId) === item.target_id) void refresh(true);
    };
    chatSyncService.addEventListener('chatUpdated', changed);
    chatSyncService.addEventListener('chatDeleted', changed);
    window.addEventListener(CHAT_METADATA_KEY_READY_EVENT, changed);
    return () => {
      request += 1;
      chatSyncService.removeEventListener('chatUpdated', changed);
      chatSyncService.removeEventListener('chatDeleted', changed);
      window.removeEventListener(CHAT_METADATA_KEY_READY_EVENT, changed);
    };
  });
</script>

<div class="project-chat-preview" class:list={viewMode === 'list'} data-testid="project-chat-preview" data-chat-id={item.target_id}>
  {#if loading || !presentation}
    <div class="chat-state" class:list={viewMode === 'list'} aria-busy={loading} data-testid="project-chat-state">
      <span>{loading ? $text('common.loading') : $text('common.detail_load_error', { values: { item: $text('common.chat') } })}</span>
      {#if failed}<button type="button" onclick={() => void refresh(true)}>{$text('common.retry')}</button>{/if}
    </div>
  {:else if viewMode === 'tile'}
    <WorkspaceContinueCard {title} summary={presentation.summary} badge={$text('common.chat')} category={presentation.category}
      appId={null} icon={presentation.icon} testId="project-chat-card" {href} source={null} fluid={true} onActivate={null} {processing} />
  {:else}
    <a class="chat-list-card" class:processing data-testid="project-chat-card" data-category={presentation.category}
      style={processing ? '' : getResumeCardGradientStyle(getContinueGradientColors(presentation.category, null))} {href}>
      {#if processing}<ProcessingWheel />{:else}<IconComponent size={24} aria-hidden="true" />{/if}
      <span class="chat-list-content"><strong>{title}</strong>{#if presentation.summary}<small>{presentation.summary}</small>{/if}</span>
    </a>
  {/if}
</div>

<style>
  .project-chat-preview { width: min(100%, 300px); min-width: 0; margin-inline: auto; }
  .project-chat-preview.list { width: 100%; }
  .chat-state { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--spacing-4); width: 100%; height: 200px; border-radius: 30px; background: var(--color-grey-10); color: var(--color-font-secondary); }
  .chat-state.list { height: 78px; border-radius: var(--radius-5); }
  .chat-list-card { box-sizing: border-box; display: flex; align-items: center; gap: var(--spacing-6); min-height: 78px; padding: var(--spacing-5) var(--spacing-8); border-radius: var(--radius-8); color: var(--color-font-button); text-decoration: none; overflow: hidden; }
  .chat-list-content { display: flex; flex-direction: column; gap: var(--spacing-2); min-width: 0; }
  .chat-list-content strong, .chat-list-content small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .chat-list-content strong { font-size: var(--font-size-p); }
  .chat-list-content small { font-size: var(--font-size-xxs); }
  .chat-list-card.processing { background: var(--color-grey-10); color: var(--color-font-primary); }
  .chat-list-card:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
</style>
