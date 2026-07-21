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
  import { isRecord, normalizeFinanceOverview, toNumber, type FinanceOverview, type TimeSeriesBucket } from './financeCheckAccountsContent';

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

  $effect(() => {
    const overview = normalizeFinanceOverview({ overview: overviewProp, results });
    localStatus = statusProp;
    localPeriod = periodProp;
    localOverview = overview;
    localAccountCount = accountCount ?? account_count ?? overview?.accounts?.length ?? 0;
    localTransactionCount = transactionCount ?? transaction_count ?? overview?.transactions?.length ?? 0;
    localSummary = summaryProp;
  });

  let summaries = $derived(localOverview?.summaries ?? {});
  let accounts = $derived(Array.isArray(localOverview?.accounts) ? localOverview.accounts : []);
  let totalBalance = $derived(sumBalances(accounts));
  let primaryCurrency = $derived(resolvePrimaryCurrency(accounts));
  let incomeTotal = $derived(toNumber(summaries.income_total));
  let expenseTotal = $derived(toNumber(summaries.expense_total));
  let netTotal = $derived(toNumber(summaries.net_total));
  let trend = $derived(normalizeTimeSeries(summaries.time_series));
  let trendMax = $derived(Math.max(1, ...trend.flatMap((bucket) => [bucket.income, bucket.expense])));
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
  }

  function isEmbedStatus(value: string): value is EmbedStatus {
    return value === 'processing' || value === 'finished' || value === 'error' || value === 'cancelled';
  }

  function sumBalances(items: Array<Record<string, unknown>>): number | null {
    let foundBalance = false;
    const total = items.reduce((sum, account) => {
      const balance = toNumber(account.balance);
      if (account.balance !== null && account.balance !== undefined && Number.isFinite(balance)) foundBalance = true;
      return sum + balance;
    }, 0);
    return foundBalance ? total : null;
  }

  function resolvePrimaryCurrency(items: Array<Record<string, unknown>>): string {
    const currencies = items
      .map((account) => typeof account.currency === 'string' ? account.currency : '')
      .filter(Boolean);
    return currencies[0] || 'EUR';
  }

  function normalizeTimeSeries(value: unknown): TimeSeriesBucket[] {
    if (!Array.isArray(value)) return [];
    return value
      .filter(isRecord)
      .map((bucket) => ({
        bucket: String(bucket.bucket ?? ''),
        income: Math.max(0, toNumber(bucket.income)),
        expense: Math.max(0, toNumber(bucket.expense)),
        net: toNumber(bucket.net),
        transaction_count: Math.max(0, toNumber(bucket.transaction_count)),
      }))
      .filter((bucket) => bucket.bucket);
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

  function barHeight(value: number): string {
    return `${Math.max(7, Math.round((value / trendMax) * 38))}px`;
  }

  function handleStop() {
    // Check accounts runs are synchronous once the skill starts; there is no per-skill stop action.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="finance"
  skillId="check_accounts"
  skillIconName="search"
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
        <span class="label">Current total value</span>
        <strong data-testid="finance-total-value">{formatMoney(totalBalance)}</strong>
      </div>

      <div class="preview-meta">
        <span>{formatPeriod(localPeriod)}</span>
        <span>{formatMoney(netTotal)} net</span>
      </div>

      {#if trend.length > 0}
        <div class="trend" aria-label="Income and expenses over time" data-testid="finance-income-expense-chart">
          {#each trend.slice(-6) as bucket}
            <div class="bucket" title={bucket.bucket}>
              <span class="bar income" style={`height: ${barHeight(bucket.income ?? 0)}`}></span>
              <span class="bar expense" style={`height: ${barHeight(bucket.expense ?? 0)}`}></span>
            </div>
          {/each}
        </div>
        <div class="legend" aria-hidden="true">
          <span><i class="income-dot"></i>Income {formatMoney(incomeTotal)}</span>
          <span><i class="expense-dot"></i>Expenses {formatMoney(expenseTotal)}</span>
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
    justify-content: center;
    gap: 10px;
    min-height: 100%;
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
    font-size: var(--font-size-xl);
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

  .trend {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    align-items: end;
    gap: 7px;
    min-height: 46px;
    padding: 8px 10px;
    border-radius: 18px;
    background:
      radial-gradient(circle at 12% 0%, color-mix(in srgb, var(--color-app-finance-end) 20%, transparent), transparent 48%),
      color-mix(in srgb, var(--color-grey-0) 84%, transparent);
    border: 1px solid color-mix(in srgb, var(--color-app-finance-start) 16%, var(--color-grey-20));
  }

  .bucket {
    display: flex;
    align-items: end;
    justify-content: center;
    gap: 3px;
    min-width: 0;
  }

  .bar {
    width: 7px;
    min-height: 7px;
    border-radius: 999px 999px 2px 2px;
  }

  .income { background: var(--color-app-finance-end); }
  .expense { background: var(--color-warning); }

  .legend span {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    text-transform: none;
  }

  .legend i {
    width: 7px;
    height: 7px;
    border-radius: 999px;
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
