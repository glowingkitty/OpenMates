// frontend/packages/ui/src/services/connectedAccountStorageService.ts
//
// Browser client for encrypted connected-account row storage.
// The server receives only encrypted blobs and stable hashes; provider identity
// labels and refresh tokens must already be encrypted by the caller.
//
// Spec: docs/specs/calendar-permission-management/spec.yml

import { getApiEndpoint } from '../config/api';
import { computeSHA256 } from '../message_parsing/utils';

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
