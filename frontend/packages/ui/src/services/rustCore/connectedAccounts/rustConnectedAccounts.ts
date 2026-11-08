/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) connected-account service logic: the page
 * adapter over the connected-account ops of the shared Rust core Worker's
 * stateless pre-bind `settings` unit (connectedAccountsProtocol.ts). Loaded only
 * through the guarded branches of connectedAccountStorageService.ts and
 * connectedAccountTokenBrokerService.ts, which default builds drop.
 *
 * Rust (web_connected_accounts.rs) decides row selection, plaintext guards,
 * directory entries, token-ref plans, summaries and the broker ref merge. The
 * page keeps the IO: master-key decryption and attaching each planned row's
 * decrypted refresh-token envelope, which never enters the Worker. Rust
 * outcomes are rethrown as the errors the TypeScript service throws (a
 * `TypeError` where it would hit one); there is no TypeScript fallback.
 */
import type {
	ConnectedAccountSendContext,
	ConnectedAccountTurnTokenRef,
	ConnectedAccountTurnTokenRefInput
} from '../../connectedAccountTokenBrokerService';
import type {
	ConnectedAccountSummary,
	EncryptedConnectedAccountRow
} from '../../connectedAccountStorageService';
import { settingsCall as connectedAccountsCall } from '../settings/settingsClient';
import type { ConnectedAccountsFailure } from './connectedAccountsProtocol';

/** The storage service's master-key field decrypt (JSON when it parses, else the text). */
export type DecryptConnectedAccountField = (encryptedValue: string, fieldName: string) => Promise<unknown>;

const MALFORMED = 'Connected account data is malformed';

/** The TypeScript error a Rust failure outcome stands for. */
export function failure(outcome: Pick<ConnectedAccountsFailure, 'code'> & { message?: string }): Error {
	if (outcome.code === 'malformed') return new TypeError(MALFORMED);
	if (outcome.code === 'missing_refs') return new Error('Token broker response did not include refs');
	return new Error(outcome.message);
}

/** Decrypted non-credential fields of a row (`hint` only when the row has one). */
async function decryptRowFacts(row: EncryptedConnectedAccountRow, decrypt: DecryptConnectedAccountField) {
	const [provider, label, capabilities, permissions, hint] = await Promise.all([
		decrypt(row.encrypted_provider_type, 'encrypted_provider_type'),
		decrypt(row.encrypted_account_label, 'encrypted_account_label'),
		decrypt(row.encrypted_capabilities, 'encrypted_capabilities'),
		decrypt(row.encrypted_app_permissions, 'encrypted_app_permissions'),
		row.encrypted_account_directory_hint
			? decrypt(row.encrypted_account_directory_hint, 'encrypted_account_directory_hint')
			: Promise.resolve(undefined)
	]);
	return {
		provider,
		label,
		capabilities,
		permissions,
		...(row.encrypted_account_directory_hint ? { hint } : {})
	};
}

export async function rustBuildConnectedAccountSendContext(
	params: {
		rows: EncryptedConnectedAccountRow[];
		appId: string;
		accountIds?: string[];
		defaultAllowedActions?: string[];
		allowedActionsOverride?: string[];
		actionScopesOverride?: Record<string, unknown>[];
		includeActionScope?: boolean;
	},
	decrypt: DecryptConnectedAccountField
): Promise<ConnectedAccountSendContext | undefined> {
	const selection = await connectedAccountsCall('selectSendRows', {
		rows: JSON.stringify(params.rows),
		accountIds: JSON.stringify(params.accountIds ?? null)
	});
	if (selection.kind === 'error') throw failure(selection);
	if (selection.indices.length === 0) return undefined;
	const rows = selection.indices.map((index) => params.rows[index]);
	const planRows: Record<string, unknown>[] = [];
	for (const row of rows) {
		planRows.push({ id: row.id, execution_mode: row.execution_mode, ...(await decryptRowFacts(row, decrypt)) });
	}
	const plan = await connectedAccountsCall('sendContextPlan', {
		input: JSON.stringify({
			appId: params.appId,
			defaultAllowedActions: params.defaultAllowedActions,
			allowedActionsOverride: params.allowedActionsOverride,
			actionScopesOverride: params.actionScopesOverride,
			includeActionScope: params.includeActionScope,
			rows: planRows
		})
	});
	if (plan.kind === 'error') throw failure(plan);
	const envelopes = new Map<number, Record<string, unknown>>();
	const tokenRefInputs: ConnectedAccountTurnTokenRefInput[] = [];
	for (const token of plan.tokens) {
		if (!envelopes.has(token.row)) {
			const row = rows[token.row];
			envelopes.set(
				token.row,
				(await decrypt(row.encrypted_refresh_token_bundle, 'encrypted_refresh_token_bundle')) as Record<string, unknown>
			);
		}
		tokenRefInputs.push({
			connected_account_id: token.connected_account_id,
			app_id: token.app_id,
			provider_id: token.provider_id,
			allowed_actions: token.allowed_actions,
			refresh_token_envelope: envelopes.get(token.row) as Record<string, unknown>,
			...('action_scope' in token ? { action_scope: token.action_scope } : {})
		});
	}
	return { directory: plan.directory, tokenRefInputs };
}

export async function rustSummarizeConnectedAccountRows(
	rows: EncryptedConnectedAccountRow[],
	decrypt: DecryptConnectedAccountField
): Promise<ConnectedAccountSummary[]> {
	const decrypted: unknown[] = [];
	const decryptErrors: unknown[] = [];
	for (const row of rows) {
		try {
			decrypted.push(await decryptRowFacts(row, decrypt));
			decryptErrors.push(undefined);
		} catch (decryptError) {
			// Rust decides per row whether the local-connector metadata replaces
			// the summary or this error is rethrown, as the TS try/catch did.
			decrypted.push(null);
			decryptErrors.push(decryptError);
		}
	}
	const outcome = await connectedAccountsCall('summaryPlan', { input: JSON.stringify({ rows, decrypted }) });
	if ('fallbacks' in outcome) {
		for (const index of outcome.fallbacks) {
			console.warn('[ConnectedAccountStorage] Using non-secret local connector metadata after encrypted summary fields could not be decrypted:', rows[index].id);
		}
	}
	if (outcome.kind === 'ok') return outcome.summaries;
	if ('row' in outcome) {
		if (outcome.code === 'decrypt') throw decryptErrors[outcome.row];
		throw failure({ code: 'malformed' });
	}
	throw failure(outcome);
}

export async function rustMergeTurnTokenRefs(
	inputs: ConnectedAccountTurnTokenRefInput[],
	payload: unknown
): Promise<ConnectedAccountTurnTokenRef[]> {
	// Only the non-secret fields cross to the Worker; the envelopes stay here.
	const stripped = inputs.map((input) => ({
		connected_account_id: input.connected_account_id,
		app_id: input.app_id,
		provider_id: input.provider_id,
		allowed_actions: input.allowed_actions,
		action_scope: input.action_scope
	}));
	const outcome = await connectedAccountsCall('mergeTokenRefs', {
		inputs: JSON.stringify(stripped),
		payload: JSON.stringify(payload)
	});
	if (outcome.kind === 'error') throw failure(outcome);
	return outcome.refs;
}
