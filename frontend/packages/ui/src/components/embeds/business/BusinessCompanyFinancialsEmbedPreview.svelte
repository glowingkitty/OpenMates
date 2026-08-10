<!--
  frontend/packages/ui/src/components/embeds/business/BusinessCompanyFinancialsEmbedPreview.svelte

  Parent preview for Business / Get company financials. Child SEC result cards
  are loaded only in fullscreen or as direct child embeds.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { getParentPreviewResultState, normalizeEmbedIdList } from '../embedPreviewHydration';

  interface Props {
    id: string;
    query?: string;
    provider?: string;
    period?: string;
    metricGroup?: string;
    status: 'processing' | 'finished' | 'error' | 'cancelled';
    resultCount?: number;
    results?: unknown[];
    childEmbedIds?: string[] | string;
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    query = '',
    provider = 'SEC EDGAR',
    period = 'latest_annual',
    metricGroup = 'summary',
    status,
    resultCount,
    results = [],
    childEmbedIds = [],
    taskId,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  const skillName = $text('app_skills.business.company_financials');
  let childIds = $derived(normalizeEmbedIdList(childEmbedIds));
  let resultState = $derived(getParentPreviewResultState({
    status,
    previewResultCount: results.length,
    resultCount,
    childEmbedIds: childIds,
  }));
  let displayCount = $derived(resultCount ?? results.length ?? childIds.length);
  let periodLabel = $derived(formatPeriod(period));

  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> | null }) {
    if (!data.decodedContent) return;
    const content = data.decodedContent;
    if (typeof content.query === 'string') query = content.query;
    if (typeof content.provider === 'string') provider = content.provider;
    if (typeof content.period === 'string') period = content.period;
    if (typeof content.metric_group === 'string') metricGroup = content.metric_group;
    if (typeof content.result_count === 'number') resultCount = content.result_count;
    if (Array.isArray(content.results)) results = content.results;
  }

  function formatPeriod(value: string): string {
    return value.replace(/_/g, ' ');
  }

  function handleStop() {
    // SEC EDGAR lookups are synchronous and not cancellable from the preview.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="business"
  skillId="company_financials"
  skillIconName="business"
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={true}
  showSkillIcon={true}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details()}
    <div class="business-financials-preview" data-testid="business-financials-preview">
      <div class="query">{query || skillName}</div>
      <div class="meta">
        {#if resultState === 'no-results'}
          {$text('embeds.business.company_financials.no_results')}
        {:else if resultState === 'open-to-view'}
          {$text('embeds.business.company_financials.open_to_view')}
        {:else}
          {$text('embeds.business.company_financials.results_count', { values: { count: displayCount } })} · {$text('embeds.via')} {provider}
        {/if}
      </div>
      <div class="chips" aria-label="Financial query options">
        <span>{periodLabel}</span>
        <span>{metricGroup.replace(/_/g, ' ')}</span>
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .business-financials-preview {
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 8px;
    min-height: 100%;
  }

  .query {
    overflow: hidden;
    color: var(--color-font-primary);
    font-size: var(--font-size-sm);
    font-weight: 650;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .meta {
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
  }

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .chips span {
    border-radius: 999px;
    background: color-mix(in srgb, var(--color-app-business) 12%, var(--color-grey-10));
    color: var(--color-font-secondary);
    font-size: 11px;
    padding: 4px 8px;
    text-transform: capitalize;
  }
</style>
