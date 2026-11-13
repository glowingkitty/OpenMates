<!--
  frontend/packages/ui/src/components/embeds/business/BusinessCompanyOwnershipEmbedFullscreen.svelte

  Fullscreen for Business / Company ownership. One parent embed carries every
  record: a section per subject with facts, owners, holdings (ended ones marked),
  officers, source link, provider and limitation. Failed lookups are listed with
  their candidates so the user can pick one. Missing fields render nothing.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData, EmbedFullscreenCommonProps } from '../../../types/embedFullscreen';
  import { countryName, normalizeCompanyOwnership } from './companyOwnershipContent';
  interface Props extends EmbedFullscreenCommonProps { data: EmbedFullscreenRawData; }
  let { data, onClose, embedId, hasPreviousEmbed = false, hasNextEmbed = false,
    onNavigatePrevious, onNavigateNext, navigateDirection, showChatButton = false, onShowChat }: Props = $props();
  const prefix = 'embeds.business.company_ownership.';
  let payload = $state<Record<string, unknown>>({});
  $effect(() => { payload = data.decodedContent ?? {}; });
  let result = $derived(normalizeCompanyOwnership(payload));
  let subtitle = $derived(result.hasData ? $text(prefix + 'result_count', { values: { count: result.count } }) : '');
  const label = (value: string): string => value.replace(/_/g, ' ');
  function date(value: string): string {
    const parsed = new Date(value);
    return value && !Number.isNaN(parsed.valueOf()) ? parsed.toLocaleDateString(undefined, { dateStyle: 'medium' }) : value;
  }
  function errorTitle(code: string): string {
    return $text(prefix + (code === 'ambiguous' ? 'error_ambiguous' : code === 'coverage_gap' ? 'error_coverage_gap'
      : code === 'not_found' ? 'error_not_found' : 'error_other'));
  }
  function updated(value: { status: string; decodedContent: Record<string, unknown> }) { payload = value.decodedContent; }
</script>

