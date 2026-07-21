// frontend/packages/ui/src/components/embeds/finance/__tests__/financeCheckAccountsContent.test.ts
// Unit coverage for Finance / Check accounts embed content normalization.
// Real saved app-skill-use embeds arrive as TOON-flattened result rows, while
// preview fixtures often use the nested skill response shape directly.
// These assertions keep the shared renderer contract stable for both paths.

import { describe, expect, it } from 'vitest';
import { normalizeFinanceOverview } from '../financeCheckAccountsContent';

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
});
