<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData, EmbedFullscreenCommonProps } from '../../../types/embedFullscreen';
  import { normalizeTrademarkSearch, string, strings, trademarkSourceUrl } from './trademarkSearchContent';
  interface Props extends EmbedFullscreenCommonProps { data: EmbedFullscreenRawData; }
  let { data, onClose, embedId, hasPreviousEmbed = false, hasNextEmbed = false,
    onNavigatePrevious, onNavigateNext, navigateDirection, showChatButton = false, onShowChat }: Props = $props();
  let content = $derived(data.decodedContent ?? {});
  let search = $derived(normalizeTrademarkSearch(content));
  const prefix = 'embeds.business.search_trademarks.';
  function statusLabel(value: unknown): string {
    const status = string(value);
    return $text(prefix + (['registered', 'pending', 'ended', 'unknown'].includes(status) ? status : 'unknown'));
  }
  function date(value: unknown): string {
    const raw = string(value);
    const parsed = new Date(raw);
    return raw && !Number.isNaN(parsed.valueOf()) ? parsed.toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'}) : raw;
  }
  function updated(value: {status: string; decodedContent: Record<string, unknown>}) { data = {...data, decodedContent: value.decodedContent}; }
</script>

<UnifiedEmbedFullscreen testId="trademark-search-fullscreen" appId="business" skillId="search_trademarks"
  skillIconName="business" embedHeaderTitle={search.query || $text('app_skills.business.search_trademarks')}
  embedHeaderSubtitle={$text(prefix + 'preliminary')} {onClose} currentEmbedId={embedId}
  {hasPreviousEmbed} {hasNextEmbed} {onNavigatePrevious} {onNavigateNext}
  navigateDirection={navigateDirection ?? undefined} {showChatButton} {onShowChat} onEmbedDataUpdated={updated}>
  {#snippet content()}
    <div class="body">
      <p class="notice" data-testid="trademark-fullscreen-limitation">{$text(prefix + 'limitation')}</p>
      {#if search.error}<p class="error" data-testid="trademark-error">{search.error}</p>{/if}
      {#if search.hasData}
        <div class="filters" data-testid="trademark-search-filters">
          {#if search.match}<span>{$text(prefix + (search.match === 'exact' ? 'exact' : 'similar'))}</span>{/if}
          {#if search.statusFilter}<span>{$text(prefix + (search.statusFilter === 'all' ? 'all_statuses' : 'active'))}</span>{/if}
          <span>{$text(prefix + 'classes')}: {search.niceClasses.length ? search.niceClasses.join(', ') : $text(prefix + 'all_classes')}</span>
        </div>
        <section class="coverage" aria-label={$text('embeds.coverage')} data-testid="trademark-search-coverage">
          <h3>{$text('embeds.coverage')}</h3>
          {#each search.coverage as row}
            {@const source = trademarkSourceUrl(row.source_url)}
            <article class="coverage-row">
              <strong>{string(row.query)} · {string(row.region)}</strong>
              <span>{$text(prefix + (row.status === 'searched' ? 'checked' : row.status === 'partial' ? 'partial' : 'not_searched'))}</span>
              {#if row.checked_at}<small>{$text(prefix + 'checked')}: {date(row.checked_at)}</small>{/if}
              {#if typeof row.total_matches === 'number'}<small>{$text(prefix + 'records', {values: {count: row.total_matches}})}</small>{/if}
              {#if row.more_results === true || row.more_results === 'true'}<small>{$text(prefix + 'more')}</small>{/if}
              {#if row.message}<p>{string(row.message)}</p>{/if}
              {#if source}<a href={source} target="_blank" rel="noopener noreferrer">{$text(prefix + 'open_register')}</a>{/if}
            </article>
          {/each}
        </section>
        <h3>{$text(prefix + 'records', {values: {count: search.count}})}</h3>
        {#if search.matches.length === 0 && !search.error && search.coverage.some(row => row.status === 'searched')}<p data-testid="trademark-empty">{$text(prefix + 'empty')}</p>{/if}
        <div class="records" data-testid="trademark-record-grid">
          {#each search.matches as row}
            {@const source = trademarkSourceUrl(row.source_url)}
            <article class="record" data-testid="trademark-record">
              <h3>{string(row.mark)}</h3>
              <span class="status">{statusLabel(row.status)} · {string(row.region)}</span>
              {#if row.status_description}<p>{string(row.status_description)}</p>{/if}
              {#if strings(row.owners).length}<p><strong>{$text(prefix + 'owner')}:</strong> {strings(row.owners).join('; ')}</p>{/if}
              <p><strong>{$text(prefix + 'classes')}:</strong> {strings(row.nice_classes).join(', ') || '—'}</p>
              <p>{$text(prefix + 'application')}: {string(row.application_number)}</p>
              {#if row.registration_number}<p>{$text(prefix + 'registration')}: {string(row.registration_number)}</p>{/if}
              {#if row.filing_date}<p>{$text(prefix + 'filed')}: {string(row.filing_date)}</p>{/if}
              {#if row.registration_date}<p>{$text(prefix + 'registered')}: {string(row.registration_date)}</p>{/if}
              {#if strings(row.goods_services).length}
                <details><summary>{$text(prefix + 'goods')}</summary>
                  {#each strings(row.goods_services) as goods}<p>{goods}</p>{/each}
                </details>
              {/if}
              {#if source}<a href={source} target="_blank" rel="noopener noreferrer" data-testid="trademark-record-source">{$text(prefix + 'open_record')}</a>{/if}
            </article>
          {/each}
        </div>
      {:else if !search.error}
        <p>{$text(prefix + 'failed')}</p>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .body { padding: var(--spacing-8); min-width: 0; color: var(--color-font-primary); }
  .notice { padding: var(--spacing-6); border-radius: var(--radius-3); background: var(--color-grey-20); font-size: var(--font-size-small); }
  .error { color: var(--color-error); }
  .filters { display: flex; flex-wrap: wrap; gap: var(--spacing-4); margin-block: var(--spacing-8); font-size: var(--font-size-small); }
  .filters span, .status { padding: var(--spacing-2) var(--spacing-4); background: var(--color-grey-20); border-radius: var(--radius-3); }
  .coverage { margin-bottom: var(--spacing-12); }
  .coverage-row { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--spacing-4); padding-block: var(--spacing-6); border-bottom: 1px solid var(--color-grey-30); overflow-wrap: anywhere; font-size: var(--font-size-small); }
  .coverage-row p { flex-basis: 100%; margin: 0; }
  .coverage-row small { color: var(--color-font-tertiary); }
  .records { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); gap: var(--spacing-8); }
  .record { min-width: 0; padding: var(--spacing-8); border: 1px solid var(--color-grey-30); border-radius: var(--radius-3); background: var(--color-grey-10); overflow-wrap: anywhere; font-size: var(--font-size-small); }
  h3 { margin: 0 0 var(--spacing-6); font-size: var(--font-size-h4); }
  .record p { margin-block: var(--spacing-6); }
  details { margin-block: var(--spacing-8); }
  summary { cursor: pointer; }
  a { display: inline-block; color: var(--color-font-primary); text-decoration: underline; margin-block: var(--spacing-4); }
  a:focus-visible, summary:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 3px; }
</style>
