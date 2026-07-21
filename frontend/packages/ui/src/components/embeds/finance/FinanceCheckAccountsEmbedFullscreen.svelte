<!--
  frontend/packages/ui/src/components/embeds/finance/FinanceCheckAccountsEmbedFullscreen.svelte

  Fullscreen view for Finance / Check accounts.
  It renders filters, aggregate charts, accounts, and the redacted normalized
  transaction list from saved embed data only. No provider data is fetched here.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { normalizeFinanceOverview, toNumber } from './financeCheckAccountsContent';

  type EmbedStatus = 'processing' | 'finished' | 'error' | 'cancelled';

  interface FinanceAccount {
    account_ref: string;
    source_ref: string;
    display_label: string;
    currency: string;
    balance?: number | null;
    balance_as_of?: string | null;
  }

  interface FinanceTransaction {
    transaction_ref: string;
    account_ref: string;
    source_ref: string;
    posted_at: string;
    amount: number;
    currency: string;
    direction: string;
    category: string;
    counterparty_placeholder: string;
    state?: string;
  }

  interface TimeSeriesBucket {
    bucket: string;
    income: number;
    expense: number;
    net: number;
    transaction_count: number;
  }

  interface FinanceOverview {
    accounts?: FinanceAccount[];
    transactions?: FinanceTransaction[];
    summaries?: Record<string, unknown>;
    filter_options?: Record<string, string[]>;
    [key: string]: unknown;
  }

  interface Props {
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
  }: Props = $props();

  const skillName = $text('app_skills.finance.check_accounts');

  let localStatus = $state<EmbedStatus>('finished');
  let localPeriod = $state('monthly');
  let localOverview = $state<FinanceOverview | null>(null);
  let localSummary = $state('');

  let selectedAccount = $state('');
  let selectedSource = $state('');
  let selectedCategory = $state('');
  let selectedDirection = $state('');
  let selectedState = $state('');
  let selectedPlaceholder = $state('');
  let startDate = $state('');
  let endDate = $state('');

  $effect(() => {
    const content = data.decodedContent ?? {};
    localStatus = normalizeStatus(content.status ?? data.embedData?.status);
    localPeriod = typeof content.period === 'string' ? content.period : 'monthly';
    localOverview = normalizeFinanceOverview(content) as FinanceOverview | null;
    localSummary = typeof content.summary === 'string' ? content.summary : '';
  });

  let accounts = $derived(Array.isArray(localOverview?.accounts) ? localOverview.accounts : []);
  let transactions = $derived(Array.isArray(localOverview?.transactions) ? localOverview.transactions : []);
  let summaries = $derived(localOverview?.summaries ?? {});
  let filteredTransactions = $derived(filterTransactions(transactions));
  let filteredAccountRefs = $derived(new Set(filteredTransactions.map((item) => item.account_ref)));
  let filteredAccounts = $derived(accounts.filter((account) => !selectedAccount || account.account_ref === selectedAccount || filteredAccountRefs.has(account.account_ref)));
  let totalBalance = $derived(sumBalances(filteredAccounts));
  let primaryCurrency = $derived(resolvePrimaryCurrency(filteredAccounts, filteredTransactions));
  let filteredTotals = $derived(calculateTotals(filteredTransactions));
  let filteredTrend = $derived(buildFilteredTrend(filteredTransactions, localPeriod));
  let trendMax = $derived(Math.max(1, ...filteredTrend.flatMap((bucket) => [bucket.income, bucket.expense])));
  let hasFilters = $derived(Boolean(selectedAccount || selectedSource || selectedCategory || selectedDirection || selectedState || selectedPlaceholder || startDate || endDate));

  let filterOptions = $derived(localOverview?.filter_options ?? {});
  let accountOptions = $derived(optionList(filterOptions.accounts, accounts.map((account) => account.account_ref)));
  let sourceOptions = $derived(optionList(filterOptions.sources, [...accounts.map((account) => account.source_ref), ...transactions.map((item) => item.source_ref)]));
  let categoryOptions = $derived(optionList(filterOptions.categories, transactions.map((item) => item.category)));
  let directionOptions = $derived(optionList(filterOptions.directions, transactions.map((item) => item.direction)));
  let stateOptions = $derived(optionList(filterOptions.states, transactions.map((item) => item.state ?? '')));
  let placeholderOptions = $derived(optionList(filterOptions.placeholders, transactions.map((item) => item.counterparty_placeholder)));

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    localStatus = normalizeStatus(data.status);
    const content = data.decodedContent;
    if (!content) return;
    if (typeof content.period === 'string') localPeriod = content.period;
    const overview = normalizeFinanceOverview(content) as FinanceOverview | null;
    if (overview) localOverview = overview;
    if (typeof content.summary === 'string') localSummary = content.summary;
  }

  function normalizeStatus(value: unknown): EmbedStatus {
    if (value === 'processing' || value === 'finished' || value === 'error' || value === 'cancelled') return value;
    return 'finished';
  }

  function optionList(preferred: unknown, fallback: string[]): string[] {
    const values = Array.isArray(preferred) ? preferred : fallback;
    return [...new Set(values.map((item) => String(item || '').trim()).filter(Boolean))].sort();
  }

  function filterTransactions(items: FinanceTransaction[]): FinanceTransaction[] {
    return items.filter((item) => {
      const postedAt = String(item.posted_at || '').slice(0, 10);
      if (startDate && postedAt < startDate) return false;
      if (endDate && postedAt > endDate) return false;
      if (selectedAccount && item.account_ref !== selectedAccount) return false;
      if (selectedSource && item.source_ref !== selectedSource) return false;
      if (selectedCategory && item.category !== selectedCategory) return false;
      if (selectedDirection && item.direction !== selectedDirection) return false;
      if (selectedState && (item.state ?? '') !== selectedState) return false;
      if (selectedPlaceholder && item.counterparty_placeholder !== selectedPlaceholder) return false;
      return true;
    });
  }

  function sumBalances(items: FinanceAccount[]): number | null {
    let foundBalance = false;
    const total = items.reduce((sum, account) => {
      if (account.balance === null || account.balance === undefined) return sum;
      foundBalance = true;
      return sum + toNumber(account.balance);
    }, 0);
    return foundBalance ? total : null;
  }

  function resolvePrimaryCurrency(items: FinanceAccount[], txs: FinanceTransaction[]): string {
    return items.find((account) => account.currency)?.currency || txs.find((item) => item.currency)?.currency || 'EUR';
  }

  function calculateTotals(items: FinanceTransaction[]): { income: number; expense: number; net: number } {
    return items.reduce((totals, item) => {
      const amount = toNumber(item.amount);
      if (item.direction === 'income') totals.income += amount;
      if (item.direction === 'expense') totals.expense += Math.abs(amount);
      totals.net = totals.income - totals.expense;
      return totals;
    }, { income: 0, expense: 0, net: 0 });
  }

  function buildFilteredTrend(items: FinanceTransaction[], period: string): TimeSeriesBucket[] {
    if (!hasFilters && Array.isArray(summaries.time_series)) {
      return (summaries.time_series as Array<Record<string, unknown>>).map((bucket) => ({
        bucket: String(bucket.bucket ?? ''),
        income: Math.max(0, toNumber(bucket.income)),
        expense: Math.max(0, toNumber(bucket.expense)),
        net: toNumber(bucket.net),
        transaction_count: Math.max(0, toNumber(bucket.transaction_count)),
      })).filter((bucket) => bucket.bucket);
    }

    const buckets = new Map<string, TimeSeriesBucket>();
    for (const item of items) {
      const key = bucketKey(item.posted_at, period);
      if (!key) continue;
      const bucket = buckets.get(key) ?? { bucket: key, income: 0, expense: 0, net: 0, transaction_count: 0 };
      const amount = toNumber(item.amount);
      if (item.direction === 'income') bucket.income += amount;
      if (item.direction === 'expense') bucket.expense += Math.abs(amount);
      bucket.net = bucket.income - bucket.expense;
      bucket.transaction_count += 1;
      buckets.set(key, bucket);
    }
    return [...buckets.values()].sort((a, b) => a.bucket.localeCompare(b.bucket));
  }

  function bucketKey(dateValue: string, period: string): string {
    const date = new Date(`${String(dateValue || '').slice(0, 10)}T00:00:00Z`);
    if (Number.isNaN(date.getTime())) return '';
    const year = date.getUTCFullYear();
    const month = date.getUTCMonth() + 1;
    if (period === 'yearly') return String(year);
    if (period === 'quarterly') return `${year}-Q${Math.floor((month - 1) / 3) + 1}`;
    return `${year}-${String(month).padStart(2, '0')}`;
  }

  function formatMoney(value: number | null | undefined, currency = primaryCurrency): string {
    if (value === null || value === undefined || !Number.isFinite(value)) return 'No balance';
    try {
      return new Intl.NumberFormat(undefined, {
        style: 'currency',
        currency,
        maximumFractionDigits: Math.abs(value) >= 1000 ? 0 : 2,
      }).format(value);
    } catch {
      return `${currency} ${new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value)}`.trim();
    }
  }

  function formatPeriod(value: string): string {
    return value.replace(/_/g, ' ');
  }

  function accountLabel(accountRef: string): string {
    return accounts.find((account) => account.account_ref === accountRef)?.display_label || accountRef;
  }

  function barHeight(value: number): string {
    return `${Math.max(8, Math.round((value / trendMax) * 92))}px`;
  }

  function resetFilters() {
    selectedAccount = '';
    selectedSource = '';
    selectedCategory = '';
    selectedDirection = '';
    selectedState = '';
    selectedPlaceholder = '';
    startDate = '';
    endDate = '';
  }
