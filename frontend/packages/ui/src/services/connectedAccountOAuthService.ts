// frontend/packages/ui/src/services/connectedAccountOAuthService.ts
//
// Browser-side OAuth handoff finalization for connected accounts.
// The backend may briefly handle provider refresh tokens during confidential
// OAuth exchange, but this service immediately encrypts the claimed bundle and
// persists only encrypted/hash fields through connected-account storage.
//
// Spec: docs/specs/calendar-permission-management/spec.yml

import { getApiEndpoint } from '../config/api';
import { get } from 'svelte/store';
import { userProfile } from '../stores/userProfile';
import { computeSHA256 } from '../message_parsing/utils';
import { decryptWithMasterKey, encryptWithMasterKey } from './cryptoService';
import {
	assertNoPlaintextConnectedAccountFields,
	createConnectedAccount,
	listConnectedAccounts,
	updateConnectedAccount,
	type ConnectedAccountWriteResponse,
	type EncryptedConnectedAccountCreateInput,
	type EncryptedConnectedAccountRow
} from './connectedAccountStorageService';

// Flag switch: default builds run the TypeScript logic below unchanged; with
// VITE_OPENMATES_RUST_CORE=1 the shared Rust Worker decides the row plan (no
// TypeScript fallback). The const-false branch is dead-code eliminated from
// flag-off builds, so no Rust adapter ships there.
const RUST_CONNECTED_ACCOUNTS_BUILD: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';
type RustConnectedAccountWrites = typeof import('./rustCore/connectedAccounts/rustConnectedAccountWrites');
function rustConnectedAccountWrites(): Promise<RustConnectedAccountWrites> | null {
	return RUST_CONNECTED_ACCOUNTS_BUILD ? import('./rustCore/connectedAccounts/rustConnectedAccountWrites') : null;
}

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
	updateExisting?: boolean;
	capabilitiesOverride?: string[];
	/** The existing row an `updateExisting` finalize adds an app to; its app permissions are merged, not replaced. */
	existingRow?: EncryptedConnectedAccountRow;
}

export async function startGoogleCalendarOAuth(params: {
	capabilities: string[];
	returnPath?: string;
	appId?: 'calendar' | 'mail';
}): Promise<{ authorization_url: string; state_expires_at: number; scopes: string[] }> {
	const response = await fetch(getApiEndpoint('/v1/provider-oauth/google/calendar/start'), {
		method: 'POST',
		credentials: 'include',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			capabilities: params.capabilities,
			return_path: params.returnPath ?? `/#settings/apps/${params.appId ?? 'calendar'}`,
			app_id: params.appId ?? 'calendar'
		})
	});
	if (!response.ok) {
		throw new Error(`Failed to start Google Calendar OAuth (HTTP ${response.status})`);
	}
	return response.json() as Promise<{ authorization_url: string; state_expires_at: number; scopes: string[] }>;
}

export async function startFigmaOAuth(params: {
	capabilities: string[];
	returnPath?: string;
}): Promise<{ authorization_url: string; state_expires_at: number; scopes: string[] }> {
	const response = await fetch(getApiEndpoint('/v1/provider-oauth/figma/start'), {
		method: 'POST',
		credentials: 'include',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			capabilities: params.capabilities,
			return_path: params.returnPath ?? '/#settings/apps/design'
		})
	});
	if (!response.ok) {
		throw new Error(`Failed to start Figma OAuth (HTTP ${response.status})`);
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
		handoff,
		capabilitiesOverride: params.capabilitiesOverride
	});
	if (params.connectedAccountId && params.updateExisting) {
		const patch = params.existingRow ? await mergeIntoExistingRow(params.existingRow, row) : row;
		return updateConnectedAccount({
			accountId: params.connectedAccountId,
			patch
		});
	}
	return createConnectedAccount({ userId: params.userId, row });
}

