// frontend/packages/ui/src/services/__tests__/teamService.test.ts
//
// Regression coverage for Teams V1 browser create normalization. The backend
// may acknowledge a newly-created team with a sparse row, so the browser must
// keep the encrypted payload it just submitted until list/get returns a full row.
//
// Spec: docs/specs/teams-v1/spec.yml

import { beforeEach, describe, expect, it, vi } from 'vitest';

const cryptoMocks = vi.hoisted(() => ({
	decryptChatKeyWithMasterKey: vi.fn(async () => new Uint8Array([1, 2, 3, 4])),
	decryptWithEmbedKey: vi.fn(async (value: string) => value.replace(/^enc:/, '')),
	encryptChatKeyWithMasterKey: vi.fn(async () => 'wrapped-team-key'),
	encryptWithEmbedKey: vi.fn(async (value: string) => `enc:${value}`),
	generateEmbedKey: vi.fn(() => new Uint8Array([1, 2, 3, 4])),
	unwrapEmbedKeyWithEmbedKey: vi.fn(async () => new Uint8Array([5, 6, 7, 8])),
	wrapEmbedKeyWithChatKey: vi.fn(async () => 'wrapped-chat-key')
}));

vi.mock('../../config/api', () => ({
	getApiEndpoint: (path: string) => `https://api.test${path}`
}));

vi.mock('../cryptoService', () => cryptoMocks);
vi.mock('../../stores/userProfile', async () => {
	const { writable } = await import('svelte/store');
	return { userProfile: writable({ user_id: 'team-cache-test-user' }) };
});

import { createTeam, getTeam, getTeamKey, listTeams } from '../teamService';
import { invalidateWorkspaceCaches } from '../workspaceCacheLifecycle';
import { TEAMS_UPDATED_EVENT } from '../../stores/teamStore';

describe('teamService', () => {
	beforeEach(() => {
		invalidateWorkspaceCaches();
		vi.restoreAllMocks();
		vi.clearAllMocks();
		vi.spyOn(crypto, 'randomUUID').mockReturnValue('team-local-id' as ReturnType<Crypto['randomUUID']>);
	});

	// contract-test: supporting surface=gui.web assertions=teams.lifecycle.encrypted-profiled,teams.context.full-switch-local
	it('shares a recent team list and refreshes after a local team update', async () => {
		const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({ teams: [] }), {
			status: 200,
			headers: { 'Content-Type': 'application/json' }
		}));
		await listTeams();
		await listTeams();
		expect(fetchMock).toHaveBeenCalledTimes(1);
		window.dispatchEvent(new CustomEvent(TEAMS_UPDATED_EVENT));
		await listTeams();
		expect(fetchMock).toHaveBeenCalledTimes(2);
	});

	// contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
	it('discards a team key decrypted after the workspace identity resets', async () => {
		let releaseDecrypt!: (key: Uint8Array) => void;
		cryptoMocks.decryptChatKeyWithMasterKey.mockImplementationOnce(() => new Promise(resolve => {
			releaseDecrypt = resolve;
		}));
		const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({
			team: { team_id: 'team-old', encrypted_team_key: 'wrapped', encrypted_name: 'enc:Team' }
		}), { status: 200, headers: { 'Content-Type': 'application/json' } }));
		const oldRead = getTeam('team-old');
		await vi.waitFor(() => expect(cryptoMocks.decryptChatKeyWithMasterKey).toHaveBeenCalledTimes(1));
		invalidateWorkspaceCaches();
		releaseDecrypt(new Uint8Array([1, 2, 3, 4]));
		await expect(oldRead).rejects.toThrow(/cancelled/);
		await expect(getTeamKey('team-old')).resolves.toEqual(new Uint8Array([1, 2, 3, 4]));
		expect(fetchMock).toHaveBeenCalledTimes(2);
		expect(cryptoMocks.decryptChatKeyWithMasterKey).toHaveBeenCalledTimes(2);
	});

	// contract-test: direct surface=gui.web assertions=teams.lifecycle.encrypted-profiled
	it('keeps the submitted encrypted fields when create returns a sparse team row', async () => {
		const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			new Response(JSON.stringify({ team: { team_id: 'team-server-id', encrypted_team_key: 'server-wrapper', role: 'owner' } }), {
				status: 200,
				headers: { 'Content-Type': 'application/json' }
			})
		);

		const team = await createTeam({
			name: 'Launch team',
			description: 'Encrypted browser team'
		});

		expect(fetchMock).toHaveBeenCalledWith('https://api.test/v1/teams', expect.objectContaining({
			method: 'POST',
			credentials: 'include'
		}));
		expect(team).toMatchObject({
			team_id: 'team-server-id',
			name: 'Launch team',
			description: 'Encrypted browser team',
			role: 'owner',
			zeroBalance: 0
		});
		expect(cryptoMocks.decryptChatKeyWithMasterKey).not.toHaveBeenCalled();
		expect(team.encrypted.encrypted_team_key).toBe('wrapped-team-key');
		expect(team.encrypted.encrypted_name).toBe('enc:Launch team');
		expect(team.encrypted.encrypted_description).toBe('enc:Encrypted browser team');
	});
});