</script>

<UnifiedEmbedFullscreen
  testId="finance-check-accounts-fullscreen"
  appId="finance"
  skillId="check_accounts"
  skillIconName="search"
  embedHeaderTitle={skillName}
  embedHeaderSubtitle={`${formatPeriod(localPeriod)} · ${filteredAccounts.length} accounts · ${filteredTransactions.length} transactions`}
  onClose={onClose}
  currentEmbedId={embedId}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    {#if localStatus === 'error'}
      <div class="state-message" data-testid="finance-error-state">Finance account analysis failed.</div>
    {:else if !localOverview}
      <div class="state-message" data-testid="finance-empty-state">{localSummary || 'No account data available.'}</div>
    {:else}
      <div class="finance-fullscreen-content">
        <section class="summary-grid" aria-label="Finance summary">
          <article class="summary-card total">
            <span>Total value</span>
            <strong data-testid="finance-fullscreen-total-value">{formatMoney(totalBalance)}</strong>
          </article>
          <article class="summary-card income">
            <span>Income</span>
            <strong>{formatMoney(filteredTotals.income)}</strong>
          </article>
          <article class="summary-card expense">
            <span>Expenses</span>
            <strong>{formatMoney(filteredTotals.expense)}</strong>
          </article>
          <article class="summary-card net">
            <span>Net</span>
            <strong>{formatMoney(filteredTotals.net)}</strong>
          </article>
        </section>

        <section class="panel chart-panel" data-testid="finance-fullscreen-chart">
          <div class="section-heading">
            <div>
              <h2>Income and expenses over time</h2>
              <p>{formatPeriod(localPeriod)} buckets from the saved account snapshot.</p>
            </div>
          </div>
          {#if filteredTrend.length > 0}
            <div class="chart" aria-label="Income and expenses over time">
              {#each filteredTrend as bucket}
                <div class="chart-bucket">
                  <div class="bars">
                    <span class="bar income" style={`height: ${barHeight(bucket.income)}`} title={`Income ${formatMoney(bucket.income)}`}></span>
                    <span class="bar expense" style={`height: ${barHeight(bucket.expense)}`} title={`Expenses ${formatMoney(bucket.expense)}`}></span>
                  </div>
                  <span class="bucket-label">{bucket.bucket}</span>
                </div>
              {/each}
            </div>
          {:else}
            <p class="empty-copy">No transactions match the current filters.</p>
          {/if}
        </section>

        <section class="panel filters" data-testid="finance-filters">
          <div class="section-heading">
            <div>
              <h2>Filters</h2>
              <p>Filter saved data by account, source, date, category, direction, state, or placeholder.</p>
            </div>
            {#if hasFilters}
              <button type="button" class="reset-button" onclick={resetFilters}>Reset</button>
            {/if}
          </div>

          <div class="filter-grid">
            <label>
              Account
              <select bind:value={selectedAccount} data-testid="finance-filter-account">
                <option value="">All accounts</option>
                {#each accountOptions as accountRef}
                  <option value={accountRef}>{accountLabel(accountRef)}</option>
                {/each}
              </select>
            </label>

            <label>
              Source
              <select bind:value={selectedSource} data-testid="finance-filter-source">
                <option value="">All sources</option>
                {#each sourceOptions as source}
                  <option value={source}>{source}</option>
                {/each}
              </select>
            </label>

            <label>
              From
              <input type="date" bind:value={startDate} data-testid="finance-filter-start-date" />
            </label>

            <label>
              To
              <input type="date" bind:value={endDate} data-testid="finance-filter-end-date" />
            </label>

            <label>
              Category
              <select bind:value={selectedCategory} data-testid="finance-filter-category">
                <option value="">All categories</option>
                {#each categoryOptions as category}
                  <option value={category}>{category}</option>
                {/each}
              </select>
            </label>

            <label>
              Direction
              <select bind:value={selectedDirection} data-testid="finance-filter-direction">
                <option value="">Income and expense</option>
                {#each directionOptions as direction}
                  <option value={direction}>{direction}</option>
                {/each}
              </select>
            </label>

            <label>
              State
              <select bind:value={selectedState} data-testid="finance-filter-state">
                <option value="">All states</option>
                {#each stateOptions as state}
                  <option value={state}>{state}</option>
                {/each}
              </select>
            </label>

            <label>
              Placeholder
              <select bind:value={selectedPlaceholder} data-testid="finance-filter-placeholder">
                <option value="">All placeholders</option>
                {#each placeholderOptions as placeholder}
                  <option value={placeholder}>{placeholder}</option>
                {/each}
              </select>
            </label>
          </div>
        </section>

        <section class="panel accounts" data-testid="finance-account-list">
          <div class="section-heading">
            <div>
              <h2>Accounts</h2>
              <p>{filteredAccounts.length} account{filteredAccounts.length === 1 ? '' : 's'} in view.</p>
            </div>
          </div>
          <div class="account-grid">
            {#each filteredAccounts as account}
              <article class="account-card">
                <span>{account.display_label || account.account_ref}</span>
                <strong>{formatMoney(account.balance ?? null, account.currency || primaryCurrency)}</strong>
                <small>{account.source_ref}{account.balance_as_of ? ` · ${account.balance_as_of}` : ''}</small>
              </article>
            {/each}
          </div>
        </section>

        <section class="panel transactions" data-testid="finance-transaction-list">
          <div class="section-heading">
            <div>
              <h2>Transactions</h2>
              <p>{filteredTransactions.length} redacted transaction{filteredTransactions.length === 1 ? '' : 's'} match.</p>
            </div>
          </div>

          {#if filteredTransactions.length > 0}
            <div class="transaction-table" role="table" aria-label="Filtered Finance transactions">
              <div class="transaction-row header" role="row">
                <span>Date</span>
                <span>Counterparty</span>
                <span>Category</span>
                <span>Account</span>
                <span>Amount</span>
                <span>State</span>
              </div>
              {#each filteredTransactions as transaction}
                <div class="transaction-row" role="row" data-testid="finance-transaction-row">
                  <span>{transaction.posted_at}</span>
                  <span class="placeholder">{transaction.counterparty_placeholder}</span>
                  <span>{transaction.category}</span>
                  <span>{accountLabel(transaction.account_ref)}</span>
                  <span class:negative={transaction.direction === 'expense'} class:positive={transaction.direction === 'income'}>
                    {formatMoney(transaction.amount, transaction.currency || primaryCurrency)}
                  </span>
                  <span>{transaction.state || 'unknown'}</span>
                </div>
              {/each}
            </div>
          {:else}
            <p class="empty-copy">No transactions match the current filters.</p>
          {/if}
        </section>
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .state-message {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 240px;
    color: var(--color-font-secondary);
    font-size: var(--font-size-p);
  }

  .finance-fullscreen-content {
    display: flex;
    flex-direction: column;
    gap: 18px;
    width: min(1120px, calc(100% - 32px));
    margin: 0 auto;
    padding: 32px 0 120px;
  }

  .summary-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
  }

  .summary-card,
  .panel {
    border: 1px solid color-mix(in srgb, var(--color-app-finance-start) 14%, var(--color-grey-20));
    background: color-mix(in srgb, var(--color-grey-0) 92%, transparent);
    box-shadow: 0 18px 55px color-mix(in srgb, var(--color-app-finance-start) 7%, transparent);
  }

  .summary-card {
    display: flex;
    flex-direction: column;
    gap: 7px;
    min-width: 0;
    padding: 18px;
    border-radius: 24px;
  }

  .summary-card.total {
    background:
      radial-gradient(circle at 10% 0%, color-mix(in srgb, var(--color-app-finance-end) 24%, transparent), transparent 52%),
      color-mix(in srgb, var(--color-grey-0) 90%, transparent);
  }

  .summary-card span,
  .section-heading p,
  .empty-copy,
  label,
  small {
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
  }

  .summary-card strong {
    overflow: hidden;
    color: var(--color-font-primary);
    font-size: var(--font-size-xl);
    line-height: 1.08;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .summary-card.income strong,
  .positive { color: var(--color-app-finance-end); }

  .summary-card.expense strong,
  .negative { color: var(--color-warning); }

  .panel {
    padding: 20px;
    border-radius: 28px;
  }

  .section-heading {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 16px;
  }

  h2,
  p {
    margin: 0;
  }

  h2 {
    color: var(--color-font-primary);
    font-size: var(--font-size-lg);
    line-height: 1.2;
  }

  .chart {
    display: flex;
    align-items: stretch;
    gap: 12px;
    min-height: 150px;
    overflow-x: auto;
    padding: 12px 4px 4px;
  }

  .chart-bucket {
    display: flex;
    flex: 1 0 72px;
    flex-direction: column;
    justify-content: flex-end;
    gap: 8px;
    min-width: 72px;
  }

  .bars {
    display: flex;
    align-items: flex-end;
    justify-content: center;
    gap: 7px;
    min-height: 100px;
    padding: 0 8px;
    border-radius: 18px;
    background: color-mix(in srgb, var(--color-grey-10) 62%, transparent);
  }

  .bar {
    width: 16px;
    min-height: 8px;
    border-radius: 999px 999px 4px 4px;
  }

  .bar.income { background: var(--color-app-finance-end); }
  .bar.expense { background: var(--color-warning); }

  .bucket-label {
    overflow: hidden;
    color: var(--color-font-secondary);
    font-size: var(--font-size-xxs);
    text-align: center;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .filter-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-weight: 650;
  }

  select,
  input {
    width: 100%;
    min-height: 40px;
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-6);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    font: inherit;
    padding: 0 12px;
  }

  .reset-button {
    border: 1px solid color-mix(in srgb, var(--color-app-finance-start) 22%, var(--color-grey-30));
    border-radius: var(--radius-full);
    background: color-mix(in srgb, var(--color-app-finance-end) 10%, var(--color-grey-0));
    color: var(--color-font-primary);
    cursor: pointer;
    font: inherit;
    font-size: var(--font-size-xs);
    font-weight: 700;
    padding: 8px 12px;
  }

  .account-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 12px;
  }

  .account-card {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
    padding: 14px;
    border-radius: var(--radius-8);
    background: color-mix(in srgb, var(--color-grey-10) 68%, transparent);
  }

  .account-card span,
  .account-card strong {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .account-card span,
  .transaction-row span {
    color: var(--color-font-primary);
  }

  .transaction-table {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-8);
  }

  .transaction-row {
    display: grid;
    grid-template-columns: 110px minmax(180px, 1.4fr) minmax(110px, 1fr) minmax(140px, 1fr) minmax(100px, 0.8fr) minmax(90px, 0.7fr);
    gap: 12px;
    align-items: center;
    padding: 12px 14px;
    border-bottom: 1px solid var(--color-grey-20);
    font-size: var(--font-size-xs);
  }

  .transaction-row:last-child { border-bottom: 0; }

  .transaction-row.header {
    background: color-mix(in srgb, var(--color-app-finance-end) 9%, var(--color-grey-10));
    color: var(--color-font-secondary);
    font-weight: 760;
    text-transform: uppercase;
  }

  .transaction-row span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .placeholder {
    font-family: 'Courier New', Courier, monospace;
    font-size: var(--font-size-xxs);
  }

  @media (max-width: 900px) {
    .summary-grid,
    .filter-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .transaction-table {
      overflow-x: auto;
    }

    .transaction-row {
      min-width: 760px;
    }
  }

  @media (max-width: 560px) {
    .finance-fullscreen-content {
      width: calc(100% - 20px);
      padding-top: 20px;
    }

    .summary-grid,
    .filter-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
