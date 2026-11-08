// Cases for the Team `work` parity vectors (workTeamVectors.test.ts).
// Each case drives the real flag-off teamService (crypto, fetch and key lookups
// stubbed by the test) and states the input the flag-on page sends to the Rust
// op; packages/openmates-rust/src/web_work/teams_tests.rs replays them.
// Ciphertexts are `sealed:<plaintext>`; the stub seals with `sealed:<key byte>:`.
// spec: specifications/features/teams#teams.lifecycle.encrypted-profiled
import type * as Teams from '../../../teamService';

type TeamService = typeof Teams;
type Json = Record<string, unknown>;

export const FRESH_ID = '00000000-0000-4000-8000-000000000002';
export const NOW_SECONDS = 1_700_000_000;
export const USERNAME = '  Mira  ';

export const seal = (value: unknown) => `sealed:${typeof value === 'string' ? value : JSON.stringify(value)}`;

export function teamRecord(over: Json = {}): Json {
	return {
		team_id: 'team-1', encrypted_name: seal('Design'), encrypted_description: seal('Product design'),
		encrypted_profile_image_metadata: seal({ mode: 'generated', icon_name: 'design', version: 1 }),
		encrypted_team_key: 'wrapped-team', encrypted_zero_balance: seal('25'), role: 'admin', status: 'active',
		created_at: 10, updated_at: 20, ...over,
	};
}

/** A view the mutating calls receive (only the members the service reads). */
export function teamView(over: Json = {}): Teams.TeamViewModel {
	return { team_id: 'team-1', zeroBalance: 25, encrypted: teamRecord(), ...over } as unknown as Teams.TeamViewModel;
}

/** Team records projected by `teamView` (through getTeam). */
export const viewCases: Array<{ name: string; record: Json }> = [
	{ name: 'full record with metadata, balance and policy override', record: teamRecord({ security_policy: { require_strong_auth: true, allowed_email_domains: ['example.org'], extra_flag: 1 } }) },
	{ name: 'minimal record takes every default', record: { team_id: 'team-2', encrypted_team_key: 'wrapped-team' } },
	{ name: 'undecryptable name and empty members read as defaults', record: teamRecord({ encrypted_name: 'garbage', encrypted_description: '', encrypted_zero_balance: null, role: null }) },
	{ name: 'profile metadata that is not an object keeps the default', record: teamRecord({ encrypted_profile_image_metadata: seal([1, 2]) }) },
	{ name: 'profile metadata that is not JSON keeps the default', record: teamRecord({ encrypted_profile_image_metadata: seal('{oops') }) },
	{ name: 'zero balance parses like parseInt', record: teamRecord({ encrypted_zero_balance: seal('  -12.9credits') }) },
	{ name: 'a non-numeric zero balance is zero', record: teamRecord({ encrypted_zero_balance: seal('abc') }) },
	{ name: 'a huge zero balance is not finite and reads zero', record: teamRecord({ encrypted_zero_balance: seal('9'.repeat(400)) }) },
	{ name: 'a null security policy keeps the defaults', record: teamRecord({ security_policy: null }) },
];

const member = (over: Json) => ({ user_id: 'u-1', role: 'member', status: 'active', ...over });

/** Member lists parsed by `teamMemberProfiles` (through loadTeamMembers). */
export const memberCases: Array<{ name: string; members: Json[] }> = [
	{ name: 'profiles with and without avatars', members: [
		member({ encrypted_member_profile: seal({ display_name: 'Ana', avatar: { mode: 'generated', icon_name: 'x', background_color: '#000000' } }) }),
		member({ user_id: 'u-2', encrypted_member_profile: seal({ display_name: 'Ben' }) }),
	] },
	{ name: 'missing, blank, non-string and malformed profiles keep the member', members: [
		member({}), member({ encrypted_member_profile: seal({ display_name: '   ' }) }),
		member({ encrypted_member_profile: seal({ display_name: 7 }) }), member({ encrypted_member_profile: seal('not json') }),
		member({ encrypted_member_profile: 'garbage' }), member({ encrypted_member_profile: seal('null') }), member({ encrypted_member_profile: seal([1]) }),
	] },
];

