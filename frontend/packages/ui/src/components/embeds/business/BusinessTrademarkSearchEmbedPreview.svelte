<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { normalizeTrademarkSearch, string } from './trademarkSearchContent';
  type Status = 'processing' | 'finished' | 'error' | 'cancelled';
  interface Props {
    id: string;
    data?: Record<string, unknown>;
    query?: string;
    status: Status;
    taskId?: string;
    isMobile?: boolean;
    presentationOnly?: boolean;
    onFullscreen: (content?: Record<string, unknown>) => void;
  }
  let { id, data = {}, query = '', status, taskId, isMobile = false,
    presentationOnly = false, onFullscreen }: Props = $props();
  let content = $derived(data);
  let search = $derived(normalizeTrademarkSearch(content));
  let regions = $derived([...new Set(search.coverage.map(row => string(row.region)))]);
  let effectiveStatus = $derived(search.status === 'error' || search.status === 'cancelled'
    ? search.status as Status : status);
  const prefix = 'embeds.business.search_trademarks.';
  function regionState(region: string): string {
    const states = search.coverage.filter(row => row.region === region).map(row => row.status);
    return states.every(value => value === 'searched') ? 'checked'
      : states.every(value => value === 'unsupported' || value === 'error') ? 'not_searched' : 'partial';
  }
  function updated(value: {status: string; decodedContent: Record<string, unknown>}) {
    data = value.decodedContent;
    if (['processing', 'finished', 'error', 'cancelled'].includes(value.status)) status = value.status as Status;
  }
</script>

<UnifiedEmbedPreview {id} appId="business" skillId="search_trademarks" skillIconName="business"
  status={effectiveStatus} skillName={$text('app_skills.business.search_trademarks')}
  {taskId} {isMobile} {presentationOnly} showStatus={effectiveStatus === 'processing'}
  onFullscreen={() => onFullscreen(content)} onEmbedDataUpdated={updated}>
  {#snippet details()}
    <div class="summary" data-testid="trademark-search-preview">
      <strong class="query">{search.query || query || $text('app_skills.business.search_trademarks')}</strong>
      {#if effectiveStatus === 'error'}
        <p class="notice">{$text(prefix + 'failed')}</p>
      {:else if effectiveStatus === 'cancelled'}
        <p>{$text('embeds.cancelled')}</p>
      {:else if search.hasData}
        <p class="count">{$text(prefix + 'records', {values: {count: search.count}})} · {search.provider}</p>
        <div class="regions" data-testid="trademark-preview-coverage">
          {#each regions as region}<span>{region} · {$text(prefix + regionState(region))}</span>{/each}
        </div>
        <p class="notice" data-testid="trademark-preview-limitation">{$text(prefix + 'preliminary')}</p>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .summary { display: flex; flex-direction: column; justify-content: center; gap: var(--spacing-4); min-height: 100%; min-width: 0; }
  .query { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; color: var(--color-font-primary); font-size: var(--font-size-small); }
  p { margin: 0; }
  .count { color: var(--color-font-primary); font-size: var(--font-size-small); }
  .regions { display: flex; flex-wrap: wrap; gap: var(--spacing-3); }
  .regions span { padding: var(--spacing-2) var(--spacing-4); border-radius: var(--radius-3); background: var(--color-grey-20); color: var(--color-font-primary); font-size: var(--font-size-xs); }
  .notice { color: var(--color-font-tertiary); font-size: var(--font-size-xs); }
</style>
