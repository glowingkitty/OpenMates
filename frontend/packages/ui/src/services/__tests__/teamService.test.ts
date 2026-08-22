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

import { createTeam } from '../teamService';

describe('teamService', () => {
	beforeEach(() => {
		vi.restoreAllMocks();
		vi.clearAllMocks();
		vi.spyOn(crypto, 'randomUUID').mockReturnValue('team-local-id' as ReturnType<Crypto['randomUUID']>);
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
