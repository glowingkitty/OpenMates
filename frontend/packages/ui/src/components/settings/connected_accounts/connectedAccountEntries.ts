// Pure helpers for the central Connected accounts page: turns decrypted summaries plus the
// server metadata (created_at, connector_status) and the client-encrypted last use into list entries.
import { getProviderIconUrl } from '../../../data/providerIcons';
import {
    readConnectedAccountAppActions,
    readConnectedAccountLastUsed,
    type ConnectedAccountSummary,
    type EncryptedConnectedAccountRow
} from '../../../services/connectedAccountStorageService';
import { isLegacyGoogleLabel } from './googleAccountLabel';

export interface ConnectedAccountEntry {
    id: string;
    summary: ConnectedAccountSummary;
    row: EncryptedConnectedAccountRow;
    /** Account email, or null for legacy rows that never stored one. */
    email: string | null;
    /** Granted actions per app id, from the multi-app envelope (or the single app of old rows). */
    apps: Record<string, string[]>;
    lastUsedAt: Date | null;
    createdAt: Date | null;
    reconnectRequired: boolean;
}

export function parseServerTimestamp(value: number | string | null | undefined): Date | null {
    if (value === null || value === undefined || value === '') return null;
    const parsed =
        typeof value === 'number' ? new Date(value < 1e12 ? value * 1000 : value) : new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function emailForSummary(summary: ConnectedAccountSummary): string | null {
    if (summary.provider_id === 'google_calendar' && isLegacyGoogleLabel(summary.label)) return null;
    return summary.label || null;
}

export async function buildConnectedAccountEntries(
    rows: EncryptedConnectedAccountRow[],
    summaries: ConnectedAccountSummary[]
): Promise<ConnectedAccountEntry[]> {
    const entries: ConnectedAccountEntry[] = [];
    for (const summary of summaries) {
        const row = rows.find((candidate) => candidate.id === summary.id);
        if (!row || row.connector_status === 'revoked') continue;
        entries.push({
            id: summary.id,
            summary,
            row,
            email: emailForSummary(summary),
            // Local connector rows carry only non-secret metadata; their encrypted fields
            // may not decrypt here, so their apps come from the summary built from that metadata.
            apps:
                summary.execution_mode === 'local_connector'
                    ? { [summary.app_id]: summary.capabilities }
                    : await readConnectedAccountAppActions(row),
            lastUsedAt: parseServerTimestamp(await readConnectedAccountLastUsed(row)),
            createdAt: parseServerTimestamp(row.created_at),
            reconnectRequired: row.connector_status === 'reconnect_required'
        });
    }
    return entries;
}

export function formatRelativeTime(date: Date, locale: string, now: Date = new Date()): string {
    const seconds = Math.round((date.getTime() - now.getTime()) / 1000);
    const formatter = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
    const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
        ['day', 86400],
        ['hour', 3600],
        ['minute', 60]
    ];
    for (const [unit, size] of units) {
        if (Math.abs(seconds) >= size) return formatter.format(Math.round(seconds / size), unit);
    }
    return formatter.format(0, 'day');
}

export function formatShortDate(date: Date, locale: string): string {
    return date.toLocaleDateString(locale, { day: 'numeric', month: 'short' });
}

/** Permission toggles per app: toggle id, the allowed_actions it grants, and its label key. */
export const APP_PERMISSION_TOGGLES: Record<string, Array<{ id: string; actions: string[]; labelKey: string }>> = {
    calendar: [
        { id: 'read', actions: ['read'], labelKey: 'settings.app_store.connected_accounts.capability_read' },
        { id: 'write', actions: ['write', 'update'], labelKey: 'settings.app_store.connected_accounts.capability_write' },
        { id: 'delete', actions: ['delete'], labelKey: 'settings.app_store.connected_accounts.capability_delete' }
    ],
    mail: [
        { id: 'read', actions: ['read'], labelKey: 'settings.app_store.connected_accounts.central.cap_read_mail' },
        { id: 'draft', actions: ['draft'], labelKey: 'settings.app_store.connected_accounts.central.cap_draft' }
    ],
    design: [
        { id: 'read', actions: ['read'], labelKey: 'settings.app_store.connected_accounts.capability_read' }
    ]
};

type Translate = (key: string) => string;

export function isLocalConnectorEntry(entry: ConnectedAccountEntry): boolean {
    return entry.summary.execution_mode === 'local_connector';
}

export function localProviderLabel(providerId: string, t: Translate): string {
    if (providerId === 'protonmail_bridge') return t('settings.privacy.connected_accounts.provider_proton_mail_bridge');
    return providerId;
}

export function localConnectorStatusLabel(entry: ConnectedAccountEntry, t: Translate): string {
    const status = entry.summary.connector_status;
    if (status === 'online') return t('settings.privacy.connected_accounts.status_online_cli');
    if (status === 'setup_required') return t('settings.privacy.connected_accounts.status_setup_required');
    return t('settings.privacy.connected_accounts.status_offline');
}

export function localCapabilityLabels(capabilities: string[], t: Translate): string {
    if (capabilities.length === 0) return t('settings.privacy.connected_accounts.none');
    return capabilities.map((capability) => {
        if (capability === 'read') return t('settings.app_store.connected_accounts.capability_read');
        if (capability === 'write') return t('settings.app_store.connected_accounts.capability_write');
        if (capability === 'delete') return t('settings.app_store.connected_accounts.capability_delete');
        return capability;
    }).join(', ');
}

/** App ids that have their own settings icon class; any other app uses the generic app icon. */
const APP_ICON_CLASSES = new Set(['calendar', 'mail']);

/** Settings icon class for an app id (the design app has no icon class of its own). */
export function appIconClass(appId: string): string {
  return APP_ICON_CLASSES.has(appId) ? appId : 'app';
}

/** Bundled provider logos by stored provider id (Google rows are stored as google_calendar). */
const PROVIDER_LOGOS: Record<string, string> = { google: 'icons/google.svg', google_calendar: 'icons/google.svg' };

/** Logo URL for a provider, or '' when no logo is bundled (callers then use a generic icon). */
export function providerLogoUrl(providerId: string): string {
  const path = PROVIDER_LOGOS[providerId];
  return path ? getProviderIconUrl(path) : '';
}
