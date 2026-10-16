<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { text } from '@repo/ui';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { formatChecked, formatMoney, formatTierMoney, headlineTier, isFirstYearOffer, normalRegistration, normalizeDomain, numberValue, quote, safeGandiUrl, years, type DomainResult, type DomainTier } from './hostingDomainData';

  interface Props {
    data?: EmbedFullscreenRawData;
    domain?: DomainResult;
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }

  let { data, domain, embedId, onClose, hasPreviousEmbed = false, hasNextEmbed = false, onNavigatePrevious, onNavigateNext }: Props = $props();
  let result = $derived(domain ?? normalizeDomain(embedId || '', data?.decodedContent ?? {}));
  let registration = $derived(headlineTier(result.registration_tiers));
  let renewal = $derived(headlineTier(result.renewal_tiers));
  let providerUrl = $derived(safeGandiUrl(result.provider_url));
  let checked = $derived(formatChecked(result.checked_at));
  let statusLabel = $derived(result.availability === 'available'
    ? $text('embeds.hosting.search_domains.available')
    : result.availability === 'unavailable'
      ? $text('embeds.hosting.search_domains.unavailable')
      : $text('embeds.hosting.search_domains.could_not_check'));

  function term(tier: DomainTier): string {
    const minimum = years(tier);
    const maximum = numberValue(tier.duration_range?.maximum);
    if (!minimum) return tier.minimum_term || '';
    if (maximum && maximum > minimum) return `${minimum}–${maximum} ${$text('embeds.hosting.search_domains.years')}`;
    return `${minimum} ${minimum === 1 ? $text('embeds.hosting.search_domains.year') : $text('embeds.hosting.search_domains.years')}`;
  }

  function price(tier: DomainTier): string {
    return formatTierMoney(tier, result.currency || 'EUR', $text('embeds.hosting.search_domains.year'))
      || $text('embeds.hosting.search_domains.price_unavailable');
  }

  function taxLabel(tier: DomainTier | undefined): string {
    const value = quote(tier);
    if (!value) return $text('embeds.hosting.search_domains.tax_unknown');
    const rate = numberValue(tier?.tax_rate) ?? numberValue(tier?.product_taxes?.[0]?.rate);
    const basis = value.basis === 'including' ? $text('embeds.hosting.search_domains.tax_included') : $text('embeds.hosting.search_domains.tax_excluded');
    return rate === undefined ? basis : `${basis} (${rate}%)`;
  }
</script>

<UnifiedEmbedFullscreen
  testId="hosting-domain-fullscreen"
  appId="hosting"
  skillId="search_domains"
  embedHeaderTitle={result.domain_unicode || result.domain_ascii}
  embedHeaderSubtitle={`${statusLabel} · ${$text('embeds.hosting.search_domains.provider_via').replace('{provider}', result.provider)}`}
  skillIconName="search"
  showSkillIcon={true}
  currentEmbedId={embedId || result.embed_id}
  {onClose}
  onCopy={() => navigator.clipboard.writeText(result.domain_unicode || result.domain_ascii)}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
