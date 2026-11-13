// Canonical embed sender parity vectors (embeds-3 lane, sender slice).
// The committed packages/openmates-rust/src/embed_read/sender_ts_vectors.json is
// regenerated here from the real flag-off decisions of embedSenderPolicy.ts (the
// functions embedSenders.ts calls inline); sender_tests.rs replays it through the
// Rust `embed_read::run_json`. Regenerate:
//   EMBED_SENDER_VECTORS_WRITE=1 npx vitest run src/services/rustCore/__tests__/embedSenderVectors.test.ts
// spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
	decideEmbedSender, identityNeedsContentDigest, type EmbedSenderDecisions, type EmbedSenderOp,
	type SenderCanonicalRevision, type SenderHeadFacts
} from '../../embedSenderPolicy';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/embed_read/sender_ts_vectors.json');
const HEX_A = 'a'.repeat(64);
const HEX_B = 'b'.repeat(64);
const E = 'e';
const P = 'p';
type Vector = { name: string; op: EmbedSenderOp; input: unknown; expected: unknown };

const json = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
const vectors: Vector[] = [];
function add<O extends EmbedSenderOp>(name: string, op: O, input: EmbedSenderDecisions[O]['input']): void {
	const document = json(input);
	vectors.push({ name, op, input: document, expected: json(decideEmbedSender(op, document)) });
}

function availabilityRequests(): void {
	for (const team_id of [null, '', 't 1/ü']) {
		for (const parent_embed_id of [null, '', P]) {
			add(`req ${team_id} ${parent_embed_id}`, 'senderAvailabilityRequest',
				{ chat_id: "c/ä b?&#'", team_id, embed_id: E, parent_embed_id, version: parent_embed_id ? 3 : 1 });
		}
	}
}

function availabilityPlans(): void {
	const revision = (version: unknown, sha: unknown = HEX_A, write_state: unknown = 'mutable') =>
		({ version, ciphertext_sha256: sha, write_state });
	const revisions: Array<[string, unknown]> = [
		['none', undefined], ['num', 5], ['v1', revision(1)], ['v1i', revision(1, HEX_A, 'immutable')],
		['v2', revision(2)], ['v3', revision(3)], ['v0', revision(1.5)], ['upper', revision(1, HEX_A.toUpperCase())],
		['short', revision(1, 'abc')], ['state', revision(1, HEX_A, 'sealed')]
	];
	const heads: Array<[string, unknown]> = [];
	for (const state of ['missing', 'ready', 'pending']) {
		for (const [label, canonical_revision] of revisions) heads.push([`${state}/${label}`, { embed_id: E, state, canonical_revision }]);
	}
	heads.push(['nostate/v1', { embed_id: E, canonical_revision: revision(1) }], ['ready/null', { embed_id: E, state: 'ready', canonical_revision: null }]);
	const odd: Array<[string, unknown, boolean]> = [
		['null-reply', null, false], ['empty', {}, false], ['string-results', { results: 'x' }, false], ['no-results', { results: [] }, false],
		['null-entry', { results: [null] }, false], ['other-id', { results: [{ embed_id: 'other', state: 'ready' }] }, false],
		['string-entry', { results: ['x'] }, false], ['too-many', { results: [{ embed_id: E }, { embed_id: P }] }, false],
		['parent-missing-second', { results: [{ embed_id: E, state: 'missing' }] }, true],
		['parent-null-second', { results: [{ embed_id: E, state: 'missing' }, null] }, true],
		['parent-null-first', { results: [null, { embed_id: P, state: 'ready' }] }, true],
		['parent-wrong-first', { results: [{ embed_id: 'x' }, null] }, true],
		['parent-wrong-id', { results: [{ embed_id: E, state: 'missing' }, { embed_id: 'x', state: 'ready' }] }, true],
		['parent-pending', { results: [{ embed_id: E, state: 'missing' }, { embed_id: P, state: 'pending' }] }, true]
	];
	for (const [requested_version, read_only] of [[1, false], [2, true]] as const) {
		for (const [label, head] of heads) {
			add(`plan ${label} r${requested_version}${read_only ? 'ro' : ''}`, 'senderAvailabilityPlan',
				{ embed_id: E, parent_embed_id: null, requested_version, read_only, reply: { results: [head] } });
		}
	}
	for (const [label, head] of heads.filter((_, index) => index % 4 === 0)) {
		add(`plan parent ${label}`, 'senderAvailabilityPlan', {
			embed_id: E, parent_embed_id: P, requested_version: 1, read_only: false,
			reply: { results: [head, { embed_id: P, state: 'ready' }] }
		});
	}
	for (const [label, reply, parent] of odd) {
		add(`plan ${label}`, 'senderAvailabilityPlan',
			{ embed_id: E, parent_embed_id: parent ? P : null, requested_version: 1, read_only: false, reply });
	}
}

