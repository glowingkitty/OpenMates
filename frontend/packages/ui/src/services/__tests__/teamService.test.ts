// frontend/packages/ui/src/services/__tests__/teamService.test.ts
//
// Regression coverage for Teams V1 browser create normalization. The backend
// may acknowledge a newly-created team with a sparse row, so the browser must
// keep the encrypted payload it just submitted until list/get returns a full row.
//
// Spec: docs/specs/teams-v1/spec.yml

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';

Object.defineProperty(globalThis, 'crypto', { configurable: true, value: webcrypto });

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
vi.mock('../uploadPrivacy', () => ({ prepareFileForUpload: vi.fn(async (file: File) => file) }));
vi.mock('../../stores/userProfile', async () => {
	const { writable } = await import('svelte/store');
	return { userProfile: writable({ user_id: 'team-cache-test-user', username: 'Mira' }) };
});

import { createTeam, createTeamEmailInvite, deleteTeam, getTeam, getTeamKey, isTeamAIInvocation, listTeams, loadTeamBilling, loadTeamMembers, loadTeamMemberAvatar, TeamRequestCancelledError, type TeamViewModel } from '../teamService';
import { invalidateWorkspaceCaches } from '../workspaceCacheLifecycle';
import { getActiveTeamContextSnapshot, setActiveTeamContext, TEAMS_UPDATED_EVENT } from '../../stores/teamStore';