>
  {#snippet embedHeaderCta()}
    {#if providerUrl}<EmbedHeaderCtaButton label={$text('embeds.hosting.search_domains.open_on_gandi')} href={providerUrl} />{/if}
  {/snippet}

  {#snippet content()}
    <main class="domain-details" data-testid="hosting-domain-details">
      <section class="identity">
        <div class="field"><span>{$text('embeds.hosting.search_domains.domain_unicode')}</span><strong class="copyable">{result.domain_unicode || result.domain_ascii}</strong></div>
        <div class="field"><span>{$text('embeds.hosting.search_domains.domain_ascii')}</span><strong class="copyable" data-testid="hosting-domain-ascii">{result.domain_ascii}</strong></div>
      </section>

      <section data-testid="hosting-domain-registration">
        <h2>{$text('embeds.hosting.search_domains.registration')}</h2>
        {#if registration && quote(registration)}
          <p class="headline">{price(registration)} <span>{years(registration) === 1 ? $text('embeds.hosting.search_domains.first_year') : years(registration) ? $text('embeds.hosting.search_domains.minimum_years').replace('{count}', String(years(registration))) : term(registration)}</span></p>
          {#if isFirstYearOffer(registration)}
            <p>{$text('embeds.hosting.search_domains.first_year_offer')} · {$text('embeds.hosting.search_domains.normal_registration')} {formatMoney(normalRegistration(registration)!, result.currency || 'EUR')} / {$text('embeds.hosting.search_domains.year')}</p>
          {/if}
        {:else}<p>{$text('embeds.hosting.search_domains.price_unavailable')}</p>{/if}
      </section>

      <section data-testid="hosting-domain-renewal">
        <h2>{$text('embeds.hosting.search_domains.renewal')}</h2>
        {#if renewal && quote(renewal)}<p class="headline">{price(renewal)} <span>{term(renewal)}</span></p>
        {:else}<p>{$text('embeds.hosting.search_domains.price_unavailable')}</p>{/if}
      </section>

      <section>
        <h2>{$text('embeds.hosting.search_domains.quote_details')}</h2>
        <div class="field"><span>{$text('embeds.hosting.search_domains.currency')}</span><strong>{result.currency || 'EUR'}</strong></div>
        {#if result.country}<div class="field"><span>{$text('embeds.hosting.search_domains.tax_country').replace('{country}', result.country)}</span></div>{/if}
        <div class="field"><span>{$text('embeds.hosting.search_domains.tax')}</span><strong>{taxLabel(registration)}</strong></div>
        {#if registration && years(registration)}<div class="field"><span>{$text('embeds.hosting.search_domains.minimum_term')}</span><strong>{years(registration)} {years(registration) === 1 ? $text('embeds.hosting.search_domains.year') : $text('embeds.hosting.search_domains.years')}</strong></div>{/if}
        {#if result.premium === true}<div class="field"><span>{$text('embeds.hosting.search_domains.premium')}</span><strong>{$text('embeds.hosting.search_domains.yes')}</strong></div>{/if}
        {#if checked}<div class="field"><span>{$text('embeds.hosting.search_domains.checked_at').replace('{date}', checked)}</span></div>{/if}
      </section>

      {#if result.restrictions.length}
        <section><h2>{$text('embeds.hosting.search_domains.registration_requirements')}</h2><ul>{#each result.restrictions as restriction}<li>{restriction}</li>{/each}</ul></section>
      {/if}

      {#if result.registration_tiers.length > 1 || result.renewal_tiers.length > 1}
        <section>
          <h2>{$text('embeds.hosting.search_domains.other_term_prices').replace('{count}', String(result.registration_tiers.length + result.renewal_tiers.length))}</h2>
          <div class="tier-tables">
            {#if result.registration_tiers.length > 1}
              <table><caption>{$text('embeds.hosting.search_domains.registration')}</caption><thead><tr><th>{$text('embeds.hosting.search_domains.term')}</th><th>{$text('embeds.hosting.search_domains.price')}</th></tr></thead><tbody>{#each result.registration_tiers as tier}<tr><td>{term(tier)}</td><td>{price(tier)} · {taxLabel(tier)}</td></tr>{/each}</tbody></table>
            {/if}
            {#if result.renewal_tiers.length > 1}
              <table><caption>{$text('embeds.hosting.search_domains.renewal')}</caption><thead><tr><th>{$text('embeds.hosting.search_domains.term')}</th><th>{$text('embeds.hosting.search_domains.price')}</th></tr></thead><tbody>{#each result.renewal_tiers as tier}<tr><td>{term(tier)}</td><td>{price(tier)} · {taxLabel(tier)}</td></tr>{/each}</tbody></table>
            {/if}
          </div>
        </section>
      {/if}
      <p class="disclaimer">{$text('embeds.hosting.search_domains.availability_may_change')}</p>
    </main>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .domain-details { max-width: 760px; margin: 0 auto; padding: var(--spacing-8); display: grid; gap: var(--spacing-8); color: var(--color-font-primary); }
  section { padding: var(--spacing-6); border: 1px solid var(--color-grey-30); border-radius: var(--radius-5); background: var(--color-grey-0); min-width: 0; }
  h2 { margin: 0 0 var(--spacing-4); font-size: var(--font-size-h3); }
  p { margin: var(--spacing-2) 0; }
  .headline { font-size: var(--font-size-h3); font-weight: 700; }
  .headline span { font-size: var(--font-size-p); font-weight: 400; color: var(--color-font-secondary); }
  .field { display: flex; flex-wrap: wrap; gap: var(--spacing-3); justify-content: space-between; padding: var(--spacing-3) 0; border-bottom: 1px solid var(--color-grey-25); }
  .field:last-child { border-bottom: 0; }
  .field span { color: var(--color-font-secondary); }
  .copyable { user-select: text; overflow-wrap: anywhere; }
  .tier-tables { display: grid; gap: var(--spacing-6); }
  table { width: 100%; border-collapse: collapse; text-align: left; }
  caption { text-align: left; font-weight: 600; margin-bottom: var(--spacing-2); }
  th, td { padding: var(--spacing-3); border-bottom: 1px solid var(--color-grey-25); }
  .disclaimer { color: var(--color-font-secondary); font-size: var(--font-size-small); }
  @media (max-width: 600px) { .domain-details { padding: var(--spacing-4); } .field { display: block; } .field strong { display: block; margin-top: var(--spacing-2); } }
</style>