/** Invite lists read by `teamInviteHints` (through loadTeamInvites). */
export const inviteCases: Array<{ name: string; invites: Json[] }> = [
	{ name: 'recipient hints of every shape', invites: [
		{ invite_id: 'i-1', role: 'member', status: 'pending', encrypted_recipient_hint: seal({ recipient_email: 'a@example.org', role: 'member' }) },
		{ invite_id: 'i-2', role: 'viewer', status: 'pending' },
		{ invite_id: 'i-3', role: 'admin', status: 'pending', encrypted_recipient_hint: 'garbage' },
		{ invite_id: 'i-4', role: 'member', status: 'pending', encrypted_recipient_hint: seal({ recipient_email: 42 }) },
		{ invite_id: 'i-5', role: 'member', status: 'pending', encrypted_recipient_hint: seal({ recipient_email: null }) },
		{ invite_id: 'i-6', role: 'member', status: 'pending', encrypted_recipient_hint: seal('null') },
		{ invite_id: 'i-7', role: 'member', status: 'pending', encrypted_recipient_hint: seal({ recipient_email: ['x', null, 'y'] }) },
		{ invite_id: 'i-8', role: 'member', status: 'pending', encrypted_recipient_hint: seal('{bad') },
	] },
];

/** Wallet replies decided by `teamBilling` (through loadTeamBilling); `keyed` says whether the Team key opens. */
export const billingCases: Array<{ name: string; billing: unknown; keyed: boolean; zero?: number }> = [
	{ name: 'versioned numeric balance wins over the snapshot', billing: { balance_credits: 4, version: 3, encrypted_balance: seal('99') }, keyed: true },
	{ name: 'versioned negative balance is refused', billing: { balance_credits: -1, version: 3 }, keyed: true },
	{ name: 'versioned string balance is refused', billing: { balance_credits: '4', version: 3 }, keyed: true },
	{ name: 'versioned fractional balance is refused', billing: { balance_credits: 4.5, version: 2 }, keyed: true },
	{ name: 'legacy credits field', billing: { credits: 12 }, keyed: true },
	{ name: 'legacy string balance parses like parseInt', billing: { balance: ' 12abc' }, keyed: true },
	{ name: 'a fractional version is not authoritative', billing: { balance_credits: 7.5, version: 1.5 }, keyed: true },
	{ name: 'encrypted snapshot opens with the Team key', billing: { encrypted_balance: seal('31') }, keyed: true },
	{ name: 'an undecryptable snapshot reads zero', billing: { encrypted_balance: 'garbage', balance: -3 }, keyed: true },
	{ name: 'a snapshot without a Team key falls back to the zero balance', billing: { encrypted_balance: seal('31') }, keyed: false },
	{ name: 'nothing usable falls back to the zero balance', billing: { balance: 'n/a', encrypted_balance: '' }, keyed: true, zero: 8 },
	{ name: 'array balances stringify like String()', billing: { balance_credits: null, credits: [5] }, keyed: true },
	{ name: 'a missing billing member is a TypeError', billing: undefined, keyed: true },
	{ name: 'a null billing member is a TypeError', billing: null, keyed: true },
];

/** Team GET/DELETE/POST paths (`teamPath`), driven through the service call that uses them. */
export const pathCases: Array<{ name: string; route: string; ids: Json; run: (s: TeamService) => Promise<unknown> }> = [
	{ name: 'team item path encodes the id', route: 'team', ids: { team_id: 'team/1 a' }, run: (s) => s.getTeam('team/1 a') },
	{ name: 'delete uses the item path', route: 'team', ids: { team_id: 'team?x' }, run: (s) => s.deleteTeam('team?x') },
	{ name: 'members path', route: 'members', ids: { team_id: 'team-1' }, run: (s) => s.loadTeamMembers('team-1') },
	{ name: 'invites path', route: 'invites', ids: { team_id: 'team-1' }, run: (s) => s.loadTeamInvites(teamView()) },
	{ name: 'invite revoke path', route: 'invite_revoke', ids: { team_id: 'team-1', invite_id: 'inv #1' }, run: (s) => s.revokeTeamInvite('team-1', 'inv #1') },
	{ name: 'security path', route: 'security', ids: { team_id: 'team-1' }, run: (s) => s.updateTeamSecurity('team-1', { restrict_email_domains: false, allowed_email_domains: [], require_invite_link_approval: true, require_strong_auth: false }) },
	{ name: 'billing path', route: 'billing', ids: { team_id: 'team-1' }, run: (s) => s.loadTeamBilling(teamView()) },
	{ name: 'storage path', route: 'storage', ids: { team_id: 'team-1' }, run: (s) => s.loadTeamStorage('team-1') },
	{ name: 'storage notice first page', route: 'storage_notice', ids: { team_id: 'team-1' }, run: (s) => s.loadTeamStorageNotice('team-1') },
	{ name: 'storage notice after a unit id', route: 'storage_notice', ids: { team_id: 'team-1', after_unit_id: 'unit a&b' }, run: (s) => s.loadTeamStorageNotice('team-1', 'unit a&b') },
	{ name: 'memories path', route: 'memories', ids: { team_id: 'team é' }, run: (s) => s.loadTeamMemoryCount('team é') },
];

