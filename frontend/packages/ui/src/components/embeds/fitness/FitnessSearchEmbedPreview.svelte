<!--
  frontend/packages/ui/src/components/embeds/fitness/FitnessSearchEmbedPreview.svelte

  Preview component for Fitness fitness source search embeds.
  Uses UnifiedEmbedPreview and mirrors the compact event-search card pattern:
  query/location summary, provider, result count, plan/mode filters, and top
  result snippets while the full result list stays in fullscreen.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import {
    asText,
    normalizeFitnessSearchContent,
    type FitnessResult,
    type FitnessSkillId,
    type FitnessStatus,
  } from './fitnessEmbedData';

  interface Props {
    id: string;
    skillId: FitnessSkillId;
    query?: string;
    provider?: string;
    summary?: string;
    filters?: Record<string, unknown>;
    status: FitnessStatus;
    results?: FitnessResult[];
    result_count?: number;
    taskId?: string;
    skillTaskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    skillId,
    query: queryProp = '',
    provider: providerProp = '',
    filters: filtersProp = {},
    status: statusProp,
    results: resultsProp = [],
    result_count: resultCountProp,
    taskId,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let localQuery = $state('');
  let localProvider = $state('');
  let localStatus = $state<FitnessStatus>('processing');
  let localResultCount = $state(0);

  $effect(() => {
    localQuery = queryProp || asText(filtersProp.query || filtersProp.address || filtersProp.city);
    localProvider = providerProp || '';
    localStatus = statusProp || 'processing';
    localResultCount = resultCountProp ?? resultsProp.length;
  });

  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    const normalized = normalizeFitnessSearchContent(data.decodedContent, skillId);
    localStatus = data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled'
      ? data.status
      : normalized.status;
    localQuery = normalized.query || localQuery;
    localProvider = normalized.provider;
    localResultCount = normalized.resultCount;
  }

  let title = $derived(skillId === 'search_classes' ? $text('app_skills.fitness.search_classes') : $text('app_skills.fitness.search_locations'));
  let countLabel = $derived(`${localResultCount} ${skillId === 'search_classes' ? 'classes' : 'locations'}`);
</script>

{#snippet details()}
  <div class="fitness-search-preview" data-testid="fitness-search-preview" data-skill-id={skillId}>
    <div class="fitness-search-query" title={localQuery}>{localQuery || title}</div>
    <div class="fitness-search-provider" title={localProvider}>{localProvider}</div>
    {#if localStatus === 'finished'}
      <div class="fitness-search-count" data-testid="fitness-search-result-count">{countLabel}</div>
    {:else if localStatus === 'error'}<div class="fitness-search-status">Search failed.</div>
    {:else if localStatus === 'cancelled'}<div class="fitness-search-status">Search cancelled.</div>
    {/if}
  </div>
{/snippet}

<UnifiedEmbedPreview
  {id}
  appId="fitness"
  {skillId}
  appIconName="fitness"
  skillIconName="search"
  status={localStatus}
  skillName={title}
  {taskId}
  {isMobile}
  {onFullscreen}
  {details}
  onEmbedDataUpdated={handleEmbedDataUpdated}
/>

<style>
  .fitness-search-preview { display:flex; flex-direction:column; justify-content:center; gap:var(--spacing-3); min-width:0; height:100%; }
  .fitness-search-query { color:var(--color-font-primary); font-size:var(--font-size-small); font-weight:600; line-height:1.3; overflow:hidden; display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2; line-clamp:2; overflow-wrap:anywhere; }
  .fitness-search-provider, .fitness-search-count, .fitness-search-status { color:var(--color-font-secondary); font-size:var(--font-size-xs); line-height:1.3; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
</style>
