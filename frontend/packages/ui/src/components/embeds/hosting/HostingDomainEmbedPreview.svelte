<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { formatTierMoney, headlineTier, isFirstYearOffer, normalizeDomain, quote, years, type DomainResult } from './hostingDomainData';

  interface Props {
    id: string;
    domain?: DomainResult;
    content?: Record<string, unknown>;
    isMobile?: boolean;
    presentationOnly?: boolean;
    onFullscreen: () => void;
  }

  let { id, domain, content, isMobile = false, presentationOnly = false, onFullscreen }: Props = $props();
  let result = $derived(domain ?? normalizeDomain(id, content ?? {}));
  let registrationTier = $derived(headlineTier(result.registration_tiers));
  let renewalTier = $derived(headlineTier(result.renewal_tiers));
  let registration = $derived(quote(registrationTier));
  let renewal = $derived(quote(renewalTier));
  let minimum = $derived(registrationTier ? years(registrationTier) : undefined);
  let statusLabel = $derived(result.availability === 'available'
    ? $text('embeds.hosting.search_domains.available')
    : result.availability === 'unavailable'
      ? $text('embeds.hosting.search_domains.unavailable')
      : $text('embeds.hosting.search_domains.could_not_check'));
  let displayDomain = $derived(result.domain_unicode || result.domain_ascii);
  let suffixStart = $derived(displayDomain.lastIndexOf('.'));
  let showBodyName = $derived(displayDomain.length > 24 || displayDomain !== result.domain_ascii);
</script>

<UnifiedEmbedPreview
  {id}
  appId="hosting"
  skillId="search_domains"
  skillIconName="search"
  skillName={result.domain_unicode || result.domain_ascii}
  status="finished"
  {isMobile}
  {presentationOnly}
  {onFullscreen}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details()}
    <div class="domain-preview" data-testid="hosting-domain-preview">
      <div class="topline"><span class:unknown={result.availability === 'unknown'} class:available={result.availability === 'available'}>{statusLabel}</span>
        {#if result.premium}<span class="badge">{$text('embeds.hosting.search_domains.premium')}</span>{/if}
      </div>
      {#if showBodyName}<div class="domain-name" title={displayDomain}>
        {#if suffixStart > 0}<span class="domain-prefix">{displayDomain.slice(0, suffixStart)}</span><span class="domain-suffix">{displayDomain.slice(suffixStart)}</span>
        {:else}{displayDomain}{/if}
      </div>{/if}
      {#if registration}
        <div class="registration" data-testid="hosting-domain-registration">{formatTierMoney(registrationTier, result.currency || 'EUR', $text('embeds.hosting.search_domains.year'))}</div>
        <div class="term">{minimum === 1 ? $text('embeds.hosting.search_domains.first_year') : minimum ? $text('embeds.hosting.search_domains.minimum_years').replace('{count}', String(minimum)) : ''}</div>
        {#if registration.basis === 'excluding'}<div class="term">{$text('embeds.hosting.search_domains.tax_excluded')}</div>{/if}
      {:else}
        <div class="unpriced" data-testid="hosting-domain-registration">{$text('embeds.hosting.search_domains.price_unavailable')}</div>
      {/if}
      {#if renewal}
        <div class="renewal" data-testid="hosting-domain-renewal">{$text('embeds.hosting.search_domains.renewal_price').replace('{price}', formatTierMoney(renewalTier, result.currency || 'EUR', $text('embeds.hosting.search_domains.year')) || '')}</div>
        {#if renewal.basis === 'excluding'}<div class="term">{$text('embeds.hosting.search_domains.tax_excluded')}</div>{/if}
      {/if}
      <div class="badges">
        {#if isFirstYearOffer(registrationTier)}<span class="badge">{$text('embeds.hosting.search_domains.first_year_offer')}</span>{/if}
        {#if minimum && minimum > 1}<span class="badge">{$text('embeds.hosting.search_domains.minimum_years').replace('{count}', String(minimum))}</span>{/if}
        {#if result.restrictions.length}<span class="badge">{$text('embeds.hosting.search_domains.registration_restrictions')}</span>{/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .domain-preview { display: flex; flex-direction: column; gap: var(--spacing-2); min-width: 0; padding-top: var(--spacing-4); }
  .topline { display: flex; justify-content: space-between; gap: var(--spacing-2); font-size: var(--font-size-small); font-weight: 600; }
  .available { color: var(--color-primary); }
  .unknown { color: var(--color-warning); }
  .domain-name { display: flex; min-width: 0; color: var(--color-font-primary); font-weight: 600; line-height: 1.2; }
  .domain-prefix { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .domain-suffix { flex: none; white-space: nowrap; }
  .registration { color: var(--color-font-primary); font-size: var(--font-size-h3); font-weight: 700; }
  .term, .renewal, .unpriced { color: var(--color-font-secondary); font-size: var(--font-size-small); }
  .badges { display: flex; flex-wrap: wrap; gap: var(--spacing-2); }
  .badge { border: 1px solid var(--color-grey-30); border-radius: var(--radius-3); padding: 2px var(--spacing-2); color: var(--color-font-secondary); font-size: var(--font-size-small); }
</style>
