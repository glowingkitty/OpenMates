<!--
  frontend/packages/ui/src/components/embeds/business/BusinessCompanyFinancialResultEmbedFullscreen.svelte

  Fullscreen view for one SEC EDGAR company-financial result. It emphasizes
  auditable source filing metadata and avoids investment-advice framing.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
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

  let content = $derived({
    ...(data.embedData ?? {}),
    ...(data.attrs ?? {}),
    ...(data.decodedContent ?? {}),
  } as Record<string, unknown>);
  let company = $derived(asString(content.company) || asString(content.ticker) || $text('embeds.business.company_financials.result_title'));
  let ticker = $derived(asString(content.ticker));
  let providerSubtitle = $derived([ticker, asString(content.form), asString(content.filed)].filter(Boolean).join(' · '));
  let sourceUrl = $derived(asString(content.source_url));
  let currency = $derived(asString(content.currency) || 'USD');
  let notes = $derived(Array.isArray(content.notes) ? content.notes.filter((note): note is string => typeof note === 'string') : []);
  let rows = $derived([
    ['revenue', $text('embeds.business.company_financials.revenue')],
    ['gross_profit', $text('embeds.business.company_financials.gross_profit')],
    ['operating_income', $text('embeds.business.company_financials.operating_income')],
    ['net_income', $text('embeds.business.company_financials.net_income')],
    ['operating_cash_flow', $text('embeds.business.company_financials.operating_cash_flow')],
    ['assets', $text('embeds.business.company_financials.assets')],
    ['liabilities', $text('embeds.business.company_financials.liabilities')],
    ['equity', $text('embeds.business.company_financials.equity')],
  ].filter(([key]) => typeof content[key] === 'number'));

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
    const year = asNumber(content.fiscal_year);
    const quarter = asString(content.fiscal_quarter);
    if (asString(content.period_type) === 'quarter' && quarter && year) return `${quarter} ${year}`;
    if (year) return `FY ${year}`;
    return asString(content.period_end) || $text('embeds.business.company_financials.period');
  }
</script>

<UnifiedEmbedFullscreen
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

  {#snippet content()}
    <div class="business-financial-fullscreen" data-testid="business-financial-result-fullscreen">
      <section class="hero-card">
        <p class="kicker">{$text('embeds.business.company_financials.sec_filing')}</p>
        <h2>{company}</h2>
        <p>{formatPeriod()} · {[asString(content.period_start), asString(content.period_end)].filter(Boolean).join(' - ')}</p>
        <div class="hero-metrics">
          <div>
            <span>{$text('embeds.business.company_financials.revenue')}</span>
            <strong>{formatMoney(content.revenue)}</strong>
          </div>
          <div>
            <span>{$text('embeds.business.company_financials.net_income')}</span>
            <strong>{formatMoney(content.net_income)}</strong>
          </div>
        </div>
      </section>

      <section class="metric-table" aria-label="Financial metrics">
        <h3>{$text('embeds.business.company_financials.metrics')}</h3>
        {#if rows.length > 0}
          {#each rows as [key, label]}
            <div class="metric-row">
              <span>{label}</span>
              <strong>{formatMoney(content[key])}</strong>
            </div>
          {/each}
        {:else}
          <p>{$text('embeds.business.company_financials.no_metrics')}</p>
        {/if}
      </section>

      <section class="source-card" aria-label="Source filing">
        <h3>{$text('embeds.business.company_financials.source')}</h3>
        <p>{[asString(content.form), asString(content.accession_number), asString(content.filed)].filter(Boolean).join(' · ')}</p>
        {#if sourceUrl}
          <a href={sourceUrl} target="_blank" rel="noopener noreferrer" data-testid="business-open-sec-filing-inline">{$text('embeds.business.company_financials.open_filing')}</a>
        {/if}
      </section>

      {#if notes.length > 0}
        <section class="source-card" aria-label="Metric notes">
          <h3>{$text('embeds.business.company_financials.notes')}</h3>
          {#each notes as note}<p>{note}</p>{/each}
        </section>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .business-financial-fullscreen {
    display: grid;
    grid-template-columns: minmax(0, 1.1fr) minmax(280px, 0.9fr);
    gap: 18px;
    width: 100%;
    max-width: 1040px;
    margin: 0 auto;
    padding: 20px clamp(8px, 3vw, 16px) 120px;
    box-sizing: border-box;
  }

  .hero-card,
  .metric-table,
  .source-card {
    border-radius: 28px;
    border: 1px solid color-mix(in srgb, var(--color-app-business) 18%, var(--color-grey-20));
    background: color-mix(in srgb, var(--color-grey-0) 92%, transparent);
    box-shadow: 0 18px 42px color-mix(in srgb, var(--color-grey-100) 9%, transparent);
  }

  .hero-card {
    grid-row: span 2;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: 380px;
    padding: 30px;
    background:
      radial-gradient(circle at 90% 10%, color-mix(in srgb, var(--color-app-business) 34%, transparent), transparent 34%),
      linear-gradient(135deg, color-mix(in srgb, var(--color-app-business) 18%, var(--color-grey-0)), var(--color-grey-0));
  }

  .kicker,
  .hero-card p,
  .source-card p,
  .metric-table p,
  .metric-row span,
  .hero-metrics span {
    color: var(--color-font-secondary);
  }

  .kicker {
    margin: 0 0 10px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  h2, h3, p { margin: 0; }

  h2 {
    color: var(--color-font-primary);
    font-size: clamp(34px, 5vw, 56px);
    line-height: 1;
  }

  h3 {
    color: var(--color-font-primary);
    font-size: 16px;
  }

  .hero-metrics {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    margin-top: 28px;
  }

  .hero-metrics div {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 18px;
    border-radius: 20px;
    background: color-mix(in srgb, var(--color-grey-0) 76%, transparent);
  }

  .hero-metrics strong {
    color: var(--color-font-primary);
    font-size: clamp(22px, 3vw, 34px);
  }

  .metric-table,
  .source-card {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 20px;
  }

  .metric-row {
    display: flex;
    justify-content: space-between;
    gap: 18px;
    padding-top: 10px;
    border-top: 1px solid var(--color-grey-20);
  }

  .metric-row strong {
    color: var(--color-font-primary);
    white-space: nowrap;
  }

  a {
    align-self: flex-start;
    color: var(--color-link);
    font-weight: 650;
    text-decoration: none;
  }

  @media (max-width: 820px) {
    .business-financial-fullscreen { grid-template-columns: 1fr; }
    .hero-card { grid-row: auto; min-height: 300px; }
  }
</style>
