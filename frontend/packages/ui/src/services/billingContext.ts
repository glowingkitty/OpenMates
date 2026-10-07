import { apiEndpoints, getApiEndpoint } from '../config/api';

export type BillingContext = { kind: 'personal' } | { kind: 'team'; teamId: string };

export interface BillingAddress {
  name: string;
  street_line_1: string;
  street_line_2?: string | null;
  postal_code: string;
  city: string;
  region?: string | null;
  country: string;
  vat_id?: string | null;
}

export const personalBillingContext: BillingContext = { kind: 'personal' };

const TEAM_BILLING_SETTINGS_SUFFIXES = new Set([
  '', 'address', 'buy-credits', 'buy-credits/payment', 'buy-credits/confirmation',
  'invoices', 'auto-topup', 'auto-topup/low-balance', 'auto-topup/monthly',
]);

/** Resolve generic billing links before Settings selects a context-specific page. */
export function resolveBillingSettingsPath(settingsPath: string, activeTeamId: string | null): string {
  if (!activeTeamId || !/^billing(?:\/|$)/.test(settingsPath)) return settingsPath;
  const suffix = settingsPath === 'billing' ? '' : settingsPath.slice('billing/'.length);
  const teamBillingRoot = `teams/${activeTeamId}/billing`;
  return TEAM_BILLING_SETTINGS_SUFFIXES.has(suffix)
    ? `${teamBillingRoot}${suffix ? `/${suffix}` : ''}`
    : teamBillingRoot;
}

export function billingPath(context: BillingContext, operation: 'address' | 'balance' | 'methods' | 'cardOrder' | 'savedCardOrder' | 'bankOrder' | 'bankStatus' | 'invoices' | 'autoTopup' | 'monthly' | 'usage' | 'usageExport' | 'saveMethod'): string {
  if (context.kind === 'personal') {
    if (operation === 'balance') throw new Error('Personal balance is read from the user profile');
    const paths = {
      address: '/v1/payments/buyer-address',
      balance: '',
      methods: apiEndpoints.payments.listPaymentMethods,
      cardOrder: apiEndpoints.payments.createOrder,
      savedCardOrder: apiEndpoints.payments.processPaymentWithSavedMethod,
      bankOrder: apiEndpoints.payments.createBankTransferOrder,
      bankStatus: apiEndpoints.payments.bankTransferStatus,
      invoices: apiEndpoints.payments.getInvoices,
      autoTopup: apiEndpoints.payments.getSubscription,
      monthly: apiEndpoints.payments.getSubscription,
      usage: apiEndpoints.usage.getUsage,
      usageExport: apiEndpoints.usage.export,
      saveMethod: apiEndpoints.payments.savePaymentMethod,
    };
    return getApiEndpoint(paths[operation]);
  }
  if (!context.teamId.trim()) throw new Error('A Team billing request requires a Team ID');
  const base = `/v1/teams/${encodeURIComponent(context.teamId)}/billing`;
  const suffix = {
    address: '/buyer-address', balance: '', methods: '/payment-methods',
    cardOrder: '/card-orders', savedCardOrder: '/saved-card-orders',
    bankOrder: '/bank-transfer-orders', bankStatus: '/bank-transfer-orders',
    invoices: '/invoices', autoTopup: '/auto-topup', monthly: '/monthly-auto-topup', usage: '/usage',
    usageExport: '/usage/export', saveMethod: '/payment-methods',
  };
  return getApiEndpoint(`${base}${suffix[operation]}`);
}

export async function loadBillingAddress(context: BillingContext): Promise<BillingAddress | null> {
  const response = await fetch(billingPath(context, 'address'), { credentials: 'include' });
  if (!response.ok) throw new Error(`Could not load billing address (${response.status})`);
  const data = await response.json();
  return data.buyer_address ?? null;
}

export async function saveBillingAddress(context: BillingContext, address: BillingAddress | null): Promise<BillingAddress | null> {
  const response = await fetch(billingPath(context, 'address'), {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
    body: JSON.stringify({ buyer_address: address }),
  });
  if (!response.ok) throw new Error(`Could not save billing address (${response.status})`);
  const data = await response.json();
  return data.buyer_address ?? null;
}
