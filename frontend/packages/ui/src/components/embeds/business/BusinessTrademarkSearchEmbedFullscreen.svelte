<script lang="ts">
  import { text } from '@repo/ui';
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import type { EmbedFullscreenRawData, EmbedFullscreenCommonProps } from '../../../types/embedFullscreen';
  import { normalizeTrademarkSearch, string, strings, trademarkSourceUrl } from './trademarkSearchContent';
  interface Props extends EmbedFullscreenCommonProps { data: EmbedFullscreenRawData; }
  let { data, onClose, embedId, hasPreviousEmbed = false, hasNextEmbed = false,
    onNavigatePrevious, onNavigateNext, navigateDirection, showChatButton = false, onShowChat }: Props = $props();
  let content = $derived(data.decodedContent ?? {});
  let search = $derived(normalizeTrademarkSearch(content));
  type TrademarkResult = Record<string, unknown> & { embed_id: string };
  const records = $derived(search.matches.map((row, index) => ({ ...row, embed_id: `legacy-trademark-${index}` })));
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

<SearchResultsTemplate testId="trademark-search-fullscreen" appId="business" skillId="search_trademarks"
  skillIconName="business" embedHeaderTitle={search.query || $text('app_skills.business.search_trademarks')}
  embedHeaderSubtitle={$text(prefix + 'preliminary')} {onClose} currentEmbedId={embedId}
  {hasPreviousEmbed} {hasNextEmbed} {onNavigatePrevious} {onNavigateNext}
  navigateDirection={navigateDirection ?? undefined} {showChatButton} {onShowChat} onEmbedDataUpdated={updated}
  localResults={true}
  legacyResults={records} legacyResultTransformer={items => items as TrademarkResult[]}
  emptyTestId={search.error ? "trademark-failed" : "trademark-empty"} status="finished"
  filters={{ controls: filterControls, notices: coverageNotices, matches: () => true }}>
  {#snippet filterControls()}        <div class="filters" data-testid="trademark-search-filters">
          {#if search.match}<span>{$text(prefix + (search.match === 'exact' ? 'exact' : 'similar'))}</span>{/if}
          {#if search.statusFilter}<span>{$text(prefix + (search.statusFilter === 'all' ? 'all_statuses' : 'active'))}</span>{/if}
          <span>{$text(prefix + 'classes')}: {search.niceClasses.length ? search.niceClasses.join(', ') : $text(prefix + 'all_classes')}</span>
        </div>
{/snippet}
  {#snippet coverageNotices()}<div class="body">      <p class="notice" data-testid="trademark-fullscreen-limitation">{$text(prefix + 'limitation')}</p>
      {#if search.error}<p class="error" data-testid="trademark-error">{search.error}</p>{/if}
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
</div>{/snippet}
  {#snippet emptyContent()}
    {#if search.error}<p>{$text(prefix + 'failed')}</p>{:else if search.hasData}<p>{$text(prefix + 'empty')}</p>{:else}<p>{$text(prefix + 'failed')}</p>{/if}
  {/snippet}
  {#snippet resultCard({ result: row, onSelect })}
    <div data-testid="trademark-record" class="record-card">
      <UnifiedEmbedPreview id={row.embed_id} appId="business" skillId="search_trademarks" skillIconName="business" skillName={string(row.mark)} status="finished" resultPreview={true} presentationOnly={true} showStatus={false} onFullscreen={onSelect}>
        {#snippet details()}
          <ResultEmbedCard title={string(row.mark) || search.query} sourceLabel={strings(row.owners).join('; ') || string(row.provider)} description={[statusLabel(row.status), string(row.region), string(row.application_number)].filter(Boolean).join(' · ')} textFirst={true}>
            {#snippet facts()}
              <ResultEmbedInfo icon="Scale" label={statusLabel(row.status)} value={statusLabel(row.status)}>{#snippet children()}{string(row.status_description) || statusLabel(row.status)}{/snippet}</ResultEmbedInfo>
              {#if strings(row.nice_classes).length}<ResultEmbedInfo icon="Tags" label={$text(prefix + 'classes')} value={strings(row.nice_classes).join(', ')}>{#snippet children()}{strings(row.nice_classes).join(', ')}{/snippet}</ResultEmbedInfo>{/if}
            {/snippet}
          </ResultEmbedCard>
        {/snippet}
      </UnifiedEmbedPreview>
    </div>
  {/snippet}
  {#snippet childFullscreen({ result: row, onClose: closeRecord, hasPrevious, hasNext, onPrevious, onNext })}
    {@const source = trademarkSourceUrl(row.source_url)}
    <ResultEmbedFullscreen testId="trademark-record-fullscreen" appId="business" skillId="search_trademarks" skillIconName="business" embedHeaderTitle={string(row.mark)} embedHeaderSubtitle={[string(row.provider), string(row.region)].filter(Boolean).join(' · ')} onClose={closeRecord} showShare={false} hasPreviousEmbed={hasPrevious} hasNextEmbed={hasNext} onNavigatePrevious={onPrevious} onNavigateNext={onNext}
      result={Object.fromEntries(['mark', 'region', 'provider', 'application_number', 'registration_number', 'owners', 'nice_classes', 'goods_services', 'status', 'status_description', 'source_url', 'filing_date', 'registration_date'].filter(key => row[key] !== undefined).map(key => [key, row[key]]))}>
      {#snippet embedHeaderCta()}{#if source}<EmbedHeaderCtaButton href={source} label={$text(prefix + 'open_record')} testId="trademark-record-source" />{/if}{/snippet}
      {#snippet summary()}
        <ResultEmbedInfo icon="Scale" label={statusLabel(row.status)} value={statusLabel(row.status)}>{#snippet children()}{string(row.status_description)}{/snippet}</ResultEmbedInfo>
        {#if strings(row.nice_classes).length}<ResultEmbedInfo icon="Tags" label={$text(prefix + 'classes')} value={strings(row.nice_classes).join(', ')}>{#snippet children()}{strings(row.nice_classes).join(', ')}{/snippet}</ResultEmbedInfo>{/if}
      {/snippet}
      {#snippet detailContent()}
        <article class="record" data-testid="trademark-record-detail">
          {#if strings(row.owners).length}<p><strong>{$text(prefix + 'owner')}:</strong> {strings(row.owners).join('; ')}</p>{/if}
          {#if string(row.application_number)}<p>{$text(prefix + 'application')}: {string(row.application_number)}</p>{/if}
          {#if row.registration_number}<p>{$text(prefix + 'registration')}: {string(row.registration_number)}</p>{/if}
          {#if row.filing_date || row.registration_date}<ResultEmbedInfo icon="Calendar" label={$text(prefix + 'filed')}>{#snippet children()}{#if row.filing_date}<p>{$text(prefix + 'filed')}: {string(row.filing_date)}</p>{/if}{#if row.registration_date}<p>{$text(prefix + 'registered')}: {string(row.registration_date)}</p>{/if}{/snippet}</ResultEmbedInfo>{/if}
          {#if strings(row.goods_services).length}<details><summary>{$text(prefix + 'goods')}</summary>{#each strings(row.goods_services) as goods}<p>{goods}</p>{/each}</details>{/if}
          <p class="notice">{$text(prefix + 'limitation')}</p>
        </article>
      {/snippet}
    </ResultEmbedFullscreen>
  {/snippet}
</SearchResultsTemplate>

<style>
.body {width:min(100%,64rem);margin:auto;padding:var(--spacing-4);box-sizing:border-box;color:var(--color-font-primary);} .notice {color:var(--color-font-secondary);font-size:var(--font-size-small);line-height:1.5;} .error {color:var(--color-error);} .filters {display:flex;flex-wrap:wrap;gap:var(--spacing-3);font-size:var(--font-size-small);} .coverage-row {display:flex;flex-wrap:wrap;gap:var(--spacing-3);padding-block:var(--spacing-3);border-bottom:1px solid var(--color-grey-25);font-size:var(--font-size-small);overflow-wrap:anywhere;} .coverage-row p {flex-basis:100%;margin:0;} .coverage-row small {color:var(--color-font-secondary);} h3 {font-size:var(--font-size-p);margin:var(--spacing-3) 0;} .record-card {width:300px;max-width:100%;} .record {width:100%;font-size:var(--font-size-small);overflow-wrap:anywhere;} .record p {line-height:1.5;margin-block:var(--spacing-3);} details {margin-block:var(--spacing-4);} summary {cursor:pointer;min-height:44px;} a {color:var(--color-link);} a:focus-visible,summary:focus-visible {outline:2px solid var(--color-button-primary);outline-offset:2px;}
</style>
