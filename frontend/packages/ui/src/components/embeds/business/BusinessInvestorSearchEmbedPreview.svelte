<!--
  frontend/packages/ui/src/components/embeds/business/BusinessInvestorSearchEmbedPreview.svelte

  Preview card for Business / Search investors: query, requested regions, result
  count and the first investor names with their type. The result list lives in
  the parent embed content; there are no child embeds.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { INVESTOR_TYPES, normalizeInvestorSearch } from './investorSearchContent';
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
  const prefix = 'embeds.business.search_investors.';
  const SHOWN = 3;
  let content = $derived(data);
  let search = $derived(normalizeInvestorSearch(content));
  let effectiveStatus = $derived(search.error ? 'error' : status);
  let unavailable = $derived(search.errorCode === 'provider_unavailable');
  let shown = $derived(search.investors.slice(0, SHOWN));
  function typeLabel(value: string): string {
    return (INVESTOR_TYPES as readonly string[]).includes(value) ? $text(prefix + 'type_' + value) : '';
  }
  function updated(value: { status: string; decodedContent: Record<string, unknown> }) {
    data = value.decodedContent;
    if (['processing', 'finished', 'error', 'cancelled'].includes(value.status)) status = value.status as Status;
  }
</script>

<UnifiedEmbedPreview {id} appId="business" skillId="search_investors" skillIconName="business"
  status={effectiveStatus} skillName={$text('app_skills.business.search_investors')}
  {taskId} {isMobile} {presentationOnly} showStatus={effectiveStatus === 'processing'}
  onFullscreen={() => onFullscreen(content)} onEmbedDataUpdated={updated}>
  {#snippet details()}
    <div class="summary" data-testid="investor-search-preview">
      <strong class="query">{search.query || query || $text('app_skills.business.search_investors')}</strong>
      {#if effectiveStatus === 'error'}
        <p class="notice" data-testid="investor-preview-error">{$text(prefix + (unavailable ? 'unavailable' : 'failed'))}</p>
      {:else if effectiveStatus === 'cancelled'}
        <p class="notice">{$text('embeds.cancelled')}</p>
      {:else if search.hasData}
        {#if search.regions.length}<p class="meta" data-testid="investor-preview-regions">{search.regions.join(' · ')}</p>{/if}
        <p class="count" data-testid="investor-preview-count">{$text(prefix + 'result_count', { values: { count: search.count } })}</p>
        {#if shown.length}
          <ul class="names" data-testid="investor-preview-names">
            {#each shown as investor}
              <li><span class="name">{investor.name}</span>{#if typeLabel(investor.investorType)}<span class="type">{typeLabel(investor.investorType)}</span>{/if}</li>
            {/each}
          </ul>
        {:else}
          <p class="notice" data-testid="investor-preview-empty">{$text(prefix + 'empty')}</p>
        {/if}
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .summary { display: flex; flex-direction: column; justify-content: center; gap: var(--spacing-3); min-height: 100%; min-width: 0; }
  .query { display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; color: var(--color-font-primary); font-size: var(--font-size-small); }
  p { margin: 0; }
  .count { color: var(--color-font-primary); font-size: var(--font-size-small); }
  .meta, .notice { color: var(--color-font-tertiary); font-size: var(--font-size-xs); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .names { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--spacing-2); min-width: 0; }
  .names li { display: flex; align-items: baseline; gap: var(--spacing-3); min-width: 0; font-size: var(--font-size-xs); }
  .name { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--color-font-primary); }
  .type { flex: 0 0 auto; color: var(--color-font-tertiary); white-space: nowrap; }
</style>