const HEAD: SenderHeadFacts & { embed_ids?: string[] } = {
	embed_id: E, hashed_chat_id: 'hc', hashed_user_id: 'hu', hashed_message_id: 'hm', version_number: 2, status: 'finished',
	app_id: 'web', skill_id: 'search', hashed_task_id: 'ht', is_private: false, is_shared: true, embed_ids: ['c1', 'c2']
};
const EMBED: Record<string, unknown> = {
	embed_id: E, hashed_chat_id: 'hc', hashed_user_id: 'hu', hashed_message_id: 'hm', version_number: 2, status: 'finished',
	app_id: 'web', skill_id: 'search', hashed_task_id: 'ht', is_private: false, is_shared: true, embed_ids: ['c1', 'c2'],
	encrypted_content: 'ct-1', encrypted_type: 'ty-1'
};

/** The identity document exactly as embedSenders.ts readEquivalentCanonicalHead builds it. */
function identityInput(head: typeof HEAD, page: unknown, historical: boolean, revision: SenderCanonicalRevision | null) {
	const embed = (page as { embed?: Record<string, unknown> } | null)?.embed;
	const needs = identityNeedsContentDigest(page, revision);
	return {
		head: Object.fromEntries(Object.entries(head).filter(([key]) => key !== 'embed_ids')) as SenderHeadFacts,
		page, historical, revision,
		content_sha256: needs ? ((embed as Record<string, unknown>).encrypted_content === 'ct-1' ? HEX_A : HEX_B) : null,
		head_embed_ids_json: head.embed_ids !== undefined ? JSON.stringify(head.embed_ids ?? []) : null,
		embed_ids_json: typeof embed === 'object' && embed !== null ? JSON.stringify(embed.embed_ids ?? []) : null
	};
}

function canonicalIdentities(): void {
	const keys = [{ hashed_embed_id: 'hs' }];
	const page = (embed: unknown, extra: Record<string, unknown> = {}) => ({ embed, embed_keys: keys, ...extra });
	const embedVariants: Array<[string, unknown]> = [
		['same', EMBED], ['missing', undefined], ['null', null], ['string', 'x'], ['array', []],
		['v-null', { ...EMBED, version_number: null }], ['v-missing', { ...EMBED, version_number: undefined }],
		['v1', { ...EMBED, version_number: 1 }], ['v3', { ...EMBED, version_number: 3 }], ['v0', { ...EMBED, version_number: 0 }],
		['v-str', { ...EMBED, version_number: '2' }], ['v-frac', { ...EMBED, version_number: 2.5 }],
		['no-content', { ...EMBED, encrypted_content: undefined }], ['num-type', { ...EMBED, encrypted_type: 7 }],
		['other-content', { ...EMBED, encrypted_content: 'ct-2' }], ['parent-null', { ...EMBED, parent_embed_id: null }],
		['parent-set', { ...EMBED, parent_embed_id: P }], ['task-null', { ...EMBED, hashed_task_id: null }],
		['ids-reordered', { ...EMBED, embed_ids: ['c2', 'c1'] }], ['ids-missing', { ...EMBED, embed_ids: undefined }],
		['status-object', { ...EMBED, status: {} }]
	];
	for (const key of ['embed_id', 'hashed_chat_id', 'hashed_user_id', 'hashed_message_id', 'status', 'app_id', 'skill_id',
		'hashed_task_id', 'is_private', 'is_shared']) {
		embedVariants.push([`diff-${key}`, { ...EMBED, [key]: 'other' }], [`absent-${key}`, { ...EMBED, [key]: undefined }]);
	}
	const headVariants: Array<[string, typeof HEAD]> = [
		['head', HEAD], ['head-v1', { ...HEAD, version_number: 1 }], ['head-v-none', { ...HEAD, version_number: undefined }],
		['head-child', { ...HEAD, parent_embed_id: P }], ['head-lean', { embed_id: E, hashed_chat_id: 'hc', hashed_user_id: 'hu', hashed_message_id: 'hm', version_number: 2, status: 'finished' }],
		['head-null-app', { ...HEAD, app_id: null }], ['head-ids-empty', { ...HEAD, embed_ids: [] }]
	];
	const revisionVariants: Array<[string, SenderCanonicalRevision | null]> = [
		['no-rev', null], ['rev2', { version: 2, ciphertext_sha256: HEX_A, write_state: 'mutable' }],
		['rev2-b', { version: 2, ciphertext_sha256: HEX_B, write_state: 'immutable' }], ['rev3', { version: 3, ciphertext_sha256: HEX_A, write_state: 'mutable' }]
	];
	for (const [el, embed] of embedVariants) {
		add(`id ${el}`, 'senderCanonicalIdentity', identityInput(HEAD, page(embed), false, null));
	}
	// Historical reads compare versions only (canonical newer than the queued head).
	for (const [el, embed] of embedVariants.filter(([label]) => ['same', 'v1', 'v3', 'v-null', 'diff-status', 'ids-reordered'].includes(label))) {
		add(`id hist ${el}`, 'senderCanonicalIdentity', identityInput(HEAD, page(embed), true, null));
	}
	for (const [rl, revision] of revisionVariants.slice(1)) {
		for (const [el, embed] of embedVariants.filter(([label]) => ['same', 'null', 'other-content'].includes(label))) {
			add(`id ${rl} ${el}`, 'senderCanonicalIdentity', identityInput(HEAD, page(embed), false, revision));
		}
	}
	for (const [hl, head] of headVariants.slice(1)) {
		for (const [el, embed] of embedVariants.filter(([label]) => ['same', 'parent-set', 'diff-skill_id'].includes(label))) {
			add(`id ${hl} ${el}`, 'senderCanonicalIdentity', identityInput(head, page(embed), false, null));
		}
	}
	const pages: Array<[string, unknown]> = [
		['null-page', null], ['string-page', 'x'], ['has-more', page(EMBED, { embed_keys_has_more_after: true })],
		['oversized', page(EMBED, { oversized_embed_key_id: 'k' })], ['oversized-null', page(EMBED, { oversized_embed_key_id: null })],
		['no-keys', { embed: EMBED }], ['keys-object', page(EMBED, { embed_keys: {} })],
		['keys-128', page(EMBED, { embed_keys: Array.from({ length: 128 }, () => ({})) })],
		['keys-129', page(EMBED, { embed_keys: Array.from({ length: 129 }, () => ({})) })]
	];
	for (const [label, value] of pages) {
		add(`identity page ${label}`, 'senderCanonicalIdentity', identityInput(HEAD, value, false, null));
	}
	// A revision whose digest is null against a missing digest: `===` keeps null distinct from absence.
	add('identity null digest', 'senderCanonicalIdentity', {
		...identityInput(HEAD, page({ ...EMBED, version_number: 2 }), false, null),
		revision: { version: 2, ciphertext_sha256: null } as unknown as SenderCanonicalRevision
	});
}