export async function buildEncryptedConnectedAccountRow(params: {
	connectedAccountId: string;
	handoff: OAuthHandoffClaimResponse;
	capabilitiesOverride?: string[];
}): Promise<EncryptedConnectedAccountCreateInput> {
	const rust = rustConnectedAccountWrites();
	if (rust) return (await rust).rustBuildEncryptedConnectedAccountRow(params, encryptWithMasterKey, computeSHA256);
	const providerId = params.handoff.provider_id;
	const hint = params.handoff.account_hint;
	const appId = appIdForProvider(providerId, hint.app_id);
	let capabilities = normalizeCapabilities(params.capabilitiesOverride ?? hint.capabilities);
	if (appId === 'mail') {
		// Mail is read + draft only: write, delete and send are never granted.
		capabilities = capabilities.filter((item) => item === 'read' || item === 'draft');
		if (!capabilities.length) capabilities = ['read'];
	}
	const label = typeof hint.label === 'string' && hint.label
		? hint.label
		: typeof hint.account_email === 'string' && hint.account_email
			? hint.account_email
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
			JSON.stringify(
				permissionsPlaintext(
					providerId,
					appId,
					actionsForCapabilities(capabilities),
					params.handoff.account_hint.scopes ?? params.handoff.refresh_token_bundle.scopes ?? []
				)
			),
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

/** google_calendar rows use the multi-app envelope; other providers stay single-app. */
function permissionsPlaintext(
	providerId: string,
	appId: string,
	allowedActions: string[],
	scopes: unknown
): Record<string, unknown> {
	if (providerId === 'google_calendar') {
		return { apps: { [appId]: { allowed_actions: allowedActions, scopes } } };
	}
	return { app_id: appId, allowed_actions: allowedActions, scopes };
}

type PermissionApps = Record<string, unknown>;

/** The `apps` of a permissions plaintext; an old single-app object becomes one entry. */
function permissionApps(plaintext: string): PermissionApps {
	const value: unknown = JSON.parse(plaintext);
	if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('protocol');
	const object = value as Record<string, unknown>;
	if ('apps' in object) {
		if (typeof object.apps !== 'object' || object.apps === null || Array.isArray(object.apps)) {
			throw new Error('protocol');
		}
		return { ...(object.apps as PermissionApps) };
	}
	if (typeof object.app_id !== 'string') throw new Error('protocol');
	const entry: Record<string, unknown> = {};
	if ('allowed_actions' in object) entry.allowed_actions = object.allowed_actions;
	if ('scopes' in object) entry.scopes = object.scopes;
	return { [object.app_id]: entry };
}

/** Flag-off twin of `merge_app_permissions_json`: the newer app entry replaces the same app's older one. */
export function mergeAppPermissions(existingPlaintext: string, newPlaintext: string): string {
	return JSON.stringify({ apps: { ...permissionApps(existingPlaintext), ...permissionApps(newPlaintext) } });
}

function unionStrings(...lists: unknown[]): string[] {
	const merged: string[] = [];
	for (const list of lists) {
		if (!Array.isArray(list)) continue;
		for (const item of list) if (typeof item === 'string' && !merged.includes(item)) merged.push(item);
	}
	return merged;
}

/** Flag-off twin of `merge_account_update_json` (same output texts). */
function mergeAccountUpdate(input: {
	existingPermissions: string;
	newPermissions: string;
	existingHint?: string;
	newHint: string;
	existingCapabilities?: string;
	newCapabilities: string;
}): { permissions: string; hint: string; capabilities: string } {
	const oldHint = input.existingHint ? JSON.parse(input.existingHint) : {};
	const newHint = JSON.parse(input.newHint);
	const oldCaps = input.existingCapabilities ? JSON.parse(input.existingCapabilities) : [];
	const newCaps = JSON.parse(input.newCapabilities);
	const hint: Record<string, unknown> = {};
	for (const key of ['account_ref', 'label']) {
		const value = oldHint[key] ?? newHint[key];
		if (value !== undefined) hint[key] = value;
	}
	hint.capabilities = unionStrings(oldHint.capabilities, newHint.capabilities);
	// The existing mode wins, so a user's choice survives adding an app.
	hint.runtime_modes = { ...(newHint.runtime_modes ?? {}), ...(oldHint.runtime_modes ?? {}) };
	return {
		permissions: mergeAppPermissions(input.existingPermissions, input.newPermissions),
		hint: JSON.stringify(hint),
		capabilities: JSON.stringify(unionStrings(oldCaps, newCaps))
	};
}

async function decryptPlaintext(encrypted: string | null | undefined, field: string): Promise<string | undefined> {
	if (!encrypted) return undefined;
	const plaintext = await decryptWithMasterKey(encrypted);
	if (!plaintext) throw new Error(`Failed to decrypt connected account field: ${field}`);
	return plaintext;
}

/**
 * "Add an app to an existing account": decrypt the existing row's app
 * permissions, directory hint and capabilities, merge the new row's into them
 * and re-encrypt, so the row never loses its other apps.
 */
async function mergeIntoExistingRow(
	existing: EncryptedConnectedAccountRow,
	row: EncryptedConnectedAccountCreateInput
): Promise<EncryptedConnectedAccountCreateInput> {
	const [existingPermissions, existingHint, existingCapabilities, newPermissions, newHint, newCapabilities] =
		await Promise.all([
			decryptPlaintext(existing.encrypted_app_permissions, 'encrypted_app_permissions'),
			decryptPlaintext(existing.encrypted_account_directory_hint, 'encrypted_account_directory_hint'),
			decryptPlaintext(existing.encrypted_capabilities, 'encrypted_capabilities'),
			decryptPlaintext(row.encrypted_app_permissions, 'encrypted_app_permissions'),
			decryptPlaintext(row.encrypted_account_directory_hint, 'encrypted_account_directory_hint'),
			decryptPlaintext(row.encrypted_capabilities, 'encrypted_capabilities')
		]);
	if (!existingPermissions || !newPermissions || !newHint || !newCapabilities) {
		throw new Error('Failed to read connected account fields for merging');
	}
	const input = { existingPermissions, newPermissions, existingHint, newHint, existingCapabilities, newCapabilities };
	const rust = rustConnectedAccountWrites();
	const merged = rust ? await (await rust).rustMergeConnectedAccountUpdate(input) : mergeAccountUpdate(input);
	const mergedRow: EncryptedConnectedAccountCreateInput = {
		...row,
		encrypted_app_permissions: await encryptRequired(merged.permissions, 'app_permissions'),
		encrypted_account_directory_hint: await encryptRequired(merged.hint, 'account_directory_hint'),
		encrypted_capabilities: await encryptRequired(merged.capabilities, 'capabilities')
	};
	assertNoPlaintextConnectedAccountFields(mergedRow);
	return mergedRow;
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

function appIdForProvider(providerId: string, hintedAppId?: unknown): string {
	if (providerId === 'google_calendar') return hintedAppId === 'mail' ? 'mail' : 'calendar';
	if (providerId === 'figma') return 'design';
	return providerId;
}

function defaultProviderLabel(providerId: string): string {
	if (providerId === 'google_calendar') return 'Google Calendar';
	if (providerId === 'figma') return 'Figma';
	return 'Connected account';
}

// ---------------------------------------------------------------------------
// Popup sign-in: the provider's consent screen opens in a popup while OpenMates
// stays open. The OAuth return page (connectedAccountOAuthReturn.ts) hands the
// one-use handoff id to this opener through a BroadcastChannel; the opener
// finalizes it and announces the change with CONNECTED_ACCOUNTS_CHANGED_EVENT.
// When the popup is blocked, the same tab is redirected and the return page
// finalizes the handoff using the pending record kept in localStorage.
// ---------------------------------------------------------------------------

export const CONNECTED_ACCOUNT_OAUTH_CHANNEL = 'openmates-connected-account-oauth';
export const CONNECTED_ACCOUNTS_CHANGED_EVENT = 'openmates:connected-accounts-changed';
export const CONNECTED_ACCOUNT_OAUTH_PENDING_KEY = 'openmates_connected_account_oauth_pending';
const POPUP_WINDOW_NAME = 'openmates-connected-account-oauth-popup';
const POPUP_FEATURES = 'popup=yes,width=520,height=720';
const POPUP_CLOSED_GRACE_MS = 2500;

export type ConnectedAccountOAuthProvider = 'google' | 'figma';

export interface BeginConnectedAccountOAuthParams {
	provider: ConnectedAccountOAuthProvider;
	appId: string;
	capabilities: string[];
	/** Existing row id: reconnect it, or add this app to it, instead of creating a new row. */
	connectedAccountId?: string;
	/** Settings hash the user came from, e.g. `/#settings/account/connected-accounts`. */
	returnPath: string;
}

export interface PendingConnectedAccountOAuth {
	mode: 'popup' | 'redirect';
	provider: ConnectedAccountOAuthProvider;
	appId: string;
	connectedAccountId?: string;
	returnPath: string;
	startedAt: number;
}

export interface ConnectedAccountsChangedDetail {
	status: 'success' | 'error';
	reason?: 'provider_error' | 'finalize_failed';
	appId?: string;
}

export function readPendingConnectedAccountOAuth(): PendingConnectedAccountOAuth | null {
	try {
		const raw = localStorage.getItem(CONNECTED_ACCOUNT_OAUTH_PENDING_KEY);
		return raw ? (JSON.parse(raw) as PendingConnectedAccountOAuth) : null;
	} catch (readError) {
		console.warn('[connectedAccountOAuth] Ignoring unreadable pending OAuth record:', readError);
		return null;
	}
}

export function clearPendingConnectedAccountOAuth(): void {
	localStorage.removeItem(CONNECTED_ACCOUNT_OAUTH_PENDING_KEY);
}

/** Start provider sign-in. Resolves 'popup' (OpenMates stays open) or 'redirect' (blocked popup, same tab leaves). */
export async function beginConnectedAccountOAuth(
	params: BeginConnectedAccountOAuthParams
): Promise<'popup' | 'redirect'> {
	// Open the blank window synchronously inside the click so popup blockers allow it.
	const popup = window.open('about:blank', POPUP_WINDOW_NAME, POPUP_FEATURES);
	let authorizationUrl: string;
	try {
		const started =
			params.provider === 'figma'
				? await startFigmaOAuth({ capabilities: params.capabilities, returnPath: params.returnPath })
				: await startGoogleCalendarOAuth({
						capabilities: params.capabilities,
						returnPath: params.returnPath,
						appId: params.appId === 'mail' ? 'mail' : 'calendar'
					});
		authorizationUrl = started.authorization_url;
	} catch (startError) {
		popup?.close();
		throw startError;
	}
	const pending: PendingConnectedAccountOAuth = {
		mode: popup ? 'popup' : 'redirect',
		provider: params.provider,
		appId: params.appId,
		connectedAccountId: params.connectedAccountId,
		returnPath: params.returnPath,
		startedAt: Date.now()
	};
	localStorage.setItem(CONNECTED_ACCOUNT_OAUTH_PENDING_KEY, JSON.stringify(pending));
	if (!popup) {
		window.location.assign(authorizationUrl);
		return 'redirect';
	}
	popup.location.href = authorizationUrl;
	listenForPopupResult(pending, popup);
	return 'popup';
}

function listenForPopupResult(pending: PendingConnectedAccountOAuth, popup: Window): void {
	const channel = new BroadcastChannel(CONNECTED_ACCOUNT_OAUTH_CHANNEL);
	let closedTimer: ReturnType<typeof setTimeout> | undefined;
	const poll = setInterval(() => {
		if (popup.closed && closedTimer === undefined) closedTimer = setTimeout(stop, POPUP_CLOSED_GRACE_MS);
	}, 1000);
	function stop(): void {
		clearInterval(poll);
		if (closedTimer !== undefined) clearTimeout(closedTimer);
		channel.close();
	}
	channel.onmessage = (event: MessageEvent) => {
		const message = event.data as { type?: string; handoffId?: string; error?: string } | null;
		if (message?.type !== 'oauth-return') return;
		channel.postMessage({ type: 'oauth-return-ack' });
		stop();
		void completeConnectedAccountOAuth(pending, { handoffId: message.handoffId, providerError: message.error });
	};
}

/** Finalize (or report the failure of) one OAuth return, then announce the result to every page. */
export async function completeConnectedAccountOAuth(
	pending: PendingConnectedAccountOAuth,
	result: { handoffId?: string; providerError?: string }
): Promise<ConnectedAccountsChangedDetail> {
	let detail: ConnectedAccountsChangedDetail;
	const userId = get(userProfile).user_id;
	if (result.providerError || !result.handoffId) {
		detail = { status: 'error', reason: 'provider_error', appId: pending.appId };
	} else if (!userId) {
		detail = { status: 'error', reason: 'finalize_failed', appId: pending.appId };
	} else {
		try {
			const existingRow = pending.connectedAccountId
				? (await listConnectedAccounts()).find((row) => row.id === pending.connectedAccountId)
				: undefined;
			await finalizeOAuthHandoffAsConnectedAccount({
				userId,
				handoffId: result.handoffId,
				connectedAccountId: pending.connectedAccountId,
				updateExisting: Boolean(pending.connectedAccountId),
				existingRow
			});
			detail = { status: 'success', appId: pending.appId };
		} catch (finalizeError) {
			console.warn('[connectedAccountOAuth] Failed to finalize OAuth handoff:', finalizeError);
			detail = { status: 'error', reason: 'finalize_failed', appId: pending.appId };
		}
	}
	clearPendingConnectedAccountOAuth();
	window.dispatchEvent(new CustomEvent<ConnectedAccountsChangedDetail>(CONNECTED_ACCOUNTS_CHANGED_EVENT, { detail }));
	return detail;
}
