// Connected-account ops on the shared Rust core Worker `settings` unit: the real
// router and installer over a scripted binding (the Rust decisions themselves
// are proven by web_connected_accounts_tests.rs over the TS vectors) and the
// flag-on page adapter following those decisions with no TypeScript fallback.
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { createSharedCoreClient, registerSharedRustCore, type SharedWorkerEndpoint } from '../host/sharedCoreRegistry';
import { createSharedWorkerRouter } from '../host/sharedWorkerProtocol';
import { UnitRefusal } from '../host/unitPort';
import { createConnectedAccountsHandlers } from '../connectedAccounts/connectedAccountsUnit';
import { installSettingsUnit } from '../settings/settingsUnit';
import { rustSettingsStats } from '../settings/settingsClient';
import {
	rustBuildConnectedAccountSendContext,
	rustMergeTurnTokenRefs,
	rustSummarizeConnectedAccountRows
} from '../connectedAccounts/rustConnectedAccounts';
import type { ConnectedAccountsBinding } from '../connectedAccounts/connectedAccountsProtocol';
import type { SettingsBinding } from '../settings/settingsProtocol';
import type { EncryptedConnectedAccountRow } from '../../connectedAccountStorageService';

const calls: string[] = [];
let next: Record<string, unknown> = {};
const unused = (): never => { throw new Error('settings export not used by this test'); };
const settingsExports: SettingsBinding = {
	settings_category_plan: unused,
	settings_request_answered: unused,
	settings_build_request_message: unused,
	settings_plan_selected_keys: unused,
	settings_select_entry_ids: unused,
	settings_response_categories: unused,
	settings_confirm_outcome: unused,
	settings_response_content: unused,
	settings_plan_privacy_entry: unused
};
const binding: SettingsBinding & ConnectedAccountsBinding = {
	...settingsExports,
	connected_accounts_select_send_rows: (_rows, ids) => (calls.push(`select ${ids}`), JSON.stringify(next.select)),
	connected_accounts_send_context_plan: (input) => (calls.push(`plan ${input}`), JSON.stringify(next.plan)),
	connected_accounts_summary_plan: (input) => (calls.push(`summary ${input}`), JSON.stringify(next.summary)),
	connected_accounts_merge_token_refs: (inputs) => (calls.push(`merge ${inputs}`), JSON.stringify(next.merge))
};

function fakeWorker() {
	const listeners: Record<string, ((event: Event) => void)[]> = { message: [], error: [], messageerror: [] };
	const router = createSharedWorkerRouter({
		installers: { settings: installSettingsUnit },
		loadBinding: async () => binding,
		reply: (reply) => queueMicrotask(() => { for (const l of listeners.message) l({ data: reply } as MessageEvent); })
	});
	const endpoint: SharedWorkerEndpoint = {
		postMessage(message, transfer) { void router.handle(message, transfer as MessagePort[]); },
		addEventListener(type, listener) { listeners[type].push(listener); },
		terminate() {}
	};
	return endpoint;
}

const row = (id: string): EncryptedConnectedAccountRow => ({
	id,
	hashed_user_id: 'hash',
	encrypted_provider_type: `enc:p-${id}`,
	provider_type_hash: 'hash:p',
	encrypted_account_label: 'enc:L',
	encrypted_refresh_token_bundle: `enc:{"ref":"placeholder-${id}"}`,
	encrypted_capabilities: 'enc:[]',
	encrypted_app_permissions: 'enc:{}'
});
const decrypted: string[] = [];
const decrypt = async (value: string, field: string) => {
	decrypted.push(field);
	if (!value.startsWith('enc:')) throw new Error(`Failed to decrypt connected account field: ${field}`);
	const plain = value.slice(4);
	try { return JSON.parse(plain); } catch { return plain; }
};

let unregister: (() => void) | null = null;
beforeEach(() => {
	calls.length = 0;
	decrypted.length = 0;
	next = {};
	unregister = registerSharedRustCore(createSharedCoreClient(fakeWorker));
});
afterEach(() => { unregister?.(); });

