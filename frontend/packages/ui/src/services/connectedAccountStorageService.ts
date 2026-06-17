// frontend/packages/ui/src/services/connectedAccountStorageService.ts
//
// Browser client for encrypted connected-account row storage.
// The server receives only encrypted blobs and stable hashes; provider identity
// labels and refresh tokens must already be encrypted by the caller.
//
// Spec: docs/specs/calendar-permission-management/spec.yml

import { getApiEndpoint } from '../config/api';
import { computeSHA256 } from '../message_parsing/utils';
import { decryptWithMasterKey } from './cryptoService';
import type { ConnectedAccountSendContext } from './connectedAccountTokenBrokerService';
import { assertNoConnectedAccountSecretLeak } from './connectedAccountTokenBrokerService';

const CONNECTED_ACCOUNTS_ENDPOINT = '/v1/connected-accounts';

const STORAGE_FORBIDDEN_FIELDS = [
	'provider',
	'provider_type',
	'provider_name',
	'provider_email',
	'email',
	'account_email',
	'account_label',
	'display_name',
	'oauth_scopes',
	'scopes',
	'refresh_token',
	'access_token',
	'provider_account_id'
];

export interface EncryptedConnectedAccountRow {
	id: string;
	hashed_user_id: string;
	encrypted_provider_type: string;
	provider_type_hash: string;
	encrypted_account_label: string;
	encrypted_refresh_token_bundle: string;
	encrypted_capabilities: string;
	encrypted_app_permissions: string;
	provider_account_id_hash?: string | null;
	encrypted_provider_account_display?: string | null;
	encrypted_account_directory_hint?: string | null;
	server_access_enabled?: boolean;
	encrypted_server_access_ref?: string | null;
	updated_at?: number;
}

export type EncryptedConnectedAccountCreateInput = Omit<
	EncryptedConnectedAccountRow,
	'hashed_user_id' | 'updated_at'
>;

export type EncryptedConnectedAccountPatchInput = Partial<
	Omit<EncryptedConnectedAccountRow, 'id' | 'hashed_user_id' | 'updated_at'>
>;

export interface ConnectedAccountWriteResponse {
	id: string;
	sync_version: number;
}

export interface ConnectedAccountListResponse {
	rows: EncryptedConnectedAccountRow[];
}

interface ConnectedAccountDirectoryHint {
	account_ref?: string;
	label?: string;
	capabilities?: string[];
	runtime_modes?: Record<string, string>;
}

interface ConnectedAccountPermissionsEnvelope {
	app_id?: string;
	allowed_actions?: string[];
	action_scope?: Record<string, unknown>;
}

export interface ConnectedAccountSummary {
	id: string;
	provider_id: string;
	app_id: string;
	account_ref: string;
	label: string;
	capabilities: string[];
	runtime_modes: Record<string, string>;
	updated_at?: number;
}

export async function computeConnectedAccountUserHash(userId: string): Promise<string> {
	if (!userId) {
		throw new Error('Connected-account storage requires a user id');
	}
	return computeSHA256(userId);
}

export async function listConnectedAccounts(): Promise<EncryptedConnectedAccountRow[]> {
	const response = await fetch(getApiEndpoint(CONNECTED_ACCOUNTS_ENDPOINT), {
		credentials: 'include'
	});
	if (!response.ok) {
		throw new Error(`Failed to list connected accounts (HTTP ${response.status})`);
	}
	const payload = (await response.json()) as ConnectedAccountListResponse;
	if (!Array.isArray(payload.rows)) {
		throw new Error('Connected accounts response did not include rows');
	}
	assertNoPlaintextConnectedAccountFields(payload.rows);
	return payload.rows;
}

