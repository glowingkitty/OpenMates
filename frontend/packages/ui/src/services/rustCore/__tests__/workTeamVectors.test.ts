// Team `work` parity vectors (parked wave-5 `work` lane, slice 2: Teams).
// The committed packages/openmates-rust/src/web_work/teams_ts_vectors.json is
// regenerated here from the real flag-off teamService (crypto, fetch and key
// lookups stubbed; invite HKDF/AES-GCM run on real WebCrypto with fixed random
// bytes); teams_tests.rs replays it through the Rust ops. Regenerate:
//   WORK_VECTORS_WRITE=1 npx vitest run src/services/rustCore/__tests__/workTeamVectors.test.ts
// spec: specifications/features/teams#teams.lifecycle.encrypted-profiled
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { webcrypto } from 'node:crypto';
import { beforeEach, describe, expect, it, vi } from 'vitest';

Object.defineProperty(globalThis, 'crypto', { configurable: true, value: webcrypto });

const stub = vi.hoisted(() => ({ encrypts: [] as Array<[string, number]> }));

vi.mock('../../../config/api', () => ({
	getApiEndpoint: (path: string) => `https://api.test${path}`,
	getUploadEndpoint: (path: string) => `https://upload.test${path}`,
}));
vi.mock('../../cryptoService', () => ({
	decryptChatKeyWithMasterKey: vi.fn(async () => new Uint8Array([1])),
	decryptWithEmbedKey: vi.fn(async (value: string) => (value.startsWith('sealed:') ? value.slice(7) : null)),
	encryptWithEmbedKey: vi.fn(async (value: string, key: Uint8Array) => {
		stub.encrypts.push([value, key[0]]);
		return `sealed:${key[0]}:${value}`;
	}),
	encryptChatKeyWithMasterKey: vi.fn(async (key: Uint8Array) => `wrapped-master:${key[0]}`),
	generateEmbedKey: vi.fn(() => new Uint8Array([9])),
	unwrapEmbedKeyWithEmbedKey: vi.fn(async () => new Uint8Array([5])),
	wrapEmbedKeyWithChatKey: vi.fn(async () => 'wrapped-chat'),
}));
vi.mock('../../uploadPrivacy', () => ({ prepareFileForUpload: vi.fn(async (file: File) => file) }));
vi.mock('../../../stores/userProfile', async () => {
	const { writable } = await import('svelte/store');
	return { userProfile: writable({ user_id: 'team-vector-user', username: '  Mira  ' }) };
});

import * as service from '../../teamService';
import { decryptWithEmbedKey } from '../../cryptoService';
import { invalidateWorkspaceCaches } from '../../workspaceCacheLifecycle';
import { decryptWorkFields } from '../../work/workRust';
import {
	FRESH_ID, NOW_SECONDS, USERNAME, avatarCases, billingCases, bodyCases, createdCases, inviteCases, inviteResultCases,
	memberCases, pathCases, teamRecord, teamView, uploadCases, viewCases,
} from './helpers/workTeamCases';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_work/teams_ts_vectors.json');
const TEAM_KEY = new Uint8Array([1]);
type Json = Record<string, unknown>;

let reply: unknown = {};
let upload = { status: 200, text: '{}' };
let requests: Array<{ url: string; init?: RequestInit }> = [];
let derived: Uint8Array[] = [];
let opened: Uint8Array[] = [];

const json = <T>(value: T): T => (value === undefined ? value : (JSON.parse(JSON.stringify(value)) as T));
const strip = (url: string) => url.replace(/^https:\/\/(api|upload)\.test/, '');
const message = (error: unknown) => ({ error: (error as Error).message });
const plaintext = async (value: unknown) => (typeof value === 'string' && value ? (await decryptWithEmbedKey(value, TEAM_KEY)) ?? null : null);

/** A sent body as the wire saw it: JSON text, or FormData entries in append order. */
function sentBody(init?: RequestInit): Json {
	if (init?.body instanceof FormData) {
		return Object.fromEntries(Array.from(init.body.entries()).map(([k, v]) => [k, typeof v === 'string' ? v : `file:${(v as File).name}`]));
	}
	return JSON.parse(String(init?.body)) as Json;
}

/** Key order of the body and of every nested plain object (Rust serde maps are sorted, so order is checked by name). */
function keyOrder(body: Json): { keys: string[]; object_keys: Record<string, string[]> } {
	const objects = Object.entries(body).filter(([, v]) => v && typeof v === 'object' && !Array.isArray(v));
	return { keys: Object.keys(body), object_keys: Object.fromEntries(objects.map(([k, v]) => [k, Object.keys(v as Json)])) };
}