function historyPages(): void {
	const pages: Array<[string, unknown]> = [
		['ok', { embed_id: E, version_number: 2, rows: [{ version_number: 1 }, { version_number: 2 }] }],
		['null', null], ['string', 'x'], ['other-id', { embed_id: 'x', version_number: 2, rows: [{ version_number: 2 }] }],
		['other-version', { embed_id: E, version_number: 3, rows: [{ version_number: 2 }] }],
		['no-rows', { embed_id: E, version_number: 2 }], ['empty-rows', { embed_id: E, version_number: 2, rows: [] }],
		['last-null', { embed_id: E, version_number: 2, rows: [{ version_number: 2 }, null] }],
		['last-other', { embed_id: E, version_number: 2, rows: [{ version_number: 2 }, { version_number: 1 }] }],
		['rows-object', { embed_id: E, version_number: 2, rows: {} }], ['string-version', { embed_id: E, version_number: '2', rows: [{ version_number: 2 }] }]
	];
	for (const [label, page] of pages) add(`history ${label}`, 'senderHistoryPage', { embed_id: E, version: 2, page });
}

function wrapperRows(): void {
	const base = { hashed_embed_id: 'hs', hashed_user_id: 'hu', encrypted_embed_key: 'wrapped' };
	const rows: unknown[] = [
		{ ...base, key_type: 'master' }, { ...base, key_type: 'master', hashed_chat_id: null }, { ...base, key_type: 'master', hashed_chat_id: 'hc' },
		{ ...base, key_type: 'chat', hashed_chat_id: 'hc' }, { ...base, key_type: 'chat', hashed_chat_id: 'other' }, { ...base, key_type: 'chat' },
		{ ...base, key_type: 'project' }, { ...base }, { ...base, key_type: 'master', hashed_embed_id: 'other' },
		{ ...base, key_type: 'chat', hashed_chat_id: 'hc', hashed_user_id: 'other' }, { ...base, key_type: 'master', encrypted_embed_key: 3 },
		{ ...base, key_type: 'master', encrypted_embed_key: undefined }, null, 'x', 7, [],
		...['hashed_project_id', 'hashed_plan_id', 'hashed_team_id', 'team_key_epoch'].flatMap((field) => [
			{ ...base, key_type: 'master', [field]: 'p' }, { ...base, key_type: 'chat', hashed_chat_id: 'hc', [field]: null },
			{ ...base, key_type: 'chat', hashed_chat_id: 'hc', [field]: 0 }
		])
	];
	for (const mode of ['canonical', 'queued'] as const) {
		for (const [label, scope] of [['scoped', { hashed_user_id: 'hu', hashed_chat_id: 'hc' }], ['unscoped', {}]] as const) {
			add(`wrappers ${mode} ${label}`, 'senderWrapperRows', { mode, rows, hashed_subject: 'hs', ...scope } as never);
		}
	}
}

