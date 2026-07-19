<!--
  frontend/packages/ui/src/components/embeds/business/BusinessCompanyFinancialResultEmbedPreview.svelte

  Preview card for one Business company_financial_result child embed. It shows
  normalized SEC facts only; the filing source is available from fullscreen.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';

  interface Props {
    id: string;
    company?: string;
    ticker?: string;
    fiscalYear?: number | null;
    fiscalQuarter?: string | null;
    periodType?: string;
    currency?: string;
    revenue?: number | null;
    netIncome?: number | null;
    filed?: string;
    form?: string;
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    company = '',
    ticker = '',
    fiscalYear = null,
    fiscalQuarter = null,
    periodType = 'annual',
    currency = 'USD',
    revenue = null,
    netIncome = null,
    filed = '',
    form = '',
    status = 'finished',
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let title = $derived(company || ticker || $text('embeds.business.company_financials.result_title'));
  let periodLabel = $derived(formatPeriod(periodType, fiscalYear, fiscalQuarter));
  let subtitle = $derived([ticker, periodLabel, form].filter(Boolean).join(' · '));

  function formatPeriod(type?: string, year?: number | null, quarter?: string | null): string {
    if (!year) return type === 'quarter' ? $text('embeds.business.company_financials.quarterly') : $text('embeds.business.company_financials.annual');
    return type === 'quarter' && quarter ? `${quarter} ${year}` : `FY ${year}`;
  }

  function formatMoney(value?: number | null): string {
    if (value === null || value === undefined) return $text('embeds.business.company_financials.not_available');
    const abs = Math.abs(value);
    const divisor = abs >= 1_000_000_000 ? 1_000_000_000 : abs >= 1_000_000 ? 1_000_000 : 1;
    const suffix = divisor === 1_000_000_000 ? 'B' : divisor === 1_000_000 ? 'M' : '';
    const formatted = new Intl.NumberFormat(undefined, {
      maximumFractionDigits: divisor === 1 ? 0 : 1,
    }).format(value / divisor);
    return `${currency || ''} ${formatted}${suffix}`.trim();
  }

  function handleStop() {
    // SEC EDGAR lookups are synchronous and not cancellable from the preview.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="business"
  skillId="company_financial_result"
  skillIconName="business"
  {status}
  skillName={title}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
  customStatusText={subtitle || undefined}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <article class="financial-result-card" class:mobile={isMobileLayout} data-testid="business-financial-result-preview">
      <div class="result-heading">
        <span class="company">{title}</span>
        <span class="period">{periodLabel}</span>
      </div>
      <div class="metric-grid">
        <div>
          <span>{$text('embeds.business.company_financials.revenue')}</span>
          <strong>{formatMoney(revenue)}</strong>
        </div>
        <div>
          <span>{$text('embeds.business.company_financials.net_income')}</span>
          <strong>{formatMoney(netIncome)}</strong>
        </div>
      </div>
      {#if filed}
        <p>{$text('embeds.business.company_financials.filed')} {filed}</p>
      {/if}
    </article>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .financial-result-card {
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    gap: 12px;
    min-height: 148px;
    padding: 14px;
    border-radius: 22px;
    background:
      radial-gradient(circle at 12% 0%, color-mix(in srgb, var(--color-app-business) 24%, transparent), transparent 46%),
      linear-gradient(145deg, color-mix(in srgb, var(--color-app-business) 10%, var(--color-grey-0)), var(--color-grey-0));
    border: 1px solid color-mix(in srgb, var(--color-app-business) 18%, var(--color-grey-20));
  }

  .financial-result-card.mobile { min-height: 130px; }

  .result-heading {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }

  .company {
    overflow: hidden;
    color: var(--color-font-primary);
    font-size: var(--font-size-sm);
    font-weight: 680;
    line-height: 1.2;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .period,
  p,
  .metric-grid span {
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
  }

  .metric-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .metric-grid div {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
    padding: 10px;
    border-radius: 16px;
    background: color-mix(in srgb, var(--color-grey-0) 82%, transparent);
    border: 1px solid color-mix(in srgb, var(--color-app-business) 14%, var(--color-grey-20));
  }

  .metric-grid strong {
    overflow: hidden;
    color: var(--color-font-primary);
    font-size: 15px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  p { margin: 0; }
</style>
