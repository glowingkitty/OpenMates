import type { ConnectedAccountSummary } from '../../../services/connectedAccountStorageService';

const account: ConnectedAccountSummary = {
  id: 'preview-figma-account',
  provider_id: 'figma',
  app_id: 'design',
  account_ref: 'preview-figma-ref',
  label: 'Dana Designer (dana@example.org)',
  capabilities: ['read'],
  runtime_modes: {}
};

export default { previewAccounts: [] };

export const variants = {
  noAccounts: { previewAccounts: [] },
  connected: { previewAccounts: [account] },
  notConfigured: { previewAccounts: [], previewNotConfigured: true }
};
