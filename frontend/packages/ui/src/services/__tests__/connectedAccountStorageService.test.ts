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
						'enc:{"account_ref":"calendar-work","label":"Work","capabilities":["read"],"runtime_modes":{"read":"ask_each_time"}}'
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
				runtime_modes: { read: 'ask_each_time' }
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
});
