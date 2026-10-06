import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../config/api', () => ({
  getApiEndpoint: (path: string) => `https://api.test${path}`,
  apiEndpoints: {
    payments: {
      listPaymentMethods: '/v1/payments/payment-methods',
      createOrder: '/v1/payments/create-order',
      processPaymentWithSavedMethod: '/v1/payments/process-payment-with-saved-method',
      createBankTransferOrder: '/v1/payments/create-bank-transfer-order',
      bankTransferStatus: '/v1/payments/bank-transfer-status',
      getInvoices: '/v1/payments/invoices',
      getSubscription: '/v1/payments/subscription',
      savePaymentMethod: '/v1/payments/save-payment-method',
    },
    usage: { getUsage: '/v1/settings/usage', export: '/v1/settings/usage/export' },
  },
}));

import { billingPath, loadBillingAddress, saveBillingAddress } from '../billingContext';

describe('billing context isolation', () => {
  beforeEach(() => vi.restoreAllMocks());

  // contract-test: supporting surface=gui.web assertions=billing.purchase.provider-routing,billing.documents.visible-downloadable
  it('uses only Team routes when a Team is selected and rejects an empty Team ID', () => {
    const team = { kind: 'team' as const, teamId: 'team/1' };
    for (const operation of ['address', 'balance', 'methods', 'cardOrder', 'savedCardOrder', 'bankOrder', 'bankStatus', 'invoices', 'autoTopup', 'monthly', 'usage', 'usageExport', 'saveMethod'] as const) {
      expect(billingPath(team, operation)).toContain('/v1/teams/team%2F1/billing');
      expect(billingPath(team, operation)).not.toContain('/v1/payments/');
    }
    expect(() => billingPath({ kind: 'team', teamId: '' }, 'cardOrder')).toThrow();
  });

  // contract-test: supporting surface=gui.web assertions=billing.documents.visible-downloadable
  it('loads and clears each context address through its own endpoint', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({ buyer_address: null }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }));
    await loadBillingAddress({ kind: 'team', teamId: 't1' });
    await saveBillingAddress({ kind: 'personal' }, null);
    expect(fetchMock.mock.calls[0][0]).toBe('https://api.test/v1/teams/t1/billing/buyer-address');
    expect(fetchMock.mock.calls[1][0]).toBe('https://api.test/v1/payments/buyer-address');
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'PUT', body: '{"buyer_address":null}' });
  });
});