function missingKeys(): void {
	const typeSets: unknown[][] = [[], ['master'], ['master', 'chat'], [null, 'chat'], ['team', 7]];
	const flows = [[true, 1, null], [true, 2, null], [true, 1, 3], [true, 1, 1], [false, 1, null]] as const;
	for (const key_types of typeSets) {
		for (const verified_key_types of [null, ['master'], ['master', 'chat']]) {
			for (const [allow_wrapper_writes, requested_version, canonical_version] of flows) {
				if (!verified_key_types && canonical_version !== null) continue;
				add(`keys ${JSON.stringify(key_types)} ${JSON.stringify(verified_key_types)} ${allow_wrapper_writes} ${requested_version} ${canonical_version}`,
					'senderMissingKeys', { key_types, verified_key_types, allow_wrapper_writes, requested_version, canonical_version });
			}
		}
	}
}

function receipts(): void {
	const heads: unknown[] = [{ embed_id: E, canonical_digest: HEX_A }, { embed_id: E, canonical_digest: HEX_B }, { embed_id: 'x', canonical_digest: HEX_A }, {}];
	heads.forEach((receipt, i) => add(`receipt head ${i}`, 'senderReceipt', { kind: 'head', receipt: receipt as Record<string, unknown>, embed_id: E, expected_digest: HEX_A }));
	const keys: unknown[] = [{ failed_count: 0, created_count: 2 }, { failed_count: 1, created_count: 2 }, { failed_count: 0, created_count: 1 },
		{ failed_count: '0', created_count: 2 }, { created_count: 2 }, { failed_count: 0, created_count: '2' }];
	keys.forEach((receipt, i) => add(`receipt keys ${i}`, 'senderReceipt', { kind: 'keys', receipt: receipt as Record<string, unknown>, count: 2 }));
	const ok = { embed_id: E, version_number: 3, canonical_digest: HEX_A, canonical_source: 'version_row' };
	const diffs: unknown[] = [ok, { ...ok, version_number: 2 }, { ...ok, canonical_source: 'head' }, { ...ok, canonical_digest: HEX_B }, { ...ok, embed_id: 'x' }, {}];
	diffs.forEach((receipt, i) => add(`receipt diff ${i}`, 'senderReceipt',
		{ kind: 'diff', receipt: receipt as Record<string, unknown>, embed_id: E, version_number: 3, expected_digest: HEX_A }));
}

function failures(): void {
	const codes = [null, 'embed_write_denied', 'embed_revision_conflict', 'embed_identity_conflict', 'other'];
	const reasons = [null, 'canonical_precondition_mismatch', 'acknowledged_embed_revision_immutable', 'quota'];
	for (const code of codes) {
		for (const reason of reasons) add(`failure rejected ${code} ${reason}`, 'senderFailure', { kind: 'rejected', code, reason });
	}
	for (const code of ['embed_wrapper_conflict', 'embed_version_conflict']) add(`failure conflict ${code}`, 'senderFailure', { kind: 'conflict', code, reason: null });
	add('failure other', 'senderFailure', { kind: 'other', code: null, reason: null });
}

function buildVectors(): Vector[] {
	vectors.length = 0;
	availabilityRequests();
	availabilityPlans();
	canonicalIdentities();
	historyPages();
	wrapperRows();
	missingKeys();
	receipts();
	failures();
	return [...vectors];
}

describe('canonical embed sender parity vectors (TypeScript side)', () => {
	// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters
	it('the flag-off sender decisions reproduce every committed vector', () => {
		const fresh = { generator: 'frontend/packages/ui/src/services/rustCore/__tests__/embedSenderVectors.test.ts', vectors: buildVectors() };
		if (process.env.EMBED_SENDER_VECTORS_WRITE === '1') writeFileSync(VECTORS, `${JSON.stringify(fresh, null, 1)}\n`);
		let committed: unknown = null;
		try { committed = JSON.parse(readFileSync(VECTORS, 'utf8')); } catch { /* First generation: no committed file yet. */ }
		// Hosts that cannot write the file (isolated CI) get the regenerated document in the log.
		if (JSON.stringify(fresh) !== JSON.stringify(committed)) {
			console.log(`EMBED_SENDER_VECTORS_FRESH_BEGIN\n${JSON.stringify(fresh)}\nEMBED_SENDER_VECTORS_FRESH_END`);
		}
		expect(fresh.vectors.length).toBeGreaterThan(250);
		expect(new Set(fresh.vectors.map((v) => v.op)).size).toBe(8);
		expect(fresh).toEqual(committed);
	});
});