<UnifiedEmbedFullscreen appId="business" skillId="company_ownership" skillIconName="business"
  testId="company-ownership-fullscreen" {onClose}
  embedHeaderTitle={result.query || $text('app_skills.business.company_ownership')}
  embedHeaderSubtitle={subtitle} currentEmbedId={embedId} onEmbedDataUpdated={updated}
  {hasPreviousEmbed} {hasNextEmbed} {onNavigatePrevious} {onNavigateNext}
  navigateDirection={navigateDirection ?? undefined} {showChatButton} {onShowChat}>
  {#snippet content()}
    <div class="body">
      {#if result.warnings.length}
        <section class="warnings" role="note" data-testid="company-ownership-warnings">
          <strong>{$text(prefix + 'skipped_sources')}</strong>
          <ul>{#each result.warnings as warning}<li>{warning}</li>{/each}</ul>
        </section>
      {/if}
      {#if result.error}
        <p class="error" data-testid="company-ownership-error">{$text(prefix + 'failed')}</p>
      {:else if !result.records.length && !result.errors.length}
        <p class="empty" data-testid="company-ownership-empty">{$text(prefix + 'empty')}</p>
      {/if}
      {#each result.records as rec}
        <section class="record" data-testid="company-ownership-record">
          <header>
            <h3 class="name">{rec.subject.name}</h3>
            {#if rec.subject.type}<span class="badge">{$text(prefix + (rec.subject.type === 'person' ? 'type_person' : 'type_company'))}</span>{/if}
          </header>
          <dl class="facts" data-testid="company-ownership-subject">
            {#if rec.subject.country}<div><dt>{$text(prefix + 'country')}</dt><dd>{countryName(rec.subject.country)}</dd></div>{/if}
            {#if rec.subject.legalForm}<div><dt>{$text(prefix + 'legal_form')}</dt><dd>{rec.subject.legalForm}</dd></div>{/if}
            {#if rec.subject.status}<div><dt>{$text(prefix + 'status')}</dt><dd>{label(rec.subject.status)}</dd></div>{/if}
            {#if rec.subject.registerId}<div><dt>{$text(prefix + 'register_id')}</dt><dd>{rec.subject.registerId}</dd></div>{/if}
            {#if rec.subject.city}<div><dt>{$text(prefix + 'city')}</dt><dd>{rec.subject.city}</dd></div>{/if}
          </dl>
          {#if rec.owners.length}
            <h4>{$text(prefix + 'owners')}</h4>
            <div class="table-wrap">
              <table data-testid="company-ownership-owners">
                <thead><tr>
                  <th>{$text(prefix + 'name')}</th><th>{$text(prefix + 'share')}</th><th class="relation-col">{$text(prefix + 'relation')}</th><th>{$text(prefix + 'since')}</th>
                </tr></thead>
                <tbody>
                  {#each rec.owners as owner}
                    <tr data-testid="company-ownership-owner">
                      <td>{owner.name}{#if owner.registerId}<span class="sub">{owner.registerId}</span>{/if}{#if owner.relation}<span class="sub relation-inline">{label(owner.relation)}</span>{/if}</td>
                      <td class="nowrap" data-testid="company-ownership-owner-share">{owner.share}{#if owner.nominal}<span class="sub">{owner.nominal}</span>{/if}</td>
                      <td class="relation-col">{label(owner.relation)}</td>
                      <td class="nowrap">{date(owner.since)}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
          {#if rec.holdings.length}
            <h4>{$text(prefix + 'holdings')}</h4>
            <ul class="items" data-testid="company-ownership-holdings">
              {#each rec.holdings as holding}
                <li class:ended={holding.ended} data-testid="company-ownership-holding">
                  <span class="item-name">{holding.name}</span>
                  {#if holding.ended}<span class="badge" data-testid="company-ownership-ended">{$text(prefix + 'ended')}</span>{/if}
                  <span class="muted">{[label(holding.relation), holding.share, holding.country, holding.registerId,
                    [date(holding.since), date(holding.until)].filter(Boolean).join(' – '), label(holding.status)].filter(Boolean).join(' · ')}</span>
                  {#if holding.sourceUrl}<a href={holding.sourceUrl} target="_blank" rel="noopener noreferrer">{$text(prefix + 'open_source')}</a>{/if}
                </li>
              {/each}
            </ul>
          {/if}
          {#if rec.officers.length}
            <h4>{$text(prefix + 'officers')}</h4>
            <ul class="items" data-testid="company-ownership-officers">
              {#each rec.officers as officer}
                <li data-testid="company-ownership-officer">
                  <span class="item-name">{officer.name}</span>
                  <span class="muted">{[officer.role, officer.since ? $text(prefix + 'since') + ' ' + date(officer.since) : ''].filter(Boolean).join(' · ')}</span>
                </li>
              {/each}
            </ul>
          {/if}
          {#each rec.warnings as warning}<p class="muted">{warning}</p>{/each}
          <p class="source">
            {#if rec.provider}{$text(prefix + 'source')}: {rec.provider}{/if}
            {#if rec.subject.sourceUrl}<a href={rec.subject.sourceUrl} target="_blank" rel="noopener noreferrer" data-testid="company-ownership-source-link">{$text(prefix + 'open_source')}</a>{/if}
          </p>
          {#if rec.limitation}<p class="limitation">{rec.limitation}</p>{/if}
        </section>
      {/each}
      {#if result.errors.length}
        <ul class="errors" data-testid="company-ownership-errors">
          {#each result.errors as err}
            <li class="record" data-testid="company-ownership-lookup-error">
              <h3 class="name">{err.query}{#if err.country} <span class="muted">({countryName(err.country)})</span>{/if}</h3>
              <p class="error-title">{errorTitle(err.code)}</p>
              {#if err.message}<p class="muted">{err.message}</p>{/if}
              {#if err.candidates.length}
                <h4>{$text(prefix + 'candidates')}</h4>
                <ul class="items" data-testid="company-ownership-candidates">
                  {#each err.candidates as candidate}
                    <li data-testid="company-ownership-candidate">
                      <span class="item-name">{candidate.name}</span>
                      <span class="muted">{[candidate.registerId, candidate.city, label(candidate.status)].filter(Boolean).join(' · ')}</span>
                    </li>
                  {/each}
                </ul>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
      {#if result.limitation}<p class="limitation" data-testid="company-ownership-limitation">{result.limitation}</p>{/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .body { width: min(100%, 64rem); margin: 0 auto; padding: var(--spacing-8) var(--spacing-6) 8rem; box-sizing: border-box; display: flex; flex-direction: column; gap: var(--spacing-6); color: var(--color-font-primary); min-width: 0; }
  p { margin: 0; }
  .warnings { padding: var(--spacing-5) var(--spacing-6); border-radius: var(--radius-3); background: var(--color-grey-20); font-size: var(--font-size-small); overflow-wrap: anywhere; }
  .warnings ul { margin: var(--spacing-3) 0 0; padding-left: var(--spacing-8); }
  .error, .error-title { color: var(--color-error); }
  .empty, .limitation { color: var(--color-font-secondary); font-size: var(--font-size-small); line-height: 1.5; }
  .record { display: flex; flex-direction: column; gap: var(--spacing-4); min-width: 0; padding: var(--spacing-6); border-radius: var(--radius-4); background: var(--color-grey-10); border: 1px solid var(--color-grey-25); font-size: var(--font-size-small); overflow-wrap: anywhere; list-style: none; }
  .errors { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--spacing-6); }
  header { display: flex; flex-wrap: wrap; align-items: center; gap: var(--spacing-3); min-width: 0; }
  .name { margin: 0; color: var(--color-font-primary); font-size: var(--font-size-p); font-weight: 600; min-width: 0; overflow-wrap: anywhere; }
  .badge { padding: var(--spacing-1) var(--spacing-4); border-radius: var(--radius-3); background: var(--color-grey-20); font-size: var(--font-size-xs); white-space: nowrap; }
  .muted, .source { color: var(--color-font-tertiary); font-size: var(--font-size-xs); }
  .facts { margin: 0; display: flex; flex-direction: column; gap: var(--spacing-2); }
  .facts div { display: flex; flex-wrap: wrap; gap: var(--spacing-3); }
  dt { color: var(--color-font-secondary); } dd { margin: 0; min-width: 0; }
  h4 { margin: var(--spacing-2) 0 0; font-size: var(--font-size-xs); font-weight: 600; color: var(--color-font-secondary); }
  .table-wrap { overflow-x: auto; max-width: 100%; container-type: inline-size; }
  table { width: 100%; border-collapse: collapse; font-size: var(--font-size-small); }
  th, td { text-align: left; padding: var(--spacing-3) var(--spacing-4); border-bottom: 1px solid var(--color-grey-25); vertical-align: top; overflow-wrap: break-word; }
  .nowrap { white-space: nowrap; }
  .relation-inline { display: none; }
  /* Narrow cards: the relation moves under the name so words never break mid-word. */
  @container (max-width: 480px) { .relation-col { display: none; } .relation-inline { display: block; } }
  th { color: var(--color-font-secondary); font-weight: 600; font-size: var(--font-size-xs); }
  .sub { display: block; color: var(--color-font-tertiary); font-size: var(--font-size-xs); }
  .items { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--spacing-3); }
  .items li { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--spacing-3); min-width: 0; }
  .item-name { font-weight: 500; }
  .ended .item-name { text-decoration: line-through; color: var(--color-font-secondary); }
  a { color: var(--color-link); display: inline-flex; align-items: center; min-height: 44px; }
  a:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
</style>
