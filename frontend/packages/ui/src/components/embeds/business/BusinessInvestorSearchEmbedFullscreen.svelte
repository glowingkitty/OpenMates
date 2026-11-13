<!--
  frontend/packages/ui/src/components/embeds/business/BusinessInvestorSearchEmbedFullscreen.svelte

  Fullscreen for Business / Search investors. One parent embed carries the whole
  investor list; each investor renders as a card. Missing fields render nothing.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData, EmbedFullscreenCommonProps } from '../../../types/embedFullscreen';
  import { INVESTOR_STAGES, INVESTOR_TYPES, normalizeInvestorSearch } from './investorSearchContent';
  interface Props extends EmbedFullscreenCommonProps { data: EmbedFullscreenRawData; }
  let { data, onClose, embedId, hasPreviousEmbed = false, hasNextEmbed = false,
    onNavigatePrevious, onNavigateNext, navigateDirection, showChatButton = false, onShowChat }: Props = $props();
  const prefix = 'embeds.business.search_investors.';
  const CLAMP_LENGTH = 220;
  let payload = $state<Record<string, unknown>>({});
  $effect(() => { payload = data.decodedContent ?? {}; });
  let search = $derived(normalizeInvestorSearch(payload));
  let expanded = $state<Record<number, boolean>>({});
  let subtitle = $derived([search.regions.join(', '), search.hasData ? $text(prefix + 'result_count', { values: { count: search.count } }) : '']
    .filter(Boolean).join(' · '));
  function typeLabel(value: string): string {
    return (INVESTOR_TYPES as readonly string[]).includes(value) ? $text(prefix + 'type_' + value) : '';
  }
  function stageLabel(value: string): string {
    return (INVESTOR_STAGES as readonly string[]).includes(value) ? $text(prefix + 'stage_' + value) : value;
  }
  function date(value: string): string {
    const parsed = new Date(value);
    return value && !Number.isNaN(parsed.valueOf()) ? parsed.toLocaleDateString(undefined, { dateStyle: 'medium' }) : value;
  }
  function updated(value: { status: string; decodedContent: Record<string, unknown> }) { payload = value.decodedContent; }
</script>

