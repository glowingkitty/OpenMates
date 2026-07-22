/**
 * frontend/packages/ui/src/components/embeds/finance/financeCheckAccountsContent.ts
 *
 * Shared normalization helpers for Finance / Check accounts embeds.
 * Saved app-skill-use embeds are TOON-flattened for compact storage, while
 * previews and tests may still pass the nested skill response shape directly.
 * These helpers keep both shapes rendering through one UI contract.
 */

export interface TimeSeriesBucket {
  bucket: string;
  income?: number;
  expense?: number;
  net?: number;
  transaction_count?: number;
}

export interface FinanceOverview {
  accounts?: Array<Record<string, unknown>>;
  transactions?: Array<Record<string, unknown>>;
  summaries?: {
    income_total?: number;
    expense_total?: number;
    net_total?: number;
    time_series?: TimeSeriesBucket[];
    [key: string]: unknown;
  };
  filter_options?: Record<string, string[]>;
  privacy?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface FinanceTotals {
  cashBalance: number | null;
  currency: string;
  expenses: number;
  income: number;
  netCashFlow: number;
}

export interface FinanceLineChartPoint {
  bucket: string;
  income: number;
  expense: number;
  incomeY: number;
  expenseY: number;
}

export interface FinanceLineChartSeries {
  maxValue: number;
  points: FinanceLineChartPoint[];
}

interface FinancePIIMapping {
  placeholder: string;
  original: string;
  type?: string;
}

const FILTER_OPTION_KEYS = ['accounts', 'sources', 'categories', 'directions', 'states', 'placeholders'];

export function normalizeFinanceOverview(content: unknown): FinanceOverview | null {
  if (!isRecord(content)) return null;
  if (isRecord(content.overview)) return content.overview as FinanceOverview;

  const result = firstResult(content) ?? content;
  if (isRecord(result.overview)) return result.overview as FinanceOverview;
  if (!hasFlattenedOverview(result)) return null;

  const summaries = collectPrefixedFields(result, 'overview_summaries_');
  const filterOptions = collectFilterOptions(result);
  const privacy = collectPrefixedFields(result, 'overview_privacy_');

  return {
    accounts: normalizeRecordArray(result.overview_accounts),
    transactions: normalizeRecordArray(result.overview_transactions),
    summaries: Object.keys(summaries).length > 0 ? summaries : undefined,
    filter_options: Object.keys(filterOptions).length > 0 ? filterOptions : undefined,
    privacy: Object.keys(privacy).length > 0 ? privacy : undefined,
  };
}

export function toNumber(value: unknown): number {
  const numeric = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

export function calculateFinanceTotals(overview: FinanceOverview | null): FinanceTotals {
  const accounts = Array.isArray(overview?.accounts) ? overview.accounts : [];
  const transactions = Array.isArray(overview?.transactions) ? overview.transactions : [];
  const summaries = overview?.summaries ?? {};
  const summaryIncome = readFiniteNumber(summaries.income_total);
  const summaryExpense = readFiniteNumber(summaries.expense_total);
  const summaryNet = readFiniteNumber(summaries.net_total);
  const transactionTotals = calculateTransactionTotals(transactions);
  const income = summaryIncome ?? transactionTotals.income;
  const expenses = summaryExpense ?? transactionTotals.expenses;

  return {
    cashBalance: sumCashBalances(accounts),
    currency: resolvePrimaryCurrency(accounts, transactions),
    expenses,
    income,
    netCashFlow: summaryNet ?? income - expenses,
  };
}

export function buildFinanceLineChartSeries(overview: FinanceOverview | null): FinanceLineChartSeries {
  const buckets = normalizeTimeSeries(overview?.summaries?.time_series).sort((a, b) => a.bucket.localeCompare(b.bucket));
  const maxValue = Math.max(1, ...buckets.flatMap((bucket) => [toNumber(bucket.income), toNumber(bucket.expense)]));
  return {
    maxValue,
    points: buckets.map((bucket) => {
      const income = Math.max(0, toNumber(bucket.income));
      const expense = Math.max(0, toNumber(bucket.expense));
      return {
        bucket: bucket.bucket,
        income,
        expense,
        incomeY: toLineChartY(income, maxValue),
        expenseY: toLineChartY(expense, maxValue),
      };
    }),
  };
}

export function resolveFinanceCounterpartyLabel(
  placeholder: string,
  mappings: FinancePIIMapping[],
  revealed: boolean,
): string {
  if (!revealed || !placeholder || mappings.length === 0) return placeholder;
  return mappings.find((mapping) => mapping.placeholder === placeholder)?.original ?? placeholder;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function firstResult(content: Record<string, unknown>): Record<string, unknown> | null {
  const results = content.results;
  if (!Array.isArray(results)) return null;
  const first = results[0];
  return isRecord(first) ? first : null;
}

function hasFlattenedOverview(value: Record<string, unknown>): boolean {
  return Object.keys(value).some((key) => key.startsWith('overview_'));
}

function normalizeRecordArray(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord);
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

function calculateTransactionTotals(items: Array<Record<string, unknown>>): { income: number; expenses: number } {
  return items.reduce<{ income: number; expenses: number }>((totals, item) => {
    const amount = toNumber(item.amount);
    if (item.direction === 'income') totals.income += amount;
    if (item.direction === 'expense') totals.expenses += Math.abs(amount);
    return totals;
  }, { income: 0, expenses: 0 });
}

function sumCashBalances(items: Array<Record<string, unknown>>): number | null {
  let foundBalance = false;
  const total = items.reduce((sum, account) => {
    const balance = readFiniteNumber(account.balance);
    if (balance === null) return sum;
    foundBalance = true;
    return sum + balance;
  }, 0);
  return foundBalance ? total : null;
}

function resolvePrimaryCurrency(accounts: Array<Record<string, unknown>>, transactions: Array<Record<string, unknown>>): string {
  for (const item of [...accounts, ...transactions]) {
    if (typeof item.currency === 'string' && item.currency.trim()) return item.currency;
  }
  return 'EUR';
}

function readFiniteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const numeric = toNumber(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function toLineChartY(value: number, maxValue: number): number {
  return Math.round((100 - (value / Math.max(1, maxValue)) * 100) * 100) / 100;
}

function collectPrefixedFields(source: Record<string, unknown>, prefix: string): Record<string, unknown> {
  const target: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(source)) {
    if (!key.startsWith(prefix)) continue;
    const targetKey = key.slice(prefix.length);
    target[targetKey] = value;
  }
  return target;
}

function collectFilterOptions(source: Record<string, unknown>): Record<string, string[]> {
  const options: Record<string, string[]> = {};
  for (const key of FILTER_OPTION_KEYS) {
    const value = source[`overview_filter_options_${key}`];
    const normalized = normalizeStringList(value);
    if (normalized.length > 0) options[key] = normalized;
  }
  return options;
}

function normalizeStringList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item || '').trim()).filter(Boolean);
  if (typeof value === 'string') return value.split('|').map((item) => item.trim()).filter(Boolean);
  return [];
}
