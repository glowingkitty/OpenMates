<!--
  frontend/packages/ui/src/components/embeds/electronics/ElectronicsSearchEmbedPreview.svelte

  Preview component for the Electronics Search Components skill embed.
  Uses UnifiedEmbedPreview and mirrors the established search embed pattern.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';

  interface ComponentResult {
    part_number?: string;
    base_part_number?: string;
    title?: string;
    provider?: string;
    topology?: string | null;
    package?: string | null;
    bom_cost_usd?: number | null;
    efficiency_percent?: number | null;
    results?: ComponentResult[];
  }

  interface Props {
    id: string;
    query?: string;
    provider?: string;
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    results?: ComponentResult[];
    taskId?: string;
    skillTaskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    query: queryProp,
    provider: providerProp,
    status: statusProp,
    results: resultsProp,
    taskId: taskIdProp,
    skillTaskId: skillTaskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  let localQuery = $state('Power converters');
  let localProvider = $state('TI WEBENCH');
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let localResults = $state<ComponentResult[]>([]);
  let localErrorMessage = $state('');
  let localTaskId = $state<string | undefined>(undefined);
  let localSkillTaskId = $state<string | undefined>(undefined);
  let storeResolved = $state(false);

  $effect(() => {
    if (!storeResolved) {
      localQuery = queryProp || 'Power converters';
      localProvider = providerProp || 'TI WEBENCH';
      localStatus = statusProp || 'processing';
      localResults = resultsProp || [];
      localTaskId = taskIdProp;
      localSkillTaskId = skillTaskIdProp;
      localErrorMessage = '';
    }
  });

  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let status = $derived(localStatus);
  let results = $derived(localResults);
  let taskId = $derived(localTaskId);
  let skillTaskId = $derived(localSkillTaskId);
  let errorMessage = $derived(localErrorMessage || $text('chat.an_error_occured'));
  let skillName = $derived($text('embeds.electronics.search_components'));

  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    if (data.status !== 'processing') storeResolved = true;

    const content = data.decodedContent;
    if (typeof content.query === 'string') localQuery = content.query;
    if (typeof content.provider === 'string') localProvider = content.provider;
    if (typeof content.error === 'string') localErrorMessage = content.error;
    if (typeof content.skill_task_id === 'string') localSkillTaskId = content.skill_task_id;
    if (Array.isArray(content.results)) localResults = content.results as ComponentResult[];
  }

  function flattenResults(rawResults: ComponentResult[]): ComponentResult[] {
    if (!rawResults || rawResults.length === 0) return [];
    const flattened: ComponentResult[] = [];
    for (const entry of rawResults) {
      if (Array.isArray(entry.results)) {
        flattened.push(...entry.results);
      } else {
        flattened.push(entry);
      }
    }
    return flattened;
  }

  let flatResults = $derived(flattenResults(results));
  let componentCount = $derived(flatResults.length);
  let bestEfficiency = $derived.by(() => {
    const values = flatResults
      .map((result) => result.efficiency_percent)
      .filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
    if (values.length === 0) return '';
    return `${Math.max(...values).toFixed(1)}% ${$text('embeds.electronics.efficiency')}`;
  });

  async function handleStop() {
    if (status !== 'processing') return;
    if (skillTaskId) {
      try {
        await chatSyncService.sendCancelSkill(skillTaskId, id);
      } catch (error) {
        console.error('[ElectronicsSearchEmbedPreview] Failed to cancel skill:', error);
      }
    } else if (taskId) {
      try {
        await chatSyncService.sendCancelAiTask(taskId);
      } catch (error) {
        console.error('[ElectronicsSearchEmbedPreview] Failed to cancel task:', error);
      }
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="electronics"
  skillId="search_components"
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
    <div class="electronics-search-details" class:mobile={isMobileLayout}>
      <div class="ds-search-query">{query}</div>
      <div class="ds-search-provider">{$text('embeds.via')} {provider}</div>

      {#if status === 'error'}
        <div class="search-error">
          <div class="ds-search-error-title">{$text('embeds.search_failed')}</div>
          <div class="search-error-message">{errorMessage}</div>
        </div>
      {:else if status === 'finished'}
        <div class="ds-search-results-info">
          {#if componentCount > 0}
            <span class="component-count">
              {componentCount} {componentCount === 1 ? $text('embeds.electronics.component') : $text('embeds.electronics.components')}
            </span>
          {/if}
          {#if bestEfficiency}
            <span class="metric-info">{bestEfficiency}</span>
          {/if}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .electronics-search-details {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    height: 100%;
  }

  .electronics-search-details:not(.mobile) {
    justify-content: center;
  }

  .electronics-search-details.mobile {
    justify-content: flex-start;
  }

  .electronics-search-details.mobile .ds-search-query {
    font-size: var(--font-size-small);
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }

  .component-count {
    font-size: var(--font-size-small);
    color: var(--color-grey-70);
    font-weight: 500;
  }

  .metric-info {
    font-size: var(--font-size-small);
    color: var(--color-primary);
    font-weight: 600;
  }

  .search-error {
    margin-top: var(--spacing-3);
    padding: var(--spacing-4) var(--spacing-5);
    border-radius: var(--radius-5);
    background-color: rgba(var(--color-error-rgb), 0.08);
    border: 1px solid rgba(var(--color-error-rgb), 0.3);
  }

  .search-error-message {
    margin-top: var(--spacing-1);
    font-size: var(--font-size-xxs);
    color: var(--color-grey-70);
    line-height: 1.4;
    word-break: break-word;
  }
</style>