export async function createConnectedAccount(params: {
	userId: string;
	row: EncryptedConnectedAccountCreateInput;
}): Promise<ConnectedAccountWriteResponse> {
	assertNoPlaintextConnectedAccountFields(params.row);
	const hashedUserId = await computeConnectedAccountUserHash(params.userId);
	const response = await fetch(getApiEndpoint(CONNECTED_ACCOUNTS_ENDPOINT), {
		method: 'POST',
		credentials: 'include',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ ...params.row, hashed_user_id: hashedUserId })
	});
	return parseWriteResponse(response, 'create');
}

export async function updateConnectedAccount(params: {
	accountId: string;
	patch: EncryptedConnectedAccountPatchInput;
}): Promise<ConnectedAccountWriteResponse> {
	assertNoPlaintextConnectedAccountFields(params.patch);
	const response = await fetch(
		getApiEndpoint(`${CONNECTED_ACCOUNTS_ENDPOINT}/${encodeURIComponent(params.accountId)}`),
		{
			method: 'PATCH',
			credentials: 'include',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(params.patch)
		}
	);
	return parseWriteResponse(response, 'update');
}

export async function buildConnectedAccountSendContext(params: {
	rows: EncryptedConnectedAccountRow[];
	appId: string;
	accountIds?: string[];
	defaultAllowedActions?: string[];
	allowedActionsOverride?: string[];
	actionScopesOverride?: Record<string, unknown>[];
	includeActionScope?: boolean;
}): Promise<ConnectedAccountSendContext | undefined> {
	const selectedIds = new Set(params.accountIds ?? []);
	const rows = params.accountIds?.length
		? params.rows.filter((row) => selectedIds.has(row.id))
		: params.rows;
	if (rows.length === 0) return undefined;

	const directory: NonNullable<ConnectedAccountSendContext['directory']> = [];
	const tokenRefInputs: NonNullable<ConnectedAccountSendContext['tokenRefInputs']> = [];

	for (const row of rows) {
		assertNoPlaintextConnectedAccountFields(row);
		const [label, capabilities, permissions, directoryHint] = await Promise.all([
			decryptConnectedAccountValue<string>(row.encrypted_account_label, 'encrypted_account_label'),
			decryptConnectedAccountValue<string[] | { capabilities?: string[] }>(
				row.encrypted_capabilities,
				'encrypted_capabilities'
			),
			decryptConnectedAccountValue<ConnectedAccountPermissionsEnvelope>(
				row.encrypted_app_permissions,
				'encrypted_app_permissions'
			),
			row.encrypted_account_directory_hint
				? decryptConnectedAccountValue<ConnectedAccountDirectoryHint>(
						row.encrypted_account_directory_hint,
						'encrypted_account_directory_hint'
					)
				: Promise.resolve(undefined)
		]);

		const capabilityList = Array.isArray(capabilities)
			? capabilities
			: capabilities.capabilities ?? [];
		const appId = normalizeConnectedAccountAppId(permissions.app_id ?? params.appId);
		const allowedActions = params.allowedActionsOverride
			?? preauthorizedActions(
				permissions.allowed_actions ?? params.defaultAllowedActions ?? [],
				directoryHint?.runtime_modes
			);
		const actionScopes = params.actionScopesOverride?.length
			? params.actionScopesOverride
			: [permissions.action_scope].filter((scope): scope is Record<string, unknown> => Boolean(scope));
		directory.push({
			connected_account_id: row.id,
			app_id: appId,
			account_ref: directoryHint?.account_ref ?? row.id,
			label: directoryHint?.label ?? label,
			capabilities: directoryHint?.capabilities ?? capabilityList,
			runtime_modes: directoryHint?.runtime_modes
		});
		if (allowedActions.length > 0) {
			const refreshTokenEnvelope = await decryptConnectedAccountValue<Record<string, unknown>>(
				row.encrypted_refresh_token_bundle,
				'encrypted_refresh_token_bundle'
			);
			const scopes = params.includeActionScope === false ? [undefined] : actionScopes.length ? actionScopes : [undefined];
			for (const actionScope of scopes) {
				tokenRefInputs.push({
					connected_account_id: row.id,
					app_id: appId,
					allowed_actions: allowedActions,
					refresh_token_envelope: refreshTokenEnvelope,
					...(actionScope ? { action_scope: actionScope } : {})
				});
			}
		}
	}

	assertNoConnectedAccountSecretLeak(directory);
	return { directory, tokenRefInputs };
}

