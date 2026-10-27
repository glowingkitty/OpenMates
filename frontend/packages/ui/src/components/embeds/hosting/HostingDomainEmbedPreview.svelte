<script lang="ts">
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';

  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { formatTierMoney, headlineTier, isFirstYearOffer, normalizeDomain, quote, years, type DomainResult } from './hostingDomainData';

  interface Props {
    id: string;
    domain?: DomainResult;
    content?: Record<string, unknown>;
    isMobile?: boolean;
    presentationOnly?: boolean;
    resultContext?: 'auto' | 'chat' | 'results';
    onFullscreen: () => void;
  }

  let { id, domain, content, isMobile = false, presentationOnly = false, resultContext = 'auto', onFullscreen }: Props = $props();
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
</script>

<UnifiedEmbedPreview
  resultPreview={true}
  {resultContext}
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
    <div data-testid="hosting-domain-preview" class="domain-preview">
      <ResultEmbedCard title={displayDomain} sourceLabel={result.provider} description={statusLabel} textFirst={true}>
        {#snippet facts()}
          <ResultEmbedInfo icon="Globe" label={statusLabel} state={result.availability === 'available' ? 'yes' : result.availability === 'unavailable' ? 'no' : 'unknown'}>{#snippet children()}{statusLabel}{#if result.premium}<p>{$text('embeds.hosting.search_domains.premium')}</p>{/if}{#each result.restrictions as restriction}<p>{restriction}</p>{/each}{/snippet}</ResultEmbedInfo>
          <ResultEmbedInfo icon="Banknote" label={$text('embeds.hosting.search_domains.registration')} value={registration ? formatTierMoney(registrationTier, result.currency || 'EUR', $text('embeds.hosting.search_domains.year')) : $text('embeds.hosting.search_domains.price_unavailable')} testId="hosting-domain-registration">
            {#snippet children()}{#if registration}{formatTierMoney(registrationTier, result.currency || 'EUR', $text('embeds.hosting.search_domains.year'))}<p>{minimum === 1 ? $text('embeds.hosting.search_domains.first_year') : minimum ? $text('embeds.hosting.search_domains.minimum_years').replace('{count}', String(minimum)) : ''}</p>{#if registration.basis === 'excluding'}<p>{$text('embeds.hosting.search_domains.tax_excluded')}</p>{/if}{#if isFirstYearOffer(registrationTier)}<p>{$text('embeds.hosting.search_domains.first_year_offer')}</p>{/if}{:else}{$text('embeds.hosting.search_domains.price_unavailable')}{/if}{/snippet}
          </ResultEmbedInfo>
          {#if renewal}<ResultEmbedInfo icon="RefreshCw" label={$text('embeds.hosting.search_domains.renewal')} testId="hosting-domain-renewal">{#snippet children()}{$text('embeds.hosting.search_domains.renewal_price').replace('{price}', formatTierMoney(renewalTier, result.currency || 'EUR', $text('embeds.hosting.search_domains.year')) || '')}{#if renewal.basis === 'excluding'}<p>{$text('embeds.hosting.search_domains.tax_excluded')}</p>{/if}{/snippet}</ResultEmbedInfo>{/if}
        {/snippet}
      </ResultEmbedCard>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>.domain-preview {width:100%;height:100%;min-width:0;}</style>
