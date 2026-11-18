import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../config/api', () => ({
	getApiEndpoint: (path: string) => `https://api.test${path}`
}));

vi.mock('../../message_parsing/utils', () => ({
	computeSHA256: vi.fn(async (value: string) => `hash:${value}`)
}));

vi.mock('../cryptoService', () => ({
	encryptWithMasterKey: vi.fn(async (value: string) => `enc:${value.length}:${value.charCodeAt(0)}`)
}));

import { encryptWithMasterKey } from '../cryptoService';
import {
	buildEncryptedConnectedAccountRow,
	claimOAuthHandoff,
	finalizeOAuthHandoffAsConnectedAccount,
	startFigmaOAuth,
	startGoogleCalendarOAuth
} from '../connectedAccountOAuthService';

describe('connectedAccountOAuthService', () => {
	beforeEach(() => {
		vi.restoreAllMocks();
		vi.clearAllMocks();
	});

	// contract-test: supporting surface=gui.web assertions=connected-accounts.connection.private-reusable,connected-accounts.execution.client-mediated
	it('starts Google Calendar OAuth with credentials and capability body', async () => {
		const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			new Response(
				JSON.stringify({
					authorization_url: 'https://accounts.google.com/o/oauth2/v2/auth?...',
					state_expires_at: 1760000000,
					scopes: ['https://www.googleapis.com/auth/calendar.readonly']
				}),
				{ status: 200, headers: { 'Content-Type': 'application/json' } }
			)
		);

		await expect(startGoogleCalendarOAuth({ capabilities: ['read'] })).resolves.toMatchObject({
			scopes: ['https://www.googleapis.com/auth/calendar.readonly']
		});
		expect(fetchMock).toHaveBeenCalledWith('https://api.test/v1/provider-oauth/google/calendar/start', {
			method: 'POST',
			credentials: 'include',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ capabilities: ['read'], return_path: '/#settings/apps/calendar' })
		});
	});

	// contract-test: supporting surface=gui.web assertions=design-figma.connection.oauth
	it('starts Figma OAuth with the provider path and design return path', async () => {
		const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			new Response(
				JSON.stringify({
					authorization_url: 'https://example.org/oauth?state=s',
					state_expires_at: 1760000000,
					scopes: ['file_content:read']
				}),
				{ status: 200, headers: { 'Content-Type': 'application/json' } }
			)
		);

		await expect(startFigmaOAuth({ capabilities: ['read', 'variables'] })).resolves.toMatchObject({
			scopes: ['file_content:read']
		});
		expect(fetchMock).toHaveBeenCalledWith('https://api.test/v1/provider-oauth/figma/start', {
			method: 'POST',
			credentials: 'include',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ capabilities: ['read', 'variables'], return_path: '/#settings/apps/design' })
		});
	});

	// contract-test: supporting surface=gui.web assertions=design-figma.connection.oauth
	it('stores a figma handoff as a design-app row with the figma provider hash', async () => {
		const row = await buildEncryptedConnectedAccountRow({
			connectedAccountId: 'acct-figma',
			handoff: {
				provider_id: 'figma',
				refresh_token_bundle: { refresh_token: 'secret-refresh', scopes: ['file_content:read'] },
				account_hint: { account_ref: 'figma-user', capabilities: ['read', 'variables'] },
				expires_at: 1760000000
			}
		});

		expect(row).toMatchObject({ id: 'acct-figma', provider_type_hash: 'hash:figma' });
		expect(vi.mocked(encryptWithMasterKey)).toHaveBeenCalledWith(
			expect.stringContaining('"app_id":"design"')
		);
		expect(vi.mocked(encryptWithMasterKey)).toHaveBeenCalledWith(
			expect.stringContaining('"allowed_actions":["read"]')
		);
		expect(vi.mocked(encryptWithMasterKey)).toHaveBeenCalledWith('Figma');
		expect(JSON.stringify(row)).not.toContain('secret-refresh');
	});

	// contract-test: supporting surface=gui.web assertions=connected-accounts.connection.private-reusable,connected-accounts.execution.client-mediated
	it('claims OAuth handoffs with a one-time authenticated POST', async () => {
		const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			new Response(
				JSON.stringify({
					provider_id: 'google_calendar',
					refresh_token_bundle: { refresh_token: 'secret-refresh' },
					account_hint: { capabilities: ['read'] },
					expires_at: 1760000000
				}),
				{ status: 200, headers: { 'Content-Type': 'application/json' } }
			)
		);

		await expect(claimOAuthHandoff('oauth_handoff_123')).resolves.toMatchObject({
			provider_id: 'google_calendar'
		});
		expect(fetchMock).toHaveBeenCalledWith(
			'https://api.test/v1/connected-account-oauth/handoffs/oauth_handoff_123/claim',
			{ method: 'POST', credentials: 'include' }
		);
	});

	// contract-test: supporting surface=gui.web assertions=connected-accounts.connection.private-reusable,connected-accounts.execution.client-mediated
	it('encrypts handoff payloads into connected-account rows without plaintext keys', async () => {
		const row = await buildEncryptedConnectedAccountRow({
			connectedAccountId: 'acct-1',
			handoff: {
				provider_id: 'google_calendar',
				refresh_token_bundle: { refresh_token: 'secret-refresh', scopes: ['calendar.readonly'] },
				account_hint: {
					label: 'Work Calendar',
					account_ref: 'calendar-work',
					capabilities: ['read', 'write'],
					scopes: ['calendar.events']
				},
				expires_at: 1760000000
			}
		});

		expect(row).toMatchObject({
			id: 'acct-1',
			provider_type_hash: 'hash:google_calendar'
		});
		expect(row.encrypted_provider_type.startsWith('enc:')).toBe(true);
		expect(row.encrypted_account_label.startsWith('enc:')).toBe(true);
		expect(vi.mocked(encryptWithMasterKey)).toHaveBeenCalledWith(
			expect.stringContaining('"allowed_actions":["read","write","update"]')
		);
		expect(vi.mocked(encryptWithMasterKey)).toHaveBeenCalledWith(
			expect.stringContaining('"read":"allow_automatically"')
		);
		expect(vi.mocked(encryptWithMasterKey)).toHaveBeenCalledWith(
			expect.stringContaining('"update":"always_ask"')
		);
		expect(JSON.stringify(row)).not.toContain('"refresh_token"');
		expect(JSON.stringify(row)).not.toContain('secret-refresh');
		expect(JSON.stringify(row)).not.toContain('"scopes"');
	});

	// contract-test: supporting surface=gui.web assertions=connected-accounts.connection.private-reusable,connected-accounts.execution.client-mediated
	it('finalizes a handoff by claiming then storing the encrypted row', async () => {
		const fetchMock = vi.spyOn(globalThis, 'fetch')
			.mockResolvedValueOnce(
				new Response(
					JSON.stringify({
						provider_id: 'google_calendar',
						refresh_token_bundle: { refresh_token: 'secret-refresh' },
						account_hint: { capabilities: ['read'], label: 'Work Calendar' },
						expires_at: 1760000000
					}),
					{ status: 200, headers: { 'Content-Type': 'application/json' } }
				)
			)
			.mockResolvedValueOnce(
				new Response(JSON.stringify({ id: 'acct-1', sync_version: 1760000001 }), {
					status: 200,
					headers: { 'Content-Type': 'application/json' }
				})
			);

		await expect(
			finalizeOAuthHandoffAsConnectedAccount({
				userId: 'user-1',
				handoffId: 'oauth_handoff_123',
				connectedAccountId: 'acct-1'
			})
		).resolves.toEqual({ id: 'acct-1', sync_version: 1760000001 });

		const storageCall = fetchMock.mock.calls[1];
		expect(storageCall[0]).toBe('https://api.test/v1/connected-accounts');
		expect(JSON.stringify(storageCall[1])).not.toContain('secret-refresh');
	});

	// contract-test: supporting surface=gui.web assertions=connected-accounts.connection.private-reusable,connected-accounts.execution.client-mediated
	it('finalizes an account update with a PATCH and merged capability envelope', async () => {
		const fetchMock = vi.spyOn(globalThis, 'fetch')
			.mockResolvedValueOnce(
				new Response(
					JSON.stringify({
						provider_id: 'google_calendar',
						refresh_token_bundle: { refresh_token: 'secret-refresh' },
						account_hint: { capabilities: ['write'], label: 'Work Calendar' },
						expires_at: 1760000000
					}),
					{ status: 200, headers: { 'Content-Type': 'application/json' } }
				)
			)
			.mockResolvedValueOnce(
				new Response(JSON.stringify({ id: 'acct-1', sync_version: 1760000002 }), {
					status: 200,
					headers: { 'Content-Type': 'application/json' }
				})
			);

		await expect(
			finalizeOAuthHandoffAsConnectedAccount({
				userId: 'user-1',
				handoffId: 'oauth_handoff_update',
				connectedAccountId: 'acct-1',
				updateExisting: true,
				capabilitiesOverride: ['read', 'write']
			})
		).resolves.toEqual({ id: 'acct-1', sync_version: 1760000002 });

		const storageCall = fetchMock.mock.calls[1];
		expect(storageCall[0]).toBe('https://api.test/v1/connected-accounts/acct-1');
		expect(storageCall[1]).toMatchObject({ method: 'PATCH' });
		expect(vi.mocked(encryptWithMasterKey)).toHaveBeenCalledWith(
			expect.stringContaining('["read","write"]')
		);
		expect(JSON.stringify(storageCall[1])).not.toContain('secret-refresh');
	});
});
