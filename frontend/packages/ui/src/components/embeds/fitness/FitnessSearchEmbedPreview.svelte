<!--
  frontend/packages/ui/src/components/embeds/fitness/FitnessSearchEmbedPreview.svelte

  Preview component for Fitness Urban Sports search embeds.
  Uses UnifiedEmbedPreview and mirrors the compact event-search card pattern:
  query/location summary, provider, result count, plan/mode filters, and top
  result snippets while the full result list stays in fullscreen.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';

  interface FitnessResult {
    name?: string;
    venue_name?: string;
    date?: string;
    time_range?: string;
    distance_km?: number;
    plans_required?: string[];
  }

  interface Props {
    id: string;
    skillId: 'search_locations' | 'search_classes';
    query?: string;
    provider?: string;
    summary?: string;
    filters?: Record<string, unknown>;
    status: 'processing' | 'finished' | 'error' | 'cancelled';
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
    provider: providerProp = 'Urban Sports Club',
    summary: summaryProp = '',
    filters: filtersProp = {},
    status: statusProp,
    results: resultsProp = [],
    result_count: resultCountProp = 0,
    taskId,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let localQuery = $state('');
  let localProvider = $state('Urban Sports Club');
  let localSummary = $state('');
  let localFilters = $state<Record<string, unknown>>({});
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let localResults = $state<FitnessResult[]>([]);
  let localResultCount = $state(0);

  $effect(() => {
    localQuery = queryProp || '';
    localProvider = providerProp || 'Urban Sports Club';
    localSummary = summaryProp || '';
    localFilters = filtersProp || {};
    localStatus = statusProp || 'processing';
    localResults = resultsProp || [];
    localResultCount = resultCountProp || resultsProp.length || 0;
  });

  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    const firstGroup = Array.isArray(data.decodedContent?.results)
      ? data.decodedContent.results[0] as Record<string, unknown> | undefined
      : undefined;
    if (firstGroup) {
      if (typeof firstGroup.summary === 'string') localSummary = firstGroup.summary;
      if (typeof firstGroup.provider === 'string') localProvider = firstGroup.provider;
      if (typeof firstGroup.result_count === 'number') localResultCount = firstGroup.result_count;
      if (firstGroup.filters && typeof firstGroup.filters === 'object') localFilters = firstGroup.filters as Record<string, unknown>;
      if (Array.isArray(firstGroup.results)) localResults = firstGroup.results as FitnessResult[];
    }
  }

  let title = $derived(skillId === 'search_classes' ? 'Fitness classes' : 'Fitness locations');
  let countLabel = $derived(`${localResultCount} ${skillId === 'search_classes' ? 'classes' : 'locations'}`);
  let locationLabel = $derived(String(localFilters.address || localFilters.city || localQuery || 'Urban Sports'));
  let filterChips = $derived.by(() => {
    const chips = [];
    if (localFilters.radius_km) chips.push(`${localFilters.radius_km} km`);
    if (localFilters.plan) chips.push(`Plan: ${localFilters.plan}`);
    if (localFilters.attendance_mode) chips.push(String(localFilters.attendance_mode));
    return chips;
  });
</script>

{#snippet details()}
  <div class="fitness-search-preview" data-testid="fitness-search-preview" data-skill-id={skillId}>
    <div class="fitness-search-kicker">{localProvider}</div>
    <div class="fitness-search-title">{title}</div>
    <div class="fitness-search-location">{locationLabel}</div>
    {#if localStatus === 'finished'}
      <div class="fitness-search-count" data-testid="fitness-search-result-count">{countLabel}</div>
      {#if localSummary}
        <div class="fitness-search-summary">{localSummary}</div>
      {/if}
      {#if localResults.length > 0}
        <div class="fitness-search-results">
          {#each localResults.slice(0, 2) as result}
            <div class="fitness-search-result">
              <span>{result.name}</span>
              {#if result.venue_name}<small>{result.venue_name}</small>{/if}
            </div>
          {/each}
        </div>
      {/if}
    {:else if localStatus === 'error'}
      <div class="fitness-search-summary">Search failed.</div>
    {:else if localStatus === 'cancelled'}
      <div class="fitness-search-summary">Search cancelled.</div>
    {:else}
      <div class="fitness-search-summary">Searching Urban Sports Club...</div>
    {/if}
    {#if filterChips.length > 0}
      <div class="fitness-search-chips">
        {#each filterChips as chip}<span>{chip}</span>{/each}
      </div>
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
  .fitness-search-preview {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    height: 100%;
  }

  .fitness-search-kicker,
  .fitness-search-summary,
  .fitness-search-location,
  .fitness-search-result small {
    color: var(--color-font-secondary, #666);
    font-size: 0.78rem;
  }

  .fitness-search-title {
    color: var(--color-font-primary, #111);
    font-size: 1rem;
    font-weight: 700;
  }

  .fitness-search-count {
    color: var(--color-font-primary, #111);
    font-weight: 650;
  }

  .fitness-search-results {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    overflow: hidden;
  }

  .fitness-search-result {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .fitness-search-result span,
  .fitness-search-result small,
  .fitness-search-location,
  .fitness-search-summary {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .fitness-search-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    margin-top: auto;
  }

  .fitness-search-chips span {
    border: 1px solid var(--color-grey-30, #d8d8d8);
    border-radius: 999px;
    color: var(--color-font-secondary, #666);
    font-size: 0.7rem;
    padding: 0.1rem 0.4rem;
  }
</style>
