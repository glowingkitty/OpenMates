<!--
  frontend/packages/ui/src/components/embeds/business/BusinessCompanyFinancialResultEmbedPreview.svelte

  Preview card for one Business company_financial_result child embed. It shows
  normalized SEC facts only; the filing source is available from fullscreen.
-->

<script lang="ts">
  import { AUTHORED_RESULT_PRESENTATION_CONTEXT, type AuthoredResultPresentationContext } from "../../../types/authoredResult";
  import { getContext } from "svelte";
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import EmbedCalendarDate from '../EmbedCalendarDate.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';

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
    presentationOnly?: boolean;
    resultContext?: 'auto' | 'chat' | 'results';
    onFullscreen: () => void;
  }

  let {
    id,
    company = '',
    ticker = '',
    fiscalYear = null,
    fiscalQuarter = null,
    periodType,
    currency,
    revenue = null,
    netIncome = null,
    filed = '',
    form = '',
    status = 'finished',
    isMobile = false,
    presentationOnly = false,
    resultContext = 'auto',
    onFullscreen,
  }: Props = $props();
  const authoredContext = getContext<AuthoredResultPresentationContext | undefined>(AUTHORED_RESULT_PRESENTATION_CONTEXT);
  let isAuthored = $derived(Boolean(authoredContext?.authoring));

  let effectiveCurrency = $derived(isAuthored ? String(authoredContext?.content.currency ?? '') : currency || 'USD');
  let effectivePeriodType = $derived(isAuthored ? String(authoredContext?.content.period_type ?? '') : periodType || 'annual');
  let title = $derived(company || ticker || $text('embeds.business.company_financials.result_title'));
  let periodLabel = $derived(formatPeriod(effectivePeriodType, fiscalYear, fiscalQuarter));
  let subtitle = $derived([ticker, periodLabel, form].filter(Boolean).join(' · '));

  function formatPeriod(type?: string, year?: number | null, quarter?: string | null): string {
    if (isAuthored && !type && !year) return '';
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
    return `${effectiveCurrency} ${formatted}${suffix}`.trim();
  }

  function handleStop() {
    // SEC EDGAR lookups are synchronous and not cancellable from the preview.
  }
</script>

<UnifiedEmbedPreview
  resultPreview={true}
  {presentationOnly}
  {resultContext}
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
  {#snippet details()}
    <div data-testid="business-financial-result-preview" class="catalog-result-preview">
      <ResultEmbedCard title={title} sourceLabel={subtitle} textFirst={true}>
        {#snippet badge()}{#if filed}<EmbedCalendarDate date={filed} />{/if}{/snippet}
        {#snippet facts()}{#if revenue != null}<ResultEmbedInfo icon="ChartNoAxesCombined" label={$text('embeds.business.company_financials.revenue')}>{#snippet children()}{formatMoney(revenue)} · {periodLabel}{/snippet}</ResultEmbedInfo>{/if}
{#if netIncome != null}<ResultEmbedInfo icon="Banknote" label={$text('embeds.business.company_financials.net_income')}>{#snippet children()}{formatMoney(netIncome)} · {periodLabel}{/snippet}</ResultEmbedInfo>{/if}
{#if filed && form}<ResultEmbedInfo icon="FileText" label="Source filing">{#snippet children()}{form}{/snippet}</ResultEmbedInfo>{/if}{/snippet}
      </ResultEmbedCard>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .catalog-result-preview { width: 100%; height: 100%; min-width: 0; }
</style>
