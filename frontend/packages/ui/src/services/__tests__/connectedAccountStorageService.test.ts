import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../config/api', () => ({
	getApiEndpoint: (path: string) => `https://api.test${path}`
}));

vi.mock('../../message_parsing/utils', () => ({
	computeSHA256: vi.fn(async (value: string) => `hash:${value}`)
}));

vi.mock('../cryptoService', () => ({
	decryptWithMasterKey: vi.fn(async (value: string) => value.replace(/^enc:/, ''))
}));

import { decryptWithMasterKey } from '../cryptoService';

import {
	buildConnectedAccountSendContext,
	createConnectedAccount,
	listConnectedAccounts,
	updateConnectedAccount
} from '../connectedAccountStorageService';

const encryptedRow = {
	id: 'acct-1',
	encrypted_provider_type: 'enc:google',
	provider_type_hash: 'hash:google',
	encrypted_account_label: 'enc:Work calendar',
	encrypted_refresh_token_bundle: 'enc:refresh-token-envelope',
	encrypted_capabilities: 'enc:read-write',
	encrypted_app_permissions: 'enc:calendar'
};

describe('connectedAccountStorageService', () => {
	beforeEach(() => {
		vi.restoreAllMocks();
		vi.clearAllMocks();
	});

	it('creates encrypted rows with the current user hash and credentials', async () => {
		const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			new Response(JSON.stringify({ id: 'acct-1', sync_version: 1760000000 }), {
				status: 200,
				headers: { 'Content-Type': 'application/json' }
			})
		);

		await expect(
			createConnectedAccount({ userId: 'user-1', row: encryptedRow })
		).resolves.toEqual({ id: 'acct-1', sync_version: 1760000000 });

		expect(fetchMock).toHaveBeenCalledWith('https://api.test/v1/connected-accounts', {
			method: 'POST',
			credentials: 'include',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ ...encryptedRow, hashed_user_id: 'hash:user-1' })
		});
	});

	it('lists encrypted rows and rejects plaintext provider identity in responses', async () => {
		vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			new Response(
				JSON.stringify({
					rows: [{ ...encryptedRow, hashed_user_id: 'hash:user-1', provider_email: 'user@example.com' }]
				}),
				{ status: 200, headers: { 'Content-Type': 'application/json' } }
			)
		);

		await expect(listConnectedAccounts()).rejects.toThrow('provider_email');
	});

	it('patches encrypted fields without owner hashes or plaintext fields', async () => {
		const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			new Response(JSON.stringify({ id: 'acct-1', sync_version: 1760000200 }), {
				status: 200,
				headers: { 'Content-Type': 'application/json' }
			})
		);

		await expect(
			updateConnectedAccount({
				accountId: 'acct-1',
				patch: { encrypted_account_label: 'enc:Renamed' }
			})
		).resolves.toEqual({ id: 'acct-1', sync_version: 1760000200 });

		expect(fetchMock).toHaveBeenCalledWith('https://api.test/v1/connected-accounts/acct-1', {
			method: 'PATCH',
			credentials: 'include',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ encrypted_account_label: 'enc:Renamed' })
		});
	});

	it('rejects plaintext refresh tokens before calling the API', async () => {
		const fetchMock = vi.spyOn(globalThis, 'fetch');

		await expect(
			createConnectedAccount({
				userId: 'user-1',
				row: { ...encryptedRow, refresh_token: 'secret' } as never
			})
		).rejects.toThrow('refresh_token');
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it('builds chat directory and broker-only token ref inputs from encrypted rows', async () => {
		const context = await buildConnectedAccountSendContext({
			appId: 'calendar',
			rows: [
				{
					...encryptedRow,
					hashed_user_id: 'hash:user-1',
					encrypted_account_label: 'enc:"Work calendar"',
					encrypted_capabilities: 'enc:["read","write"]',
					encrypted_app_permissions:
						'enc:{"app_id":"calendar","allowed_actions":["read"],"action_scope":{"calendar_id":"primary"}}',
					encrypted_refresh_token_bundle: 'enc:{"refresh_token":"secret-refresh","provider":"google"}',
					encrypted_account_directory_hint:
						'enc:{"account_ref":"calendar-work","label":"Work","capabilities":["read"],"runtime_modes":{"read":"allow_automatically"}}'
				}
			]
		});

		expect(context?.directory).toEqual([
			{
				connected_account_id: 'acct-1',
				app_id: 'calendar',
				account_ref: 'calendar-work',
				label: 'Work',
				capabilities: ['read'],
				runtime_modes: { read: 'allow_automatically' }
			}
		]);
		expect(JSON.stringify(context?.directory)).not.toContain('secret-refresh');
		expect(context?.tokenRefInputs?.[0]).toMatchObject({
			connected_account_id: 'acct-1',
			app_id: 'calendar',
			allowed_actions: ['read'],
			refresh_token_envelope: { refresh_token: 'secret-refresh', provider: 'google' },
			action_scope: { calendar_id: 'primary' }
		});
	});

	it('pre-submits token refs only for auto runtime modes during normal sends', async () => {
		const context = await buildConnectedAccountSendContext({
			appId: 'calendar',
			rows: [
				{
					...encryptedRow,
					hashed_user_id: 'hash:user-1',
					encrypted_account_label: 'enc:"Work calendar"',
					encrypted_capabilities: 'enc:["read","write","delete"]',
					encrypted_app_permissions:
						'enc:{"app_id":"calendar","allowed_actions":["read","write","update","delete"]}',
					encrypted_refresh_token_bundle: 'enc:{"refresh_token":"secret-refresh","provider":"google"}',
					encrypted_account_directory_hint:
						'enc:{"account_ref":"calendar-work","label":"Work","capabilities":["read","write","delete"],"runtime_modes":{"read":"allow_automatically","write":"always_ask","update":"always_ask","delete":"always_ask"}}'
				}
			]
		});

		expect(context?.directory?.[0].runtime_modes).toEqual({
			read: 'allow_automatically',
			write: 'always_ask',
			update: 'always_ask',
			delete: 'always_ask'
		});
		expect(context?.tokenRefInputs).toHaveLength(1);
		expect(context?.tokenRefInputs?.[0].allowed_actions).toEqual(['read']);
		expect(JSON.stringify(context?.tokenRefInputs)).not.toContain('always_ask');
	});

	it('does not decrypt refresh token envelopes when every action is always ask', async () => {
		const context = await buildConnectedAccountSendContext({
			appId: 'calendar',
			rows: [
				{
					...encryptedRow,
					hashed_user_id: 'hash:user-1',
					encrypted_account_label: 'enc:"Work calendar"',
					encrypted_capabilities: 'enc:["write","delete"]',
					encrypted_app_permissions:
						'enc:{"app_id":"calendar","allowed_actions":["write","update","delete"]}',
					encrypted_refresh_token_bundle: 'enc:{"refresh_token":"secret-refresh","provider":"google"}',
					encrypted_account_directory_hint:
						'enc:{"account_ref":"calendar-work","label":"Work","capabilities":["write","delete"],"runtime_modes":{"write":"always_ask","update":"always_ask","delete":"always_ask"}}'
				}
			]
		});

		expect(context?.directory).toHaveLength(1);
		expect(context?.tokenRefInputs).toEqual([]);
		expect(vi.mocked(decryptWithMasterKey)).not.toHaveBeenCalledWith(
			'enc:{"refresh_token":"secret-refresh","provider":"google"}'
		);
	});

	it('narrows broker token refs to an approved action override', async () => {
		const context = await buildConnectedAccountSendContext({
			appId: 'calendar',
			allowedActionsOverride: ['update'],
			rows: [
				{
					...encryptedRow,
					hashed_user_id: 'hash:user-1',
					encrypted_account_label: 'enc:"Work calendar"',
					encrypted_capabilities: 'enc:["read","write","update","delete"]',
					encrypted_app_permissions:
						'enc:{"app_id":"calendar","allowed_actions":["read","write","update","delete"]}',
					encrypted_refresh_token_bundle: 'enc:{"refresh_token":"secret-refresh","provider":"google"}'
				}
			]
		});

		expect(context?.tokenRefInputs?.[0].allowed_actions).toEqual(['update']);
	});

	it('creates scoped broker token refs for explicit connected-account approvals', async () => {
		const context = await buildConnectedAccountSendContext({
			appId: 'calendar',
			allowedActionsOverride: ['delete'],
			actionScopesOverride: [
				{ calendar_id: 'primary', event_id: 'event-1' },
				{ calendar_id: 'primary', event_id: 'event-2' }
			],
			rows: [
				{
					...encryptedRow,
					hashed_user_id: 'hash:user-1',
					encrypted_account_label: 'enc:"Work calendar"',
					encrypted_capabilities: 'enc:["read","write","delete"]',
					encrypted_app_permissions:
						'enc:{"app_id":"calendar","allowed_actions":["read","write","update","delete"]}',
					encrypted_refresh_token_bundle: 'enc:{"refresh_token":"secret-refresh","provider":"google"}'
				}
			]
		});

		expect(context?.tokenRefInputs).toHaveLength(2);
		expect(context?.tokenRefInputs?.map((input) => input.action_scope)).toEqual([
			{ calendar_id: 'primary', event_id: 'event-1' },
			{ calendar_id: 'primary', event_id: 'event-2' }
		]);
		expect(context?.tokenRefInputs?.map((input) => input.allowed_actions)).toEqual([
			['delete'],
			['delete']
		]);
	});
});