/** `loadTeamMemberAvatar` guard cases (`teamMemberAvatarPath`). */
export const avatarCases: Array<{ name: string; teamId: string; member: Json }> = [
	{ name: 'own avatar route is fetched', teamId: 'team-1', member: member({ profile_image_url: '/v1/teams/team-1/members/u-1/profile-image' }) },
	{ name: 'a foreign route is refused', teamId: 'team-1', member: member({ profile_image_url: 'https://evil.example/x.png' }) },
	{ name: 'no user id is refused', teamId: 'team-1', member: { role: 'member', status: 'active', profile_image_url: '/v1/teams/team-1/members/undefined/profile-image' } },
];

/** Upload replies mapped by `teamProfileImageOutcome` (through uploadTeamProfileImage). */
export const uploadCases: Array<{ name: string; status: number; reply: string }> = [
	{ name: 'accepted upload', status: 200, reply: JSON.stringify({ status: 'ok' }) },
	{ name: 'rejected image', status: 200, reply: JSON.stringify({ status: 'rejected', reject_count: 1 }) },
	{ name: 'third rejection warns', status: 200, reply: JSON.stringify({ status: 'rejected', reject_count: 3 }) },
	{ name: 'account deleted locks out', status: 403, reply: JSON.stringify({ status: 'account_deleted' }) },
	{ name: 'ok status on a failed response', status: 500, reply: JSON.stringify({ status: 'ok' }) },
	{ name: 'server detail is kept', status: 413, reply: JSON.stringify({ detail: 'FILE_TOO_LARGE' }) },
	{ name: 'a non-JSON reply fails generically', status: 502, reply: 'Bad gateway' },
];

/** Invite replies mapped by `teamInviteResult`. */
export const inviteResultCases: Array<{ name: string; delivery: 'email' | 'link'; invite: unknown }> = [
	{ name: 'email invite with a full reply', delivery: 'email', invite: { invite_id: 'srv-1', role: 'admin', status: 'sent', delivery_status: 'queued' } },
	{ name: 'email invite with a sparse reply', delivery: 'email', invite: { role: null } },
	{ name: 'link invite with a full reply', delivery: 'link', invite: { invite_id: 77, role: 'admin', status: 'active', delivery_status: 'queued' } },
	{ name: 'link invite with a sparse reply', delivery: 'link', invite: {} },
	{ name: 'a missing invite member is a TypeError', delivery: 'link', invite: undefined },
];

/** Created Teams (`teamCreatedRecord` over the server reply). */
export const createdCases: Array<{ name: string; returned: unknown }> = [
	{ name: 'a sparse reply keeps the submitted payload', returned: { team_id: 'srv-team' } },
	{ name: 'a missing reply keeps everything local', returned: undefined },
	{ name: 'a full reply wins over the payload', returned: teamRecord({ team_id: 'srv-team', role: 'member', encrypted_team_key: 'srv-wrapped' }) },
];

/** One mutation: the service call, the Rust op input and which request is the body under test. */
export interface BodyCase {
	name: string;
	op: string;
	pick?: 'first' | 'last';
	key: number;
	source: Json;
	run: (s: TeamService) => Promise<unknown>;
	input: (origin: string) => Json;
}