<UnifiedEmbedFullscreen appId="business" skillId="search_investors" skillIconName="business"
  testId="investor-search-fullscreen" {onClose}
  embedHeaderTitle={search.query || $text('app_skills.business.search_investors')}
  embedHeaderSubtitle={subtitle} currentEmbedId={embedId} onEmbedDataUpdated={updated}
  {hasPreviousEmbed} {hasNextEmbed} {onNavigatePrevious} {onNavigateNext}
  navigateDirection={navigateDirection ?? undefined} {showChatButton} {onShowChat}>
  {#snippet content()}
    <div class="body">
      {#if search.warnings.length || search.partial}
        <section class="warnings" role="note" data-testid="investor-warnings">
          <strong>{$text(prefix + 'skipped_sources')}</strong>
          {#if search.warnings.length}
            <ul>{#each search.warnings as warning}<li>{warning}</li>{/each}</ul>
          {:else}
            <p>{$text(prefix + 'partial')}</p>
          {/if}
        </section>
      {/if}
      {#if search.error}
        <p class="error" data-testid="investor-error">{$text(prefix + (search.errorCode === 'provider_unavailable' ? 'unavailable' : 'failed'))}</p>
      {:else if !search.investors.length}
        <p class="empty" data-testid="investor-empty">{$text(prefix + 'empty')}</p>
      {/if}
      <ul class="list" data-testid="investor-list">
        {#each search.investors as investor, index}
          {@const long = investor.thesis.length > CLAMP_LENGTH}
          <li class="card" data-testid="investor-card">
            <header>
              <h3 class="name">{investor.name}</h3>
              {#if typeLabel(investor.investorType)}<span class="badge" data-testid="investor-type">{typeLabel(investor.investorType)}</span>{/if}
            </header>
            {#if investor.organization}<p class="org">{investor.organization}</p>{/if}
            {#if investor.city || investor.regions.length}
              <p class="muted">{[investor.city, investor.regions.join(', ')].filter(Boolean).join(' · ')}</p>
            {/if}
            <dl class="facts">
              {#if investor.stages.length}
                <div><dt>{$text(prefix + 'stages')}</dt><dd>{investor.stages.map(stageLabel).join(', ')}</dd></div>
              {/if}
              {#if investor.ticket}
                <div><dt>{$text(prefix + 'ticket_size')}</dt><dd data-testid="investor-ticket">{investor.ticket}</dd></div>
              {/if}
              {#if investor.contactRoute}
                <div><dt>{$text(prefix + 'contact')}</dt><dd>{investor.contactRoute}</dd></div>
              {/if}
            </dl>
            {#if investor.sectors.length}
              <ul class="chips" aria-label={$text(prefix + 'sectors')}>{#each investor.sectors as sector}<li>{sector}</li>{/each}</ul>
            {/if}
            {#if investor.thesis}
              <div class="thesis">
                <h4>{$text(prefix + 'thesis')}</h4>
                <p class:clamped={long && !expanded[index]}>{investor.thesis}</p>
                {#if long}
                  <button type="button" class="link-button" aria-expanded={!!expanded[index]}
                    onclick={() => (expanded[index] = !expanded[index])}>{$text(prefix + (expanded[index] ? 'show_less' : 'show_more'))}</button>
                {/if}
              </div>
            {/if}
            {#if investor.exampleInvestments.length}
              <div class="examples"><h4>{$text(prefix + 'example_investments')}</h4><p>{investor.exampleInvestments.join(', ')}</p></div>
            {/if}
            {#if investor.provider || investor.sourceUpdatedAt}
              <p class="source">{$text(prefix + 'source')}: {[investor.provider, date(investor.sourceUpdatedAt)].filter(Boolean).join(' · ')}</p>
            {/if}
            {#if investor.profileUrl || investor.websiteUrl}
              <div class="links">
                {#if investor.profileUrl}<a href={investor.profileUrl} target="_blank" rel="noopener noreferrer" data-testid="investor-profile-link">{$text(prefix + 'open_profile')}</a>{/if}
                {#if investor.websiteUrl}<a href={investor.websiteUrl} target="_blank" rel="noopener noreferrer" data-testid="investor-website-link">{$text(prefix + 'open_website')}</a>{/if}
              </div>
            {/if}
          </li>
        {/each}
      </ul>
      <p class="limitation" data-testid="investor-limitation">{search.limitation || $text(prefix + 'limitation')}</p>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .body { width: min(100%, 64rem); margin: 0 auto; padding: var(--spacing-8) var(--spacing-6) 8rem; box-sizing: border-box; display: flex; flex-direction: column; gap: var(--spacing-6); color: var(--color-font-primary); min-width: 0; }
  p { margin: 0; }
  .warnings { padding: var(--spacing-5) var(--spacing-6); border-radius: var(--radius-3); background: var(--color-grey-20); font-size: var(--font-size-small); overflow-wrap: anywhere; }
  .warnings ul { margin: var(--spacing-3) 0 0; padding-left: var(--spacing-8); }
  .error { color: var(--color-error); }
  .empty, .limitation { color: var(--color-font-secondary); font-size: var(--font-size-small); line-height: 1.5; }
  .list { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 20rem), 1fr)); gap: var(--spacing-6); }
  .card { display: flex; flex-direction: column; gap: var(--spacing-4); min-width: 0; padding: var(--spacing-6); border-radius: var(--radius-4); background: var(--color-grey-10); border: 1px solid var(--color-grey-25); font-size: var(--font-size-small); overflow-wrap: anywhere; }
  header { display: flex; flex-wrap: wrap; align-items: center; gap: var(--spacing-3); min-width: 0; }
  .name { margin: 0; color: var(--color-font-primary); font-size: var(--font-size-p); font-weight: 600; min-width: 0; overflow-wrap: anywhere; }
  .badge { padding: var(--spacing-1) var(--spacing-4); border-radius: var(--radius-3); background: var(--color-grey-20); font-size: var(--font-size-xs); white-space: nowrap; }
  .org { font-weight: 500; }
  .muted, .source { color: var(--color-font-tertiary); font-size: var(--font-size-xs); }
  .facts { margin: 0; display: flex; flex-direction: column; gap: var(--spacing-2); }
  .facts div { display: flex; flex-wrap: wrap; gap: var(--spacing-3); }
  dt { color: var(--color-font-secondary); } dd { margin: 0; min-width: 0; }
  .chips { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: var(--spacing-3); }
  .chips li { padding: var(--spacing-1) var(--spacing-4); border-radius: var(--radius-3); background: var(--color-grey-20); font-size: var(--font-size-xs); }
  h4 { margin: 0 0 var(--spacing-2); font-size: var(--font-size-xs); font-weight: 600; color: var(--color-font-secondary); }
  .thesis p, .examples p { line-height: 1.5; }
  .clamped { display: -webkit-box; -webkit-line-clamp: 4; line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
  .link-button { all: unset; cursor: pointer; min-height: 44px; display: inline-flex; align-items: center; color: var(--color-link); }
  .links { display: flex; flex-wrap: wrap; gap: var(--spacing-6); }
  a { color: var(--color-link); display: inline-flex; align-items: center; min-height: 44px; }
  a:focus-visible, .link-button:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
</style>
