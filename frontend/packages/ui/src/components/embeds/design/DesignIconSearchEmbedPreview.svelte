<!--
  frontend/packages/ui/src/components/embeds/design/DesignIconSearchEmbedPreview.svelte

  Preview component for the Design app icon search skill.
  Mirrors existing search previews with query, provider, status, and result count.

  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { chatSyncService } from '../../../services/chatSyncService';

  interface Props {
    id: string;
    query?: string;
    provider?: string;
    result_count?: number;
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    taskId?: string;
    skillTaskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    query: queryProp,
    provider: providerProp,
    result_count: resultCountProp,
    status: statusProp,
    taskId: taskIdProp,
    skillTaskId: skillTaskIdProp,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let localQuery = $state('Icons');
  let localProvider = $state('Iconify');
  let localResultCount = $state<number | undefined>(undefined);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let localErrorMessage = $state('');
  let localTaskId = $state<string | undefined>(undefined);
  let localSkillTaskId = $state<string | undefined>(undefined);
  let storeResolved = $state(false);

  $effect(() => {
    if (!storeResolved) {
      localQuery = queryProp || 'Icons';
      localProvider = providerProp || 'Iconify';
      localResultCount = resultCountProp;
      localStatus = statusProp || 'processing';
      localTaskId = taskIdProp;
      localSkillTaskId = skillTaskIdProp;
      localErrorMessage = '';
    }
  });

  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let resultCount = $derived(localResultCount);
  let status = $derived(localStatus);
  let taskId = $derived(localTaskId);
  let skillTaskId = $derived(localSkillTaskId);
  let skillName = $derived('Search icons');

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    if (data.status !== 'processing') storeResolved = true;

    const content = data.decodedContent;
    if (typeof content.query === 'string') localQuery = content.query;
    if (typeof content.provider === 'string') localProvider = content.provider;
    if (typeof content.result_count === 'number') localResultCount = content.result_count;
    if (typeof content.error === 'string') localErrorMessage = content.error;
    if (typeof content.skill_task_id === 'string') localSkillTaskId = content.skill_task_id;
  }

  async function handleStop() {
    if (status !== 'processing') return;
    if (skillTaskId) {
      await chatSyncService.sendCancelSkill(skillTaskId, id);
    } else if (taskId) {
      await chatSyncService.sendCancelAiTask(taskId);
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="design"
  skillId="search_icons"
  skillIconName="search"
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="design-search-details" class:mobile={isMobileLayout}>
      <div class="ds-search-query">{query}</div>
      <div class="ds-search-provider">via {provider}</div>

      {#if status === 'error'}
        <div class="search-error">
          <div class="ds-search-error-title">Search failed</div>
          <div class="search-error-message">{localErrorMessage || 'Icon search failed.'}</div>
        </div>
      {:else if status === 'finished' && resultCount}
        <div class="ds-search-results-info">{resultCount} icons</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .design-search-details {
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: var(--spacing-2);
    height: 100%;
  }

  .design-search-details.mobile {
    justify-content: flex-start;
  }

  .search-error-message,
  .ds-search-results-info {
    color: var(--color-grey-70);
    font-size: var(--font-size-small);
  }
</style>