export async function summarizeConnectedAccountRows(
	rows: EncryptedConnectedAccountRow[]
): Promise<ConnectedAccountSummary[]> {
	const summaries: ConnectedAccountSummary[] = [];
	for (const row of rows) {
		assertNoPlaintextConnectedAccountFields(row);
		const [providerId, label, capabilities, permissions, directoryHint] = await Promise.all([
			decryptConnectedAccountValue<string>(row.encrypted_provider_type, 'encrypted_provider_type'),
			decryptConnectedAccountValue<string>(row.encrypted_account_label, 'encrypted_account_label'),
			decryptConnectedAccountValue<string[] | { capabilities?: string[] }>(
				row.encrypted_capabilities,
				'encrypted_capabilities'
			),
			decryptConnectedAccountValue<ConnectedAccountPermissionsEnvelope>(
				row.encrypted_app_permissions,
				'encrypted_app_permissions'
			),
			row.encrypted_account_directory_hint
				? decryptConnectedAccountValue<ConnectedAccountDirectoryHint>(
						row.encrypted_account_directory_hint,
						'encrypted_account_directory_hint'
					)
				: Promise.resolve(undefined)
		]);
		const capabilityList = Array.isArray(capabilities)
			? capabilities
			: capabilities.capabilities ?? [];
		summaries.push({
			id: row.id,
			provider_id: providerId,
			app_id: normalizeConnectedAccountAppId(permissions.app_id ?? appIdForProvider(providerId)),
			account_ref: directoryHint?.account_ref ?? row.id,
			label: directoryHint?.label ?? label,
			capabilities: directoryHint?.capabilities ?? capabilityList,
			runtime_modes: directoryHint?.runtime_modes ?? {},
			updated_at: row.updated_at
		});
	}
	assertNoConnectedAccountSecretLeak(summaries);
	return summaries;
}

function appIdForProvider(providerId: string): string {
	if (providerId === 'google_calendar') return 'calendar';
	return providerId;
}

function normalizeConnectedAccountAppId(appId: string): string {
	if (appId === 'google_calendar') return 'calendar';
	return appId;
}

function preauthorizedActions(
	actions: string[],
	runtimeModes?: Record<string, string>
): string[] {
	if (!runtimeModes) return [];
	return actions.filter((action) => {
		const mode = runtimeModes[action];
		return mode === 'allow_automatically' || mode === 'auto_decide';
	});
}

export function assertNoPlaintextConnectedAccountFields(value: unknown): void {
	const serialized = JSON.stringify(value ?? {});
	for (const key of STORAGE_FORBIDDEN_FIELDS) {
		if (serialized.includes(`"${key}"`)) {
			throw new Error(`Connected account storage payload contains forbidden field: ${key}`);
		}
	}
}

async function parseWriteResponse(
	response: Response,
	action: 'create' | 'update'
): Promise<ConnectedAccountWriteResponse> {
	if (!response.ok) {
		throw new Error(`Failed to ${action} connected account (HTTP ${response.status})`);
	}
	const payload = (await response.json()) as ConnectedAccountWriteResponse;
	if (!payload.id || typeof payload.sync_version !== 'number') {
		throw new Error(`Connected account ${action} response was incomplete`);
	}
	return payload;
}

async function decryptConnectedAccountValue<T>(encryptedValue: string, fieldName: string): Promise<T> {
	const decrypted = await decryptWithMasterKey(encryptedValue);
	if (!decrypted) {
		throw new Error(`Failed to decrypt connected account field: ${fieldName}`);
	}
	try {
		return JSON.parse(decrypted) as T;
	} catch {
		return decrypted as T;
	}
}