/** The length-prefixed HKDF info pieces deriveInviteKey used: [email, inviteId, teamId, origin]. */
function infoPieces(info: Uint8Array): string[] {
	const pieces: string[] = [];
	for (let offset = 0; offset < info.length;) {
		const length = new DataView(info.buffer, info.byteOffset + offset, 4).getUint32(0, false);
		pieces.push(new TextDecoder().decode(info.slice(offset + 4, offset + 4 + length)));
		offset += 4 + length;
	}
	return pieces;
}

const base64 = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes));

async function decisions(): Promise<Json[]> {
	const out: Json[] = [];
	const push = (name: string, op: string, input: unknown, expected: unknown, extra: Json = {}) =>
		out.push({ name, op, input: json(input), expected: json(expected), ...extra });
	for (const c of viewCases) {
		invalidateWorkspaceCaches();
		reply = { team: c.record };
		try {
			const { encrypted: _record, ...view } = await service.getTeam(String(c.record.team_id));
			push(c.name, 'teamView', { record: c.record, fields: await decryptWorkFields(c.record, TEAM_KEY) }, view,
				{ policy_keys: Object.keys(view.securityPolicy ?? {}) });
		} catch (error) {
			push(c.name, 'teamView', { record: c.record, fields: {} }, message(error));
		}
	}
	for (const c of memberCases) {
		invalidateWorkspaceCaches();
		reply = { members: c.members, team: teamRecord() };
		const result = await service.loadTeamMembers('team-1');
		const profiles = result.map((m, i) => ('profile' in m && !('profile' in c.members[i]) ? m.profile : null));
		const plaintexts = await Promise.all(c.members.map((m) => plaintext(m.encrypted_member_profile)));
		push(c.name, 'teamMemberProfiles', { plaintexts }, { profiles });
	}
	for (const c of inviteCases) {
		invalidateWorkspaceCaches();
		reply = { invites: c.invites, team: teamRecord() };
		const result = await service.loadTeamInvites(teamView());
		const plaintexts = await Promise.all(c.invites.map((i) => plaintext(i.encrypted_recipient_hint)));
		push(c.name, 'teamInviteHints', { plaintexts }, { recipient_emails: result.map((i) => i.recipientEmail) });
	}
	for (const c of billingCases) {
		invalidateWorkspaceCaches();
		reply = c.billing === undefined ? {} : { billing: c.billing };
		const team = teamView({ zeroBalance: c.zero ?? 25, encrypted: c.keyed ? teamRecord() : { team_id: 'team-nokey' } });
		let expected: unknown;
		try {
			const { raw: _raw, ...summary } = await service.loadTeamBilling(team);
			expected = summary;
		} catch (error) {
			expected = message(error);
		}
		const snapshot = (c.billing as Json | null | undefined)?.encrypted_balance;
		push(c.name, 'teamBilling', { billing: c.billing, zero_balance: team.zeroBalance }, expected,
			{ decrypt: { team_key: c.keyed, plaintext: await plaintext(snapshot) } });
	}
	for (const c of avatarCases) {
		requests = [];
		await service.loadTeamMemberAvatar(c.teamId, c.member as unknown as service.TeamMember);
		push(c.name, 'teamMemberAvatarPath', { team_id: c.teamId, member: c.member }, requests.length ? strip(requests[0].url) : null);
	}
	for (const c of uploadCases) {
		invalidateWorkspaceCaches();
		sessionStorage.clear();
		reply = { team: teamRecord() };
		upload = { status: c.status, text: c.reply };
		let expected: Json = { outcome: 'ok' };
		try {
			await service.uploadTeamProfileImage(teamView(), new File(['x'], 'avatar.png', { type: 'image/png' }));
		} catch (error) {
			const detail = (error as service.TeamApiError).detail;
			expected = detail === 'ACCOUNT_DELETED' && sessionStorage.getItem('account_deleted') ? { outcome: 'account_deleted' } : { outcome: 'error', detail };
		}
		let data: unknown = {};
		try { data = JSON.parse(c.reply); } catch { /* The service reads a non-JSON reply as {}. */ }
		push(c.name, 'teamProfileImageOutcome', { ok: c.status >= 200 && c.status < 300, data }, expected);
	}
	for (const c of inviteResultCases) {
		invalidateWorkspaceCaches();
		reply = { team: teamRecord(), ...(c.invite === undefined ? {} : { invite: c.invite }) };
		let expected: unknown;
		try {
			const result = c.delivery === 'email'
				? await service.createTeamEmailInvite(teamView(), 'a@example.org')
				: await service.createTeamLinkInvite(teamView());
			const { raw: _raw, inviteUrl: _url, ...facts } = result;
			expected = facts;
		} catch (error) {
			expected = message(error);
		}
		push(c.name, 'teamInviteResult', { invite: c.invite, invite_id: FRESH_ID, role: 'member', delivery: c.delivery }, expected);
	}
	for (const c of createdCases) {
		invalidateWorkspaceCaches();
		requests = [];
		reply = { approval_token: 'approval-token', ...(c.returned === undefined ? {} : { team: c.returned }) };
		const view = await service.createTeam({ name: 'Ops' });
		const record = view.encrypted as unknown as Json;
		const sent = sentBody(requests[requests.length - 1].init);
		push(c.name, 'teamCreatedRecord', { returned: c.returned ?? null, sent, team_id: FRESH_ID }, record,
			{ keys: Object.keys(record).filter((k) => record[k] !== undefined) });
	}
	return out;
}

