/**
 * Preview fixtures for Finance / Check accounts fullscreen embeds.
 * The fullscreen consumes data.decodedContent, matching persisted app-skill-use
 * payloads created by the backend skill.
 */

import { financeCheckAccountsPreviewOverview as overview } from './FinanceCheckAccountsEmbedPreview.preview';

const decodedContent = {
  app_id: 'finance',
  skill_id: 'check_accounts',
  status: 'finished' as const,
  period: 'monthly',
  account_count: overview.accounts.length,
  transaction_count: overview.transactions.length,
  provider: 'Revolut Business',
  overview,
  summary: 'Finance overview for 2 accounts and 5 transactions: income 8000, expenses 2291.25.',
};

const defaultProps = {
  embedId: 'preview-finance-check-accounts',
  data: {
    decodedContent,
    embedData: { status: 'finished' },
    attrs: { app_id: 'finance', skill_id: 'check_accounts' },
  },
  onClose: () => {},
  hasPreviousEmbed: false,
  hasNextEmbed: false,
};

export default defaultProps;

export const variants = {
  filtered: {
    ...defaultProps,
    embedId: 'preview-finance-check-accounts-filtered',
  },
};
