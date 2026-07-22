<!--
  frontend/packages/ui/src/components/embeds/finance/FinanceCheckAccountsEmbedPreview.svelte

  Preview card for Finance / Check accounts.
  It intentionally shows only aggregate totals and a compact income/expense
  trend. Transaction rows and counterparty placeholders are reserved for the
  fullscreen view to keep the chat preview privacy-safe and glanceable.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { buildFinanceLineChartSeries, calculateFinanceTotals, normalizeFinanceOverview, type FinanceOverview, type FinanceLineChartPoint } from './financeCheckAccountsContent';

  type EmbedStatus = 'processing' | 'finished' | 'error' | 'cancelled';

  interface Props {
    id: string;
    status?: EmbedStatus;
    period?: string;
    accountCount?: number;
    account_count?: number;
    transactionCount?: number;
    transaction_count?: number;
    overview?: FinanceOverview | null;
    results?: unknown[];
    summary?: string;
    provider?: string;
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    status: statusProp = 'processing',
    period: periodProp = 'monthly',
    accountCount,
    account_count,
    transactionCount,
    transaction_count,
    overview: overviewProp = null,
    results = [],
    summary: summaryProp = '',
    provider: providerProp = 'Revolut Business',
    taskId,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  const skillName = $text('app_skills.finance.check_accounts');

  let localStatus = $state<EmbedStatus>('processing');
  let localPeriod = $state('monthly');
  let localAccountCount = $state(0);
  let localTransactionCount = $state(0);
  let localOverview = $state<FinanceOverview | null>(null);
  let localSummary = $state('');
  let localProvider = $state('Revolut Business');

  $effect(() => {
    const overview = normalizeFinanceOverview({ overview: overviewProp, results });
    localStatus = statusProp;
    localPeriod = periodProp;
    localOverview = overview;
    localAccountCount = accountCount ?? account_count ?? overview?.accounts?.length ?? 0;
    localTransactionCount = transactionCount ?? transaction_count ?? overview?.transactions?.length ?? 0;
    localSummary = summaryProp;
    localProvider = providerProp || 'Revolut Business';
  });

  let totals = $derived(calculateFinanceTotals(localOverview));
  let primaryCurrency = $derived(totals.currency);
  let chartSeries = $derived(buildFinanceLineChartSeries(localOverview));
  let trend = $derived(chartSeries.points.slice(-6));
  let incomePolyline = $derived(toPolyline(trend, 'incomeY'));
  let expensePolyline = $derived(toPolyline(trend, 'expenseY'));
  let accountLabel = $derived(localAccountCount === 1 ? 'account' : 'accounts');
  let transactionLabel = $derived(localTransactionCount === 1 ? 'transaction' : 'transactions');
  let subtitle = $derived(`${localAccountCount} ${accountLabel} · ${localTransactionCount} ${transactionLabel}`);

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (isEmbedStatus(data.status)) localStatus = data.status;
    const content = data.decodedContent;
    if (!content) return;
    if (typeof content.period === 'string') localPeriod = content.period;
    if (typeof content.account_count === 'number') localAccountCount = content.account_count;
    if (typeof content.transaction_count === 'number') localTransactionCount = content.transaction_count;
    const overview = normalizeFinanceOverview(content);
    if (overview) {
      localOverview = overview;
      if (typeof content.account_count !== 'number') localAccountCount = overview.accounts?.length ?? 0;
      if (typeof content.transaction_count !== 'number') localTransactionCount = overview.transactions?.length ?? 0;
    }
    if (typeof content.summary === 'string') localSummary = content.summary;
    if (typeof content.provider === 'string') localProvider = content.provider;
  }

  function isEmbedStatus(value: string): value is EmbedStatus {
    return value === 'processing' || value === 'finished' || value === 'error' || value === 'cancelled';
  }

  function formatMoney(value: number | null | undefined, currency = primaryCurrency): string {
    if (value === null || value === undefined || !Number.isFinite(value)) return 'No balance';
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      maximumFractionDigits: Math.abs(value) >= 1000 ? 0 : 2,
    }).format(value);
  }

  function formatPeriod(value: string): string {
    return value.replace(/_/g, ' ');
  }

  function toPolyline(points: FinanceLineChartPoint[], key: 'incomeY' | 'expenseY'): string {
    if (points.length === 0) return '';
    return points.map((point, index) => {
      const x = points.length === 1 ? 50 : Math.round((index / (points.length - 1)) * 10000) / 100;
      return `${x},${point[key]}`;
    }).join(' ');
  }

  function handleStop() {
    // Check accounts runs are synchronous once the skill starts; there is no per-skill stop action.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="finance"
  skillId="check_accounts"
  skillIconName="finance"
  status={localStatus}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  customStatusText={subtitle}
  showStatus={true}
  showSkillIcon={true}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <section class="finance-preview" class:mobile={isMobileLayout} data-testid="finance-check-accounts-preview">
      <div class="headline">
        <span class="label">Net cash flow</span>
        <strong data-testid="finance-net-cash-flow"><span data-testid="finance-total-value">{formatMoney(totals.netCashFlow)}</span></strong>
      </div>

      <div class="preview-meta">
        <span class="provider-pill" data-testid="finance-provider-pill"><i></i>{localProvider}</span>
        <span>{formatPeriod(localPeriod)}</span>
        <span>Cash balance {formatMoney(totals.cashBalance)}</span>
      </div>

      {#if trend.length > 0}
        <div class="trend" aria-label="Income and expenses over time" data-testid="finance-income-expense-chart" data-chart-type="line">
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            <polyline data-testid="finance-income-line" class="line income-line" points={incomePolyline}></polyline>
            <polyline data-testid="finance-expense-line" class="line expense-line" points={expensePolyline}></polyline>
          </svg>
          <div class="bucket-labels" aria-hidden="true">
            {#each trend as bucket}
              <span title={bucket.bucket}>{bucket.bucket.slice(5) || bucket.bucket}</span>
            {/each}
          </div>
        </div>
        <div class="legend" aria-hidden="true">
          <span><i class="income-dot"></i>Income {formatMoney(totals.income)}</span>
          <span><i class="expense-dot"></i>Expenses {formatMoney(totals.expenses)}</span>
        </div>
      {:else}
        <p class="summary">{localSummary || subtitle}</p>
      {/if}
    </section>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .finance-preview {
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
    gap: 7px;
    min-height: 0;
    padding-block: 1px;
  }

  .finance-preview.mobile {
    justify-content: flex-start;
  }

  .headline {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }

  .label {
    color: var(--color-font-secondary);
    font-size: var(--font-size-xxs);
    font-weight: 720;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  strong {
    overflow: hidden;
    color: var(--color-font-primary);
    font-size: var(--font-size-lg);
    line-height: 1.05;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .preview-meta,
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
    text-transform: capitalize;
  }

  .provider-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    text-transform: none;
  }

  .provider-pill i {
    width: 13px;
    height: 13px;
    border-radius: var(--radius-full);
    background: var(--color-font-secondary);
    -webkit-mask: url('@openmates/ui/static/icons/revolut_business.svg') center / contain no-repeat;
    mask: url('@openmates/ui/static/icons/revolut_business.svg') center / contain no-repeat;
  }

  .trend {
    position: relative;
    min-height: 48px;
    padding: 6px 10px 15px;
    border-radius: var(--radius-full);
    background:
      radial-gradient(circle at 12% 0%, color-mix(in srgb, var(--color-app-finance-end) 20%, transparent), transparent 48%),
      color-mix(in srgb, var(--color-grey-0) 84%, transparent);
    border: 1px solid color-mix(in srgb, var(--color-app-finance-start) 16%, var(--color-grey-20));
  }

  svg {
    display: block;
    width: 100%;
    height: 34px;
    overflow: visible;
  }

  .line {
    fill: none;
    stroke-linecap: round;
    stroke-linejoin: round;
    stroke-width: 4;
    vector-effect: non-scaling-stroke;
  }

  .income-line { stroke: var(--color-app-finance-end); }
  .expense-line { stroke: var(--color-warning); }

  .bucket-labels {
    position: absolute;
    right: 10px;
    bottom: 4px;
    left: 10px;
    display: flex;
    justify-content: space-between;
    gap: 4px;
    color: var(--color-font-secondary);
    font-size: var(--font-size-xxs);
  }

  .bucket-labels span {
    overflow: hidden;
    min-width: 0;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .legend span {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    text-transform: none;
  }

  .legend i {
    width: 7px;
    height: 7px;
    border-radius: var(--radius-full);
  }

  .income-dot { background: var(--color-app-finance-end); }
  .expense-dot { background: var(--color-warning); }

  .summary {
    display: -webkit-box;
    overflow: hidden;
    margin: 0;
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
    line-height: 1.35;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
    line-clamp: 3;
  }
</style>