async function bodies(): Promise<{ bodies: Json[]; contexts: Json[] }> {
	const out: Json[] = [];
	/** Runs one service call, recording its requests, its encryption calls and any refusal. */
	const capture = async (run: () => Promise<unknown>) => {
		requests = [];
		stub.encrypts = [];
		derived = [];
		opened = [];
		let error: unknown = null;
		try { await run(); } catch (e) { error = e; }
		return { sent: requests, encrypts: stub.encrypts, error };
	};
	const vector = (name: string, op: string, input: unknown, key: number, source: Json, sent: { url: string; init?: RequestInit } | null, encrypts: unknown[], error: unknown) => {
		const body = sent ? sentBody(sent.init) : null;
		const expected = sent && body
			? { path: strip(sent.url), method: sent.init?.method, body, ...keyOrder(body), encrypt_calls: encrypts }
			: message(error);
		const encryptInputs = Object.fromEntries(['profileImageMetadata', 'metadata'].map((m) => [m, JSON.stringify(source[m] ?? [])]));
		out.push({ name, op, input: json(input), encrypt_inputs: encryptInputs, keys: { team: key }, expected: json(expected) });
	};
	const mutationReply = { approval_token: 'approval-token', team: teamRecord(), invite: { invite_id: 'srv-1' }, status: 'active' };
	for (const c of bodyCases) {
		invalidateWorkspaceCaches();
		reply = mutationReply;
		upload = { status: 200, text: JSON.stringify({ status: 'ok' }) };
		const { sent, encrypts, error } = await capture(() => c.run(service));
		const picked = error ? null : (c.pick === 'first' ? sent[0] : sent[sent.length - 1]);
		vector(c.name, c.op, c.input(window.location.origin), c.key, c.source, picked, encrypts, error);
	}
	// Real sealed invite keys for the accept flow: one link invite, one email invite.
	reply = mutationReply;
	requests = [];
	const link = await service.createTeamLinkInvite(teamView());
	const linkBody = sentBody(requests[requests.length - 1].init);
	requests = [];
	const email = await service.createTeamEmailInvite(teamView(), 'Ana@Example.org');
	const emailBody = sentBody(requests[requests.length - 1].init);
	const secretOf = (url?: string) => String(url).split('#key=')[1];
	const sealed = (body: Json) => ({ encrypted_invite_team_key: body.encrypted_invite_team_key, invite_key_kdf_context: body.invite_key_kdf_context });
	const acceptCases: Array<{ name: string; email: string; secret: string; invite: unknown }> = [
		{ name: 'link invite opens with an empty recipient', email: 'bo@example.org', secret: secretOf(link.inviteUrl), invite: { kind: 'link', ...sealed(linkBody) } },
		{ name: 'email invite binds the verified recipient', email: ' ANA@example.org ', secret: secretOf(email.inviteUrl), invite: { hashed_recipient_email: 'h', ...sealed(emailBody) } },
		{ name: 'a context without origin uses the page origin', email: 'bo@example.org', secret: secretOf(link.inviteUrl), invite: { kind: 'link', encrypted_invite_team_key: linkBody.encrypted_invite_team_key, invite_key_kdf_context: { team_id: 'team-1' } } },
		{ name: 'a missing team id is refused', email: 'bo@example.org', secret: 'AAAA', invite: { encrypted_invite_team_key: 'x', invite_key_kdf_context: {} } },
		{ name: 'a missing sealed key is refused', email: 'bo@example.org', secret: 'AAAA', invite: { invite_key_kdf_context: { team_id: 'team-1' } } },
		{ name: 'a non-object context reads no team', email: 'bo@example.org', secret: 'AAAA', invite: { encrypted_invite_team_key: 'x', invite_key_kdf_context: 'team-1' } },
		{ name: 'a missing invite is a TypeError', email: 'bo@example.org', secret: 'AAAA', invite: undefined },
	];
	const contexts: Json[] = [];
	for (const c of acceptCases) {
		invalidateWorkspaceCaches();
		reply = { status: 'active', ...(c.invite === undefined ? {} : { invite: c.invite }) };
		const { sent, encrypts, error } = await capture(() => service.acceptTeamInviteFromFragment(FRESH_ID, c.secret, c.email));
		vector(`preview: ${c.name}`, 'teamInvitePreviewBody', { invite_id: FRESH_ID, verified_email: c.email }, 1, {}, sent[0], [], null);
		if (!error) {
			vector(`accept: ${c.name}`, 'teamInviteAcceptBody',
				{ invite_id: FRESH_ID, verified_email: c.email, timestamp: NOW_SECONDS, username: USERNAME }, 1, {}, sent[sent.length - 1], encrypts, null);
		}
		const pieces = derived.length ? infoPieces(derived[0]) : null;
		const expected = pieces
			? { team_id: pieces[2], origin: pieces[3], encrypted: base64(opened[0]), is_link: pieces[0] === '' }
			: message(error);
		contexts.push({ name: c.name, op: 'teamInviteKeyContext', input: json({ invite: c.invite, location_origin: window.location.origin }), expected });
	}
	return { bodies: out, contexts };
}

