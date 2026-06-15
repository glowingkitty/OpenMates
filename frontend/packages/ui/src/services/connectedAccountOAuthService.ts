// frontend/packages/ui/src/services/connectedAccountOAuthService.ts
//
// Browser-side OAuth handoff finalization for connected accounts.
// The backend may briefly handle provider refresh tokens during confidential
// OAuth exchange, but this service immediately encrypts the claimed bundle and
// persists only encrypted/hash fields through connected-account storage.
//
// Spec: docs/specs/calendar-permission-management/spec.yml

import { getApiEndpoint } from '../config/api';
import { computeSHA256 } from '../message_parsing/utils';
import { encryptWithMasterKey } from './cryptoService';
import {
	assertNoPlaintextConnectedAccountFields,
	createConnectedAccount,
	type ConnectedAccountWriteResponse,
	type EncryptedConnectedAccountCreateInput
} from './connectedAccountStorageService';

export interface OAuthHandoffClaimResponse {
	provider_id: string;
	refresh_token_bundle: Record<string, unknown>;
	account_hint: Record<string, unknown>;
	expires_at: number;
}

export interface FinalizeOAuthHandoffParams {
	userId: string;
	handoffId: string;
	connectedAccountId?: string;
}

export async function startGoogleCalendarOAuth(params: {
	capabilities: string[];
	returnPath?: string;
}): Promise<{ authorization_url: string; state_expires_at: number; scopes: string[] }> {
	const response = await fetch(getApiEndpoint('/v1/provider-oauth/google/calendar/start'), {
		method: 'POST',
		credentials: 'include',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			capabilities: params.capabilities,
			return_path: params.returnPath ?? '/#settings/app_store/calendar'
		})
	});
	if (!response.ok) {
		throw new Error(`Failed to start Google Calendar OAuth (HTTP ${response.status})`);
	}
	return response.json() as Promise<{ authorization_url: string; state_expires_at: number; scopes: string[] }>;
}

export async function claimOAuthHandoff(handoffId: string): Promise<OAuthHandoffClaimResponse> {
	const response = await fetch(
		getApiEndpoint(`/v1/connected-account-oauth/handoffs/${encodeURIComponent(handoffId)}/claim`),
		{
			method: 'POST',
			credentials: 'include'
		}
	);
	if (!response.ok) {
		throw new Error(`Failed to claim OAuth handoff (HTTP ${response.status})`);
	}
	const payload = (await response.json()) as OAuthHandoffClaimResponse;
	if (!payload.provider_id || !payload.refresh_token_bundle?.refresh_token) {
		throw new Error('OAuth handoff response did not include provider and refresh token bundle');
	}
	return payload;
}

export async function finalizeOAuthHandoffAsConnectedAccount(
	params: FinalizeOAuthHandoffParams
): Promise<ConnectedAccountWriteResponse> {
	const handoff = await claimOAuthHandoff(params.handoffId);
	const row = await buildEncryptedConnectedAccountRow({
		connectedAccountId: params.connectedAccountId ?? crypto.randomUUID(),
		handoff
	});
	return createConnectedAccount({ userId: params.userId, row });
}

export async function buildEncryptedConnectedAccountRow(params: {
	connectedAccountId: string;
	handoff: OAuthHandoffClaimResponse;
}): Promise<EncryptedConnectedAccountCreateInput> {
	const providerId = params.handoff.provider_id;
	const capabilities = normalizeCapabilities(params.handoff.account_hint.capabilities);
	const label = typeof params.handoff.account_hint.label === 'string'
		? params.handoff.account_hint.label
		: defaultProviderLabel(providerId);
	const accountRef = typeof params.handoff.account_hint.account_ref === 'string'
		? params.handoff.account_hint.account_ref
		: params.connectedAccountId;
	const providerAccountId = typeof params.handoff.account_hint.provider_account_id === 'string'
		? params.handoff.account_hint.provider_account_id
		: undefined;

	const row: EncryptedConnectedAccountCreateInput = {
		id: params.connectedAccountId,
		encrypted_provider_type: await encryptRequired(providerId, 'provider_id'),
		provider_type_hash: await computeSHA256(providerId),
		encrypted_account_label: await encryptRequired(label, 'account_label'),
		encrypted_refresh_token_bundle: await encryptRequired(
			JSON.stringify(params.handoff.refresh_token_bundle),
			'refresh_token_bundle'
		),
		encrypted_capabilities: await encryptRequired(JSON.stringify(capabilities), 'capabilities'),
		encrypted_app_permissions: await encryptRequired(
			JSON.stringify({
				app_id: appIdForProvider(providerId),
				allowed_actions: actionsForCapabilities(capabilities),
				scopes: params.handoff.account_hint.scopes ?? params.handoff.refresh_token_bundle.scopes ?? []
			}),
			'app_permissions'
		),
		encrypted_account_directory_hint: await encryptRequired(
			JSON.stringify({
				account_ref: accountRef,
				label,
				capabilities,
				runtime_modes: runtimeModesForCapabilities(capabilities)
			}),
			'account_directory_hint'
		)
	};
	if (providerAccountId) {
		row.provider_account_id_hash = await computeSHA256(providerAccountId);
		row.encrypted_provider_account_display = await encryptRequired(
			providerAccountId,
			'provider_account_display'
		);
	}
	assertNoPlaintextConnectedAccountFields(row);
	return row;
}

async function encryptRequired(value: string, fieldName: string): Promise<string> {
	const encrypted = await encryptWithMasterKey(value);
	if (!encrypted) {
		throw new Error(`Failed to encrypt connected account OAuth field: ${fieldName}`);
	}
	return encrypted;
}

function normalizeCapabilities(value: unknown): string[] {
	if (!Array.isArray(value)) return ['read'];
	const capabilities = value.filter((item): item is string => typeof item === 'string');
	return capabilities.length ? capabilities : ['read'];
}

function actionsForCapabilities(capabilities: string[]): string[] {
	const actions = new Set<string>();
	for (const capability of capabilities) {
		if (capability === 'read') actions.add('read');
		if (capability === 'write') {
			actions.add('write');
			actions.add('update');
		}
		if (capability === 'delete') actions.add('delete');
	}
	return Array.from(actions);
}

function runtimeModesForCapabilities(capabilities: string[]): Record<string, string> {
	return Object.fromEntries(
		actionsForCapabilities(capabilities).map((action) => [
			action,
			action === 'read' ? 'allow_automatically' : 'always_ask'
		])
	);
}

function appIdForProvider(providerId: string): string {
	if (providerId === 'google_calendar') return 'calendar';
	return providerId;
}

function defaultProviderLabel(providerId: string): string {
	if (providerId === 'google_calendar') return 'Google Calendar';
	return 'Connected account';
}
