// Preview-only seam: serves synthetic encrypted connected-account rows from a stubbed
// GET /v1/connected-accounts so the real listConnectedAccounts/summarize pipeline runs
// unchanged. A throwaway in-memory master key encrypts the rows; nothing is persisted.
import { saveKeyToSession } from '../../services/cryptoService';
import { encryptWithMasterKey } from '../../services/encryption/MetadataEncryptor';
import type { EncryptedConnectedAccountRow } from '../../services/connectedAccountStorageService';
import { computeSHA256 } from '../../message_parsing/utils';

export interface PreviewConnectedAccount {
  id: string;
  providerId: 'google_calendar' | 'figma';
  appId: 'calendar' | 'design' | 'mail';
  label: string;
  capabilities: string[];
  /** Multi-app envelope (app id to allowed actions); omitted rows use the old single-app form. */
  apps?: Record<string, string[]>;
  lastUsedAt?: number;
  createdAt?: number;
  connectorStatus?: string;
}

async function enc(value: unknown): Promise<string> {
  const out = await encryptWithMasterKey(typeof value === 'string' ? value : JSON.stringify(value));
  if (!out) throw new Error('preview fixture encryption failed');
  return out;
}

async function buildRow(account: PreviewConnectedAccount): Promise<EncryptedConnectedAccountRow> {
  return {
    id: account.id,
    hashed_user_id: 'preview-hashed-user',
    encrypted_provider_type: await enc(account.providerId),
    provider_type_hash: await computeSHA256(account.providerId),
    encrypted_account_label: await enc(account.label),
    encrypted_refresh_token_bundle: await enc({ preview: true }),
    encrypted_capabilities: await enc(account.capabilities),
    encrypted_app_permissions: await enc(
      account.apps
        ? { apps: Object.fromEntries(Object.entries(account.apps).map(([app, actions]) => [app, { allowed_actions: actions }])) }
        : { app_id: account.appId, allowed_actions: account.capabilities }
    ),
    execution_mode: 'oauth',
    ...(account.connectorStatus ? { connector_status: account.connectorStatus } : {}),
    connector_status: account.connectorStatus ?? null,
    created_at: account.createdAt ?? 1_700_000_000,
    encrypted_last_used_at: account.lastUsedAt ? await enc(account.lastUsedAt) : null,
    updated_at: 1_700_000_000
  };
}

export async function installConnectedAccountFixture(accounts: PreviewConnectedAccount[]): Promise<void> {
  const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt']);
  await saveKeyToSession(key, false);
  const rows = await Promise.all(accounts.map(buildRow));
  const originalFetch = window.fetch;
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const method = (init?.method ?? 'GET').toUpperCase();
    if (method === 'GET' && /\/v1\/connected-accounts(\?|$)/.test(url)) {
      return Promise.resolve(new Response(JSON.stringify({ rows }), { status: 200, headers: { 'content-type': 'application/json' } }));
    }
    const patchMatch = method === 'PATCH' ? url.match(/\/v1\/connected-accounts\/([^/?]+)/) : null;
    if (patchMatch) {
      const row = rows.find((candidate) => candidate.id === decodeURIComponent(patchMatch[1]));
      if (row) Object.assign(row, JSON.parse(String(init?.body ?? '{}')));
      return Promise.resolve(new Response(JSON.stringify({ id: patchMatch[1], sync_version: 2 }), { status: 200, headers: { 'content-type': 'application/json' } }));
    }
    return originalFetch(input, init);
  };
  window.addEventListener('pagehide', () => { window.fetch = originalFetch; }, { once: true });
}

export const previewGoogleCalendar = (label: string): PreviewConnectedAccount => ({
  id: 'preview-google-calendar-account', providerId: 'google_calendar', appId: 'calendar', label,
  capabilities: ['read', 'write']
});
export const previewFigma: PreviewConnectedAccount = {
  id: 'preview-figma-account', providerId: 'figma', appId: 'design', label: 'Dana Designer (dana@example.org)',
  capabilities: ['read']
};
export const previewGmail = (label: string): PreviewConnectedAccount => ({
  id: 'preview-gmail-account', providerId: 'google_calendar', appId: 'mail', label,
  capabilities: ['read', 'draft']
});

export const previewGoogleBoth = (label: string, lastUsedAt: number): PreviewConnectedAccount => ({
  id: 'preview-google-account', providerId: 'google_calendar', appId: 'calendar', label,
  capabilities: ['read', 'write'],
  apps: { calendar: ['read', 'write', 'update'], mail: ['read', 'draft'] },
  lastUsedAt, createdAt: 1_750_000_000
});
export const previewLegacyExpiredGoogle: PreviewConnectedAccount = {
  id: 'preview-google-legacy-account', providerId: 'google_calendar', appId: 'calendar', label: 'Google Calendar',
  capabilities: ['read'], connectorStatus: 'reconnect_required',
  createdAt: Date.UTC(2026, 5, 16, 12) / 1000
};
