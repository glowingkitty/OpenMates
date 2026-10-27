<!--
  frontend/packages/ui/src/components/embeds/business/BusinessCompanyFinancialResultEmbedFullscreen.svelte

  Fullscreen view for one SEC EDGAR company-financial result. It emphasizes
  auditable source filing metadata and avoids investment-advice framing.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface Props {
    data: EmbedFullscreenRawData;
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }

  let {
    data,
    embedId,
    onClose,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
  }: Props = $props();

  let financialContent = $derived({
    ...(data.embedData ?? {}),
    ...(data.attrs ?? {}),
    ...(data.decodedContent ?? {}),
  } as Record<string, unknown>);
  let company = $derived(asString(financialContent.company) || asString(financialContent.ticker) || $text('embeds.business.company_financials.result_title'));
  let ticker = $derived(asString(financialContent.ticker));
  let providerSubtitle = $derived([ticker, asString(financialContent.form), asString(financialContent.filed)].filter(Boolean).join(' · '));
  let sourceUrl = $derived(asString(financialContent.source_url));
  let currency = $derived(asString(financialContent.currency) || 'USD');
  let notes = $derived(Array.isArray(financialContent.notes) ? financialContent.notes.filter((note): note is string => typeof note === 'string') : []);
  let rows = $derived([
    ['revenue', $text('embeds.business.company_financials.revenue')],
    ['gross_profit', $text('embeds.business.company_financials.gross_profit')],
    ['operating_income', $text('embeds.business.company_financials.operating_income')],
    ['net_income', $text('embeds.business.company_financials.net_income')],
    ['operating_cash_flow', $text('embeds.business.company_financials.operating_cash_flow')],
    ['assets', $text('embeds.business.company_financials.assets')],
    ['liabilities', $text('embeds.business.company_financials.liabilities')],
    ['equity', $text('embeds.business.company_financials.equity')],
  ].filter(([key]) => typeof financialContent[key] === 'number'));

  function asString(value: unknown): string {
    return typeof value === 'string' ? value : '';
  }

  function asNumber(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
  }

  function formatMoney(value: unknown): string {
    const amount = asNumber(value);
    if (amount === null) return $text('embeds.business.company_financials.not_available');
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      notation: 'compact',
      maximumFractionDigits: 2,
    }).format(amount);
  }

  function formatPeriod(): string {
    const year = asNumber(financialContent.fiscal_year);
    const quarter = asString(financialContent.fiscal_quarter);
    if (asString(financialContent.period_type) === 'quarter' && quarter && year) return `${quarter} ${year}`;
    if (year) return `FY ${year}`;
    return asString(financialContent.period_end) || $text('embeds.business.company_financials.period');
  }
</script>

<ResultEmbedFullscreen
  result={Object.fromEntries(["company", "ticker", "source_url", "fiscal_year", "fiscal_quarter", "period_end", "currency", "revenue", "net_income"].filter(key => financialContent[key] !== undefined).map(key => [key, financialContent[key]]))}
  appId="business"
  skillId="company_financial_result"
  skillIconName="business"
  embedHeaderTitle={company}
  embedHeaderSubtitle={providerSubtitle}
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
>
  {#snippet embedHeaderCta()}
    {#if sourceUrl}
      <EmbedHeaderCtaButton label={$text('embeds.business.company_financials.open_filing')} href={sourceUrl} testId="business-open-sec-filing" />
    {/if}
  {/snippet}

  {#snippet summary()}{#each [['revenue', $text('embeds.business.company_financials.revenue')], ['net_income', $text('embeds.business.company_financials.net_income')]] as [key, label]}
{#if typeof financialContent[key] === 'number'}<ResultEmbedInfo icon="ChartNoAxesCombined" {label} value={formatMoney(financialContent[key])}>{#snippet children()}{label}: {formatMoney(financialContent[key])} · {formatPeriod()}{/snippet}</ResultEmbedInfo>{/if}{/each}{/snippet}

  {#snippet detailContent()}
    <div class="business-financial-fullscreen" data-testid="business-financial-result-fullscreen">
      <section class="hero-card">
        <p class="kicker">{$text('embeds.business.company_financials.sec_filing')}</p>
        <h2>{company}</h2>
        <p>{formatPeriod()} · {[asString(financialContent.period_start), asString(financialContent.period_end)].filter(Boolean).join(' - ')}</p>
      </section>

      <section class="metric-table" aria-label="Financial metrics">
        <h3>{$text('embeds.business.company_financials.metrics')}</h3>
        {#if rows.length > 0}
          {#each rows as [key, label]}
            <div class="metric-row">
              <span>{label}</span>
              <strong>{formatMoney(financialContent[key])}</strong>
            </div>
          {/each}
        {:else}
          <p>{$text('embeds.business.company_financials.no_metrics')}</p>
        {/if}
      </section>

      <div class="source-details">
        {#if financialContent.form || financialContent.accession_number || financialContent.filed}<ResultEmbedInfo icon="FileText" label={$text('embeds.business.company_financials.source')}>
          {#snippet children()}<p>{[asString(financialContent.form), asString(financialContent.accession_number), asString(financialContent.filed)].filter(Boolean).join(' · ')}</p>{/snippet}
        </ResultEmbedInfo>{/if}
        {#if notes.length > 0}<ResultEmbedInfo icon="Info" label={$text('embeds.business.company_financials.notes')}>
          {#snippet children()}{#each notes as note}<p>{note}</p>{/each}{/snippet}
        </ResultEmbedInfo>{/if}
      </div>
    </div>
  {/snippet}
</ResultEmbedFullscreen>

<style>
 .business-financial-fullscreen {display:flex;flex-direction:column;gap:var(--spacing-6);width:100%;} .hero-card,.metric-table {display:flex;flex-direction:column;gap:var(--spacing-3);} h2,h3,p {margin:0;} h2 {font-size:var(--font-size-h4);overflow-wrap:anywhere;} h3 {font-size:var(--font-size-p);} p {color:var(--color-font-secondary);line-height:1.5;} .metric-row {display:flex;justify-content:space-between;gap:var(--spacing-3);padding-block:var(--spacing-2);border-bottom:1px solid var(--color-grey-20);} .metric-row span {color:var(--color-font-secondary);}
</style>
