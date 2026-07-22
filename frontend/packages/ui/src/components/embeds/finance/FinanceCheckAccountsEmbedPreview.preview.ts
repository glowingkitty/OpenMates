/**
 * Preview fixtures for Finance / Check accounts preview embeds.
 * The sample data mirrors persisted normalized skill output and contains only
 * synthetic account labels plus redacted counterparty placeholders.
 */

const overview = {
  accounts: [
    {
      account_ref: 'acct-main-eur',
      source_ref: 'revolut_business:connected-account',
      display_label: 'Operating EUR',
      currency: 'EUR',
      balance: 8450.25,
      balance_as_of: '2026-07-15',
    },
    {
      account_ref: 'acct-savings-eur',
      source_ref: 'revolut_business:connected-account',
      display_label: 'Savings EUR',
      currency: 'EUR',
      balance: 12500,
      balance_as_of: '2026-07-15',
    },
  ],
  transactions: [
    {
      transaction_ref: 'revolut_business:tx-001',
      account_ref: 'acct-main-eur',
      source_ref: 'revolut_business:connected-account',
      posted_at: '2026-05-05',
      amount: 4200,
      currency: 'EUR',
      direction: 'income',
      category: 'revenue',
      counterparty_placeholder: '[PAYER_REVENUE_001]',
      state: 'completed',
    },
    {
      transaction_ref: 'revolut_business:tx-002',
      account_ref: 'acct-main-eur',
      source_ref: 'revolut_business:connected-account',
      posted_at: '2026-05-08',
      amount: -760.8,
      currency: 'EUR',
      direction: 'expense',
      category: 'software',
      counterparty_placeholder: '[MERCHANT_SOFTWARE_001]',
      state: 'completed',
    },
    {
      transaction_ref: 'revolut_business:tx-003',
      account_ref: 'acct-savings-eur',
      source_ref: 'revolut_business:connected-account',
      posted_at: '2026-06-03',
      amount: 3800,
      currency: 'EUR',
      direction: 'income',
      category: 'revenue',
      counterparty_placeholder: '[PAYER_REVENUE_002]',
      state: 'completed',
    },
    {
      transaction_ref: 'revolut_business:tx-004',
      account_ref: 'acct-main-eur',
      source_ref: 'revolut_business:connected-account',
      posted_at: '2026-06-12',
      amount: -1180.45,
      currency: 'EUR',
      direction: 'expense',
      category: 'travel',
      counterparty_placeholder: '[MERCHANT_TRAVEL_001]',
      state: 'completed',
    },
    {
      transaction_ref: 'revolut_business:tx-005',
      account_ref: 'acct-main-eur',
      source_ref: 'revolut_business:connected-account',
      posted_at: '2026-07-02',
      amount: -350,
      currency: 'EUR',
      direction: 'expense',
      category: 'meals',
      counterparty_placeholder: '[MERCHANT_MEALS_001]',
      state: 'completed',
    },
  ],
  summaries: {
    period: 'monthly',
    income_total: 8000,
    expense_total: 2291.25,
    net_total: 5708.75,
    by_category: {
      revenue: { income: 8000, expense: 0, net: 8000 },
      software: { income: 0, expense: 760.8, net: -760.8 },
      travel: { income: 0, expense: 1180.45, net: -1180.45 },
      meals: { income: 0, expense: 350, net: -350 },
    },
    time_series: [
      { bucket: '2026-05', income: 4200, expense: 760.8, net: 3439.2, transaction_count: 2 },
      { bucket: '2026-06', income: 3800, expense: 1180.45, net: 2619.55, transaction_count: 2 },
      { bucket: '2026-07', income: 0, expense: 350, net: -350, transaction_count: 1 },
    ],
    filters_applied: {},
  },
  filter_options: {
    accounts: ['acct-main-eur', 'acct-savings-eur'],
    sources: ['revolut_business:connected-account'],
    categories: ['meals', 'revenue', 'software', 'travel'],
    directions: ['expense', 'income'],
    states: ['completed'],
    placeholders: ['[MERCHANT_MEALS_001]', '[MERCHANT_SOFTWARE_001]', '[MERCHANT_TRAVEL_001]', '[PAYER_REVENUE_001]', '[PAYER_REVENUE_002]'],
  },
};

const defaultProps = {
  id: 'preview-finance-check-accounts',
  status: 'finished' as const,
  period: 'monthly',
  accountCount: overview.accounts.length,
  transactionCount: overview.transactions.length,
  overview,
  provider: 'Revolut Business',
  summary: 'Finance overview for 2 accounts and 5 transactions: income 8000, expenses 2291.25.',
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  mobile: { ...defaultProps, id: 'preview-finance-check-accounts-mobile', isMobile: true },
  processing: {
    ...defaultProps,
    id: 'preview-finance-check-accounts-processing',
    status: 'processing' as const,
    overview: null,
    accountCount: 0,
    transactionCount: 0,
    summary: 'Checking connected accounts and statements...',
  },
};

export { overview as financeCheckAccountsPreviewOverview };