describe('connected-account ops on the shared settings unit', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('answers unavailable for a binding without the connected-account exports', () => {
		const handlers = createConnectedAccountsHandlers(settingsExports);
		let refusal: unknown;
		try {
			handlers.selectSendRows({ rows: '[]', accountIds: 'null' }, new AbortController().signal);
		} catch (error) {
			refusal = error;
		}
		expect(refusal).toBeInstanceOf(UnitRefusal);
		expect((refusal as UnitRefusal).code).toBe('unavailable');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('decrypts only selected rows and attaches envelopes the Worker never sees', async () => {
		next.select = { kind: 'ok', indices: [1] };
		next.plan = {
			kind: 'ok',
			directory: [{ connected_account_id: 'b', app_id: 'mail', provider_id: 'p', account_ref: 'b', label: 'L', capabilities: [] }],
			tokens: [
				{ row: 0, connected_account_id: 'b', app_id: 'mail', provider_id: 'p', allowed_actions: ['send'], action_scope: { folder: 'inbox' } },
				{ row: 0, connected_account_id: 'b', app_id: 'mail', provider_id: 'p', allowed_actions: ['send'] }
			]
		};
		const before = rustSettingsStats.calls;
		const context = await rustBuildConnectedAccountSendContext({ rows: [row('a'), row('b')], appId: 'mail', accountIds: ['b'] }, decrypt);
		expect(context?.tokenRefInputs).toEqual([
			{ connected_account_id: 'b', app_id: 'mail', provider_id: 'p', allowed_actions: ['send'], refresh_token_envelope: { ref: 'placeholder-b' }, action_scope: { folder: 'inbox' } },
			{ connected_account_id: 'b', app_id: 'mail', provider_id: 'p', allowed_actions: ['send'], refresh_token_envelope: { ref: 'placeholder-b' } }
		]);
		expect(decrypted.filter((field) => field === 'encrypted_refresh_token_bundle')).toHaveLength(1);
		expect(calls.join('\n')).not.toContain('placeholder-b');
		expect(calls[0]).toBe('select ["b"]');
		expect(rustSettingsStats.calls - before).toBe(2);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('rethrows Rust outcomes as the TypeScript errors without fallback', async () => {
		next.select = { kind: 'error', code: 'forbidden', message: 'Connected account storage payload contains forbidden field: email' };
		await expect(rustBuildConnectedAccountSendContext({ rows: [row('a')], appId: 'mail' }, decrypt))
			.rejects.toThrow('forbidden field: email');
		expect(decrypted).toEqual([]);
		next.summary = { kind: 'error', code: 'malformed', row: 0, fallbacks: [] };
		await expect(rustSummarizeConnectedAccountRows([row('a')], decrypt)).rejects.toBeInstanceOf(TypeError);
		next.merge = { kind: 'error', code: 'missing_refs' };
		await expect(rustMergeTurnTokenRefs([], {})).rejects.toThrow('Token broker response did not include refs');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('rethrows the page decrypt error the summary plan names', async () => {
		const broken = { ...row('a'), encrypted_provider_type: 'fail' };
		next.summary = { kind: 'error', code: 'decrypt', row: 0, fallbacks: [] };
		await expect(rustSummarizeConnectedAccountRows([broken], decrypt))
			.rejects.toThrow('Failed to decrypt connected account field: encrypted_provider_type');
		expect(calls[0]).toContain('"decrypted":[null]');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('sends broker inputs without refresh-token envelopes', async () => {
		next.merge = { kind: 'ok', refs: [{ connected_account_id: 'a', app_id: 'mail', turn_token_ref: 'ttr', expires_at: 1, allowed_actions: [] }] };
		const refs = await rustMergeTurnTokenRefs(
			[{ connected_account_id: 'a', app_id: 'mail', allowed_actions: ['read'], refresh_token_envelope: { ref: 'placeholder-secret' } }],
			{ refs: [] }
		);
		expect(refs[0].turn_token_ref).toBe('ttr');
		expect(calls[0]).not.toContain('placeholder-secret');
		expect(calls[0]).not.toContain('refresh_token_envelope');
	});
});