async function paths(): Promise<Json[]> {
	const out: Json[] = [];
	for (const c of pathCases) {
		invalidateWorkspaceCaches();
		requests = [];
		reply = { team: teamRecord(), members: [], invites: [], billing: { credits: 1 }, storage: {}, memories: [], security_policy: {} };
		await c.run(service);
		out.push({ name: c.name, op: 'teamPath', input: { route: c.route, ...c.ids }, expected: strip(requests[0].url) });
	}
	return out;
}

async function buildVectors(): Promise<Json> {
	const { bodies: bodyVectors, contexts } = await bodies();
	return { decisions: [...(await decisions()), ...contexts], paths: await paths(), bodies: bodyVectors };
}

describe('Team work parity vectors (TypeScript side)', () => {
	beforeEach(() => {
		vi.spyOn(Date, 'now').mockReturnValue(NOW_SECONDS * 1000);
		vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(FRESH_ID);
		vi.spyOn(globalThis.crypto, 'getRandomValues').mockImplementation(((array: ArrayBufferView) => {
			new Uint8Array(array.buffer).fill(7);
			return array;
		}) as typeof globalThis.crypto.getRandomValues);
		const subtle = globalThis.crypto.subtle;
		const realDerive = subtle.deriveBits.bind(subtle);
		const realDecrypt = subtle.decrypt.bind(subtle);
		vi.spyOn(subtle, 'deriveBits').mockImplementation(async (algorithm, key, length) => {
			derived.push(new Uint8Array((algorithm as HkdfParams).info as ArrayBuffer));
			return realDerive(algorithm, key, length);
		});
		vi.spyOn(subtle, 'decrypt').mockImplementation(async (algorithm, key, data) => {
			opened.push(new Uint8Array([...new Uint8Array((algorithm as AesGcmParams).iv as ArrayBuffer), ...new Uint8Array(data as ArrayBuffer)]));
			return realDecrypt(algorithm, key, data);
		});
		vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
			requests.push({ url: String(url), init });
			if (String(url).startsWith('https://upload.test')) return new Response(upload.text, { status: upload.status });
			return new Response(JSON.stringify(reply), { status: 200, headers: { 'content-type': 'application/json' } });
		});
	});

	// contract-test: supporting surface=gui.web assertions=teams.lifecycle.encrypted-profiled,teams.invites.fragment-key-web-flow,teams.billing.context-parity
	it('the flag-off teamService reproduces every committed vector', async () => {
		const fresh = json(await buildVectors());
		if (process.env.WORK_VECTORS_WRITE === '1') writeFileSync(VECTORS, `${JSON.stringify(fresh, null, 1)}\n`);
		let committed: unknown = null;
		try { committed = JSON.parse(readFileSync(VECTORS, 'utf8')); } catch { /* First generation: no committed file yet. */ }
		// Hosts that cannot write the file (isolated CI) get the regenerated document in the log.
		if (JSON.stringify(fresh) !== JSON.stringify(committed)) console.log(`WORK_VECTORS_FRESH_BEGIN\n${JSON.stringify(fresh, null, 1)}\nWORK_VECTORS_FRESH_END`);
		expect((fresh.decisions as unknown[]).length + (fresh.bodies as unknown[]).length).toBeGreaterThanOrEqual(60);
		expect(fresh).toEqual(committed);
	});
});