describe('teamService', () => {
	// contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked
	it('invokes AI only for OpenMates or a selected known Mate, not a human username', () => {
		expect(isTeamAIInvocation('@OpenMates summarize')).toBe(true);
		expect(isTeamAIInvocation('@mate:software_development review')).toBe(true);
		expect(isTeamAIInvocation('@mate:unknown_person review')).toBe(false);
		expect(isTeamAIInvocation('@Sophia review')).toBe(false);
		expect(isTeamAIInvocation('email@openmates.org')).toBe(false);
		expect(isTeamAIInvocation('@openmates_fake')).toBe(false);
	});
	beforeEach(() => {
		invalidateWorkspaceCaches();
		vi.restoreAllMocks();
		vi.clearAllMocks();
		vi.spyOn(crypto, 'randomUUID').mockReturnValue('team-local-id' as ReturnType<Crypto['randomUUID']>);
	});

	// contract-test: direct surface=gui.web assertions=billing.storage.weekly-quote
	it('uses the versioned numeric team wallet balance over an older encrypted snapshot', async () => {
		vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ billing: {
			balance_credits: 4, version: 3, encrypted_balance: 'enc:99'
		} }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
		const team = { team_id: 'team-1', zeroBalance: 99, encrypted: { team_id: 'team-1' } } as TeamViewModel;
		const result = await loadTeamBilling(team);
		expect(result.balanceCredits).toBe(4);
		expect(result.version).toBe(3);
		expect(cryptoMocks.decryptWithEmbedKey).not.toHaveBeenCalled();
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

	// contract-test: direct surface=gui.web assertions=teams.lifecycle.encrypted-profiled,teams.context.full-switch-local
	it('deletes an owned team and drops its active context and decrypted key', async () => {
		const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
			const path = new URL(String(input)).pathname;
			if (path === '/v1/teams' && !init?.method) return new Response(JSON.stringify({ teams: [{
				team_id: 'team-1', encrypted_team_key: 'wrapped', encrypted_name: 'enc:Studio', role: 'owner'
			}] }), { status: 200 });
			if (path === '/v1/teams/team-1' && init?.method === 'DELETE') return new Response(JSON.stringify({ success: true }), { status: 200 });
			throw new Error(`Unexpected request ${path}`);
		});
		const [team] = await listTeams();
		setActiveTeamContext(team);
		await deleteTeam(team.team_id);
		expect(getActiveTeamContextSnapshot().teamId).toBeNull();
		expect(fetchMock).toHaveBeenCalledWith('https://api.test/v1/teams/team-1', expect.objectContaining({
			method: 'DELETE', credentials: 'include'
		}));
		await listTeams();
		expect(fetchMock).toHaveBeenCalledTimes(3);
	});

	// contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
	it('discards a team key decrypted after the workspace identity resets', async () => {
		let releaseDecrypt!: (key: Uint8Array<ArrayBuffer>) => void;
		cryptoMocks.decryptChatKeyWithMasterKey.mockImplementationOnce(() => new Promise<Uint8Array<ArrayBuffer>>(resolve => {
			releaseDecrypt = resolve;
		}));
		const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({
			team: { team_id: 'team-old', encrypted_team_key: 'wrapped', encrypted_name: 'enc:Team' }
		}), { status: 200, headers: { 'Content-Type': 'application/json' } }));
		const oldRead = getTeam('team-old');
		await vi.waitFor(() => expect(cryptoMocks.decryptChatKeyWithMasterKey).toHaveBeenCalledTimes(1));
		invalidateWorkspaceCaches();
		releaseDecrypt(new Uint8Array([1, 2, 3, 4]));
		await expect(oldRead).rejects.toBeInstanceOf(TeamRequestCancelledError);
		await expect(getTeamKey('team-old')).resolves.toEqual(new Uint8Array([1, 2, 3, 4]));
		expect(fetchMock).toHaveBeenCalledTimes(2);
		expect(cryptoMocks.decryptChatKeyWithMasterKey).toHaveBeenCalledTimes(2);
	});

	// contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
	it('identifies a team list superseded by an account/key transition', async () => {
		let releaseResponse!: (response: Response) => void;
		const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(() => new Promise(resolve => {
			releaseResponse = resolve;
		}));
		const oldRead = listTeams();
		await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
		invalidateWorkspaceCaches();
		releaseResponse(new Response(JSON.stringify({ teams: [] }), {
			status: 200,
			headers: { 'Content-Type': 'application/json' }
		}));
		await expect(oldRead).rejects.toBeInstanceOf(TeamRequestCancelledError);
	});

	// contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
	it('decrypts Team billing and sends an encrypted invite for the active account', async () => {
		let invitePayload: Record<string, unknown> | null = null;
		cryptoMocks.decryptChatKeyWithMasterKey.mockResolvedValueOnce(new Uint8Array(32));
		vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
			const url = String(input);
			if (url === 'https://api.test/v1/teams/team-1') {
				return new Response(JSON.stringify({ team: {
					team_id: 'team-1', encrypted_team_key: 'wrapped', encrypted_name: 'enc:Project Team'
				} }), { status: 200 });
			}
			if (url === 'https://api.test/v1/teams/team-1/billing') {
				return new Response(JSON.stringify({ billing: { encrypted_balance: 'enc:42' } }), { status: 200 });
			}
			if (url === 'https://api.test/v1/teams/team-1/invites') {
				invitePayload = JSON.parse(String(init?.body)) as Record<string, unknown>;
				return new Response(JSON.stringify({ invite: { invite_id: 'invite-1', status: 'created' } }), { status: 200 });
			}
			throw new Error(`Unexpected Teams request: ${url}`);
		});

		const team = await getTeam('team-1');
		const billing = await loadTeamBilling(team);
		const invite = await createTeamEmailInvite(team, ' Member@Example.invalid ', 'member');

		expect(billing.balanceCredits).toBe(42);
		expect(invite).toMatchObject({ inviteId: 'invite-1', role: 'member', status: 'created' });
		expect(invitePayload).toMatchObject({
			recipient_email: 'member@example.invalid',
			encrypted_recipient_hint: 'enc:{"recipient_email":"member@example.invalid","role":"member"}'
		});
		expect(invitePayload).toHaveProperty('encrypted_invite_team_key');
		expect(invitePayload).toHaveProperty('invite_key_kdf_context');
		expect(JSON.stringify(invitePayload)).not.toContain(invite.inviteUrl?.split('#key=')[1]);
		expect(invite.inviteUrl).toContain('#key=');
	});

	// contract-test: direct surface=gui.web assertions=teams.lifecycle.encrypted-profiled
	it('keeps the submitted encrypted fields when create returns a sparse team row', async () => {
		let createPayload: Record<string, unknown> = {};
		const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
			if (String(input).endsWith('/name-approval')) {
				expect(JSON.parse(String(init?.body))).toEqual({ name: 'launch team' });
				return new Response(JSON.stringify({ approval_token: 'short-lived-token' }), { status: 200 });
			}
			createPayload = JSON.parse(String(init?.body));
			return new Response(JSON.stringify({ team: { team_id: 'team-server-id', encrypted_team_key: 'server-wrapper', role: 'owner' } }), { status: 200 });
		});

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
		expect(createPayload.name_approval_token).toBe('short-lived-token');
		expect(createPayload.encrypted_member_profile).toBe('enc:{"display_name":"Mira","avatar":{"mode":"generated","icon_name":"mate","background_color":"#4d73ff"}}');
	});

	// contract-test: direct surface=gui.web assertions=teams.membership.role-gated
	it('decrypts team-scoped member names without relying on server plaintext profiles', async () => {
		vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
			const path = new URL(String(input)).pathname;
			if (path === '/v1/teams/team-1') return new Response(JSON.stringify({ team: {
				team_id: 'team-1', encrypted_team_key: 'wrapped', encrypted_name: 'enc:Studio', role: 'owner'
			} }), { status: 200 });
			if (path === '/v1/teams/team-1/members') return new Response(JSON.stringify({ members: [{
				user_id: 'member-1', role: 'member', status: 'active',
				encrypted_member_profile: 'enc:{"display_name":"Alex","avatar":{"mode":"generated","icon_name":"mate","background_color":"#4d73ff"}}'
			}] }), { status: 200 });
			throw new Error(`Unexpected request ${path}`);
		});
		const members = await loadTeamMembers('team-1');
		expect(members[0].profile?.display_name).toBe('Alex');
		expect(members[0]).not.toHaveProperty('username');
	});

	// contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
	it('discards member identities arriving after a workspace transition', async () => {
		let releaseResponse!: (response: Response) => void;
		vi.spyOn(globalThis, 'fetch').mockImplementation(() => new Promise(resolve => { releaseResponse = resolve; }));
		const pending = loadTeamMembers('team-old');
		invalidateWorkspaceCaches();
		releaseResponse(new Response(JSON.stringify({ members: [{ user_id: 'member-1', encrypted_member_profile: 'enc:{"display_name":"Alex"}' }] }), { status: 200 }));
		await expect(pending).rejects.toBeInstanceOf(TeamRequestCancelledError);
		expect(cryptoMocks.decryptWithEmbedKey).not.toHaveBeenCalled();
	});

	// contract-test: supporting surface=gui.web assertions=teams.membership.role-gated
	it('loads a member image only through its authenticated Team profile endpoint', async () => {
		const createUrl = vi.fn(() => 'blob:team-member');
		vi.stubGlobal('URL', class extends URL { static createObjectURL = createUrl; });
		try {
			const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('image', { status: 200, headers: { 'content-type': 'image/png' } }));
			await expect(loadTeamMemberAvatar('team-1', { user_id: 'member-1', profile_image_url: '/v1/teams/team-other/members/member-1/profile-image' } as Parameters<typeof loadTeamMemberAvatar>[1])).resolves.toBeNull();
			expect(fetchMock).not.toHaveBeenCalled();
			await expect(loadTeamMemberAvatar('team-1', { user_id: 'member-1', profile_image_url: '/v1/teams/team-1/members/member-1/profile-image' } as Parameters<typeof loadTeamMemberAvatar>[1])).resolves.toBe('blob:team-member');
			expect(fetchMock).toHaveBeenCalledWith('https://api.test/v1/teams/team-1/members/member-1/profile-image', { credentials: 'include' });
			expect(createUrl).toHaveBeenCalledOnce();
		} finally { vi.unstubAllGlobals(); }
	});

	// contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
	it('does not create a decrypted image URL when image bytes arrive after switching context', async () => {
		const createUrl = vi.fn(() => 'blob:stale-member');
		vi.stubGlobal('URL', class extends URL { static createObjectURL = createUrl; });
		try {
			let releaseBlob!: (blob: Blob) => void;
			const response = new Response('image', { status: 200, headers: { 'content-type': 'image/png' } });
			vi.spyOn(response, 'blob').mockImplementation(() => new Promise(resolve => { releaseBlob = resolve; }));
			vi.spyOn(globalThis, 'fetch').mockResolvedValue(response);
			const pending = loadTeamMemberAvatar('team-1', { user_id: 'member-1', profile_image_url: '/v1/teams/team-1/members/member-1/profile-image' } as Parameters<typeof loadTeamMemberAvatar>[1]);
			await vi.waitFor(() => expect(response.blob).toHaveBeenCalledOnce());
			invalidateWorkspaceCaches();
			releaseBlob(new Blob(['image']));
			await expect(pending).rejects.toBeInstanceOf(TeamRequestCancelledError);
			expect(createUrl).not.toHaveBeenCalled();
		} finally { vi.unstubAllGlobals(); }
	});
});