const at = { timestamp: NOW_SECONDS };
const metadata = { version: 2, mode: 'generated', icon_name: 'rocket', background_color: '#112233', icon_color: '#ffffff' };

export const bodyCases: BodyCase[] = [
	{ name: 'name approval trims and lowercases', op: 'teamNameApprovalBody', key: 1, source: {},
		run: (s) => s.approveTeamName('  Ops TEAM '), input: () => ({ name: '  Ops TEAM ' }) },
	{ name: 'create with description and custom metadata', op: 'teamCreateBody', key: 9, source: { name: ' Design ', description: 'Desc', profileImageMetadata: metadata },
		run: (s) => s.createTeam({ name: ' Design ', description: 'Desc', profileImageMetadata: metadata }),
		input: () => ({ input: { name: ' Design ', description: 'Desc', profileImageMetadata: metadata }, team_id: FRESH_ID, ...at, username: USERNAME }) },
	{ name: 'create with defaults', op: 'teamCreateBody', key: 9, source: { name: 'Ops', description: '' },
		run: (s) => s.createTeam({ name: 'Ops', description: '' }),
		input: () => ({ input: { name: 'Ops', description: '' }, team_id: FRESH_ID, ...at, username: USERNAME }) },
	{ name: 'create refuses a blank name', op: 'teamCreateBody', key: 9, source: { name: '   ' },
		run: (s) => s.createTeam({ name: '   ' }), input: () => ({ input: { name: '   ' }, team_id: FRESH_ID, ...at, username: USERNAME }) },
	{ name: 'rename seals the trimmed name', op: 'teamNameUpdateBody', key: 1, source: {},
		run: (s) => s.updateTeamName(teamView(), ' New name '), input: () => ({ team_id: 'team-1', name: ' New name ', ...at }) },
	{ name: 'profile metadata update', op: 'teamProfileMetadataBody', key: 1, source: { metadata },
		run: (s) => s.updateTeamProfileMetadata(teamView(), metadata), input: () => ({ team_id: 'team-1', ...at }) },
	{ name: 'profile image form fields', op: 'teamProfileImageForm', key: 1, pick: 'first', source: {},
		run: (s) => s.uploadTeamProfileImage(teamView(), new File(['x'], 'avatar.png', { type: 'image/png' })), input: () => ({ team_id: 'team-1', ...at }) },
	{ name: 'member role change', op: 'teamMemberRoleBody', key: 1, source: {},
		run: (s) => s.updateTeamMemberRole('team 1', 'user/2', 'admin'), input: () => ({ team_id: 'team 1', user_id: 'user/2', role: 'admin', ...at }) },
	{ name: 'member removal', op: 'teamMemberRemoveBody', key: 1, source: {},
		run: (s) => s.removeTeamMember('team-1', 'u-2'), input: () => ({ team_id: 'team-1', user_id: 'u-2', ...at }) },
	{ name: 'decline lowercases the verified email', op: 'teamInviteDeclineBody', key: 1, source: {},
		run: (s) => s.declineTeamInvite('inv-1', ' Ana@Example.ORG '), input: () => ({ invite_id: 'inv-1', verified_email: ' Ana@Example.ORG ', ...at }) },
	{ name: 'email invite payload', op: 'teamEmailInviteBody', key: 1, source: {},
		run: (s) => s.createTeamEmailInvite(teamView(), ' Ana@Example.ORG ', 'admin'),
		input: (origin) => ({ team_id: 'team-1', email: ' Ana@Example.ORG ', role: 'admin', invite_id: FRESH_ID, origin, ...at }) },
	{ name: 'email invite refuses a blank email', op: 'teamEmailInviteBody', key: 1, source: {},
		run: (s) => s.createTeamEmailInvite(teamView(), '   '), input: (origin) => ({ team_id: 'team-1', email: '   ', role: 'member', invite_id: FRESH_ID, origin, ...at }) },
	{ name: 'link invite payload', op: 'teamLinkInviteBody', key: 1, source: {},
		run: (s) => s.createTeamLinkInvite(teamView()), input: (origin) => ({ team_id: 'team-1', role: 'member', invite_id: FRESH_ID, origin, ...at }) },
];
