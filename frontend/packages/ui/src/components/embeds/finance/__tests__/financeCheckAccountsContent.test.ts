// frontend/packages/ui/src/components/embeds/finance/__tests__/financeCheckAccountsContent.test.ts
// Unit coverage for Finance / Check accounts embed content normalization.
// Real saved app-skill-use embeds arrive as TOON-flattened result rows, while
// preview fixtures often use the nested skill response shape directly.
// These assertions keep the shared renderer contract stable for both paths.

import { describe, expect, it } from 'vitest';
import {
  buildFinanceLineChartSeries,
  calculateFinanceTotals,
  normalizeFinanceOverview,
  resolveFinanceCounterpartyLabel,
} from '../financeCheckAccountsContent';

describe('finance check accounts content normalization', () => {
  it('reconstructs overview from flattened persisted result payloads', () => {
    const overview = normalizeFinanceOverview({
      app_id: 'finance',
      skill_id: 'check_accounts',
      results: [
        {
          overview_accounts: [
            { account_ref: 'cash', source_ref: 'csv:cash.csv', display_label: 'Cash account', currency: 'EUR', balance: 1450 },
          ],
          overview_transactions: [
            {
              transaction_ref: 'csv:1',
              account_ref: 'cash',
              source_ref: 'csv:cash.csv',
              posted_at: '2026-01-04',
              amount: 1000,
              currency: 'EUR',
              direction: 'income',
              category: 'payroll',
              counterparty_placeholder: '[PAYER_PAYROLL_001]',
            },
          ],
          overview_summaries_income_total: 1000,
          overview_summaries_expense_total: 50,
          overview_summaries_net_total: 950,
          overview_summaries_time_series: [
            { bucket: '2026-01', income: 1000, expense: 50, net: 950, transaction_count: 2 },
          ],
          overview_filter_options_sources: 'csv:cash.csv|revolut:sandbox',
          overview_filter_options_categories: ['payroll', 'groceries'],
        },
      ],
    });

    expect(overview?.accounts).toHaveLength(1);
    expect(overview?.transactions).toHaveLength(1);
    expect(overview?.summaries?.income_total).toBe(1000);
    expect(overview?.summaries?.time_series).toEqual([
      { bucket: '2026-01', income: 1000, expense: 50, net: 950, transaction_count: 2 },
    ]);
    expect(overview?.filter_options?.sources).toEqual(['csv:cash.csv', 'revolut:sandbox']);
    expect(overview?.filter_options?.categories).toEqual(['payroll', 'groceries']);
  });

  it('computes net cash flow as the primary total with income, expenses, and cash balance as secondary totals', () => {
    const overview = normalizeFinanceOverview({
      overview: {
        accounts: [
          { account_ref: 'operating', currency: 'EUR', balance: 1200 },
          { account_ref: 'tax', currency: 'EUR', balance: 300 },
        ],
        transactions: [
          { posted_at: '2026-01-03', amount: 1000, currency: 'EUR', direction: 'income' },
          { posted_at: '2026-01-10', amount: -1300, currency: 'EUR', direction: 'expense' },
        ],
        summaries: { income_total: 1000, expense_total: 1300, net_total: -300 },
      },
    });

    expect(calculateFinanceTotals(overview)).toEqual({
      cashBalance: 1500,
      currency: 'EUR',
      expenses: 1300,
      income: 1000,
      netCashFlow: -300,
    });
  });

  it('builds left-to-right income and expense line chart points without clipping zero buckets', () => {
    const overview = normalizeFinanceOverview({
      overview: {
        summaries: {
          time_series: [
            { bucket: '2026-01', income: 0, expense: 400, net: -400, transaction_count: 1 },
            { bucket: '2026-02', income: 2000, expense: 0, net: 2000, transaction_count: 1 },
            { bucket: '2026-03', income: 1200, expense: 800, net: 400, transaction_count: 2 },
          ],
        },
      },
    });

    expect(buildFinanceLineChartSeries(overview)).toEqual({
      maxValue: 2000,
      points: [
        { bucket: '2026-01', income: 0, expense: 400, incomeY: 100, expenseY: 80 },
        { bucket: '2026-02', income: 2000, expense: 0, incomeY: 0, expenseY: 100 },
        { bucket: '2026-03', income: 1200, expense: 800, incomeY: 40, expenseY: 60 },
      ],
    });
  });

  it('restores Finance counterparty placeholders only when owner PII is revealed', () => {
    const mappings = [
      { placeholder: '[MERCHANT_SOFTWARE_001]', original: 'Acme Software Ltd', type: 'merchant' },
    ];

    expect(resolveFinanceCounterpartyLabel('[MERCHANT_SOFTWARE_001]', mappings, false)).toBe('[MERCHANT_SOFTWARE_001]');
    expect(resolveFinanceCounterpartyLabel('[MERCHANT_SOFTWARE_001]', mappings, true)).toBe('Acme Software Ltd');
    expect(resolveFinanceCounterpartyLabel('[PAYER_REVENUE_001]', mappings, true)).toBe('[PAYER_REVENUE_001]');
  });
});
