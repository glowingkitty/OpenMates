/**
 * Connected-account ops of the shared Rust core Worker (unitPort.ts wire v1),
 * served on the stateless pre-bind `settings` unit (SettingsUnitProtocol
 * extends this), so no extra namespace or Worker port is opened.
 *
 * Every operation is a pure decision of packages/openmates-rust/src/web_connected_accounts.rs.
 * The page keeps fetch, master-key decryption and the refresh-token envelopes;
 * it sends rows, decrypted non-credential facts and broker responses as JSON
 * text and gets back row selections, directory/token plans, summaries and
 * merged turn-token refs. No refresh-token envelope crosses this protocol.
 */
import type { UnitProtocol } from '../host/unitPort';
import type { ConnectedAccountSummary } from '../../connectedAccountStorageService';
import type {
	ConnectedAccountDirectoryEntry,
	ConnectedAccountTurnTokenRef
} from '../../connectedAccountTokenBrokerService';

/** A decision the TypeScript service would have thrown for. */
export type ConnectedAccountsFailure =
	| { kind: 'error'; code: 'malformed' }
	| { kind: 'error'; code: 'forbidden'; message: string }
	| { kind: 'error'; code: 'missing_refs' }
	| { kind: 'error'; code: 'missing_token'; message: string };

export interface ConnectedAccountTokenPlan {
	/** Position in the selected rows whose refresh-token envelope the page attaches. */
	row: number;
	connected_account_id: string;
	app_id: string;
	provider_id?: string;
	allowed_actions: string[];
	action_scope?: Record<string, unknown>;
}

export type SelectSendRowsOutcome = { kind: 'ok'; indices: number[] } | ConnectedAccountsFailure;
export type SendContextPlanOutcome =
	| { kind: 'ok'; directory: ConnectedAccountDirectoryEntry[]; tokens: ConnectedAccountTokenPlan[] }
	| ConnectedAccountsFailure;
export type SummaryPlanOutcome =
	| { kind: 'ok'; summaries: ConnectedAccountSummary[]; fallbacks: number[] }
	| { kind: 'error'; code: 'decrypt' | 'malformed'; row: number; fallbacks: number[] }
	| ConnectedAccountsFailure;
export type MergeTokenRefsOutcome = { kind: 'ok'; refs: ConnectedAccountTurnTokenRef[] } | ConnectedAccountsFailure;

/** One OAuth row step, in TypeScript await order; `bundle` is filled by the page. */
export type OAuthRowStep =
	| { field: string; hash: string }
	| { field: string; encrypt: string; failure: string }
	| { field: string; bundle: true; failure: string };
export type OAuthRowPlanOutcome = { kind: 'ok'; steps: OAuthRowStep[]; malformed: boolean } | ConnectedAccountsFailure;
export type StorageGuardOutcome = { kind: 'ok' } | ConnectedAccountsFailure;
/** Where each CLI transfer payload field comes from (the page assembles it in key order). */
export type TransferPlanOutcome =
	| {
			kind: 'ok';
			app_id: { value: string } | { from: 'permissions' | 'provider' };
			label: 'hint' | 'row';
			account_ref: boolean;
			capabilities: string[];
			runtime_modes: 'hint' | [string, string][];
	  }
	| ConnectedAccountsFailure;
export type TransferCommandOutcome = { kind: 'ok'; command: string } | ConnectedAccountsFailure;

export interface ConnectedAccountsUnitProtocol extends UnitProtocol {
	selectSendRows: { request: { rows: string; accountIds: string }; response: SelectSendRowsOutcome };
	sendContextPlan: { request: { input: string }; response: SendContextPlanOutcome };
	summaryPlan: { request: { input: string }; response: SummaryPlanOutcome };
	mergeTokenRefs: { request: { inputs: string; payload: string }; response: MergeTokenRefsOutcome };
	oauthRowPlan: { request: { input: string }; response: OAuthRowPlanOutcome };
	storageGuard: { request: { serialized: string }; response: StorageGuardOutcome };
	transferPlan: { request: { input: string }; response: TransferPlanOutcome };
	transferCommand: { request: { payload: string }; response: TransferCommandOutcome };
}

/** Worker module exports (snake_case, JSON strings) of browser_connected_accounts.rs. */
export interface ConnectedAccountsBinding {
	connected_accounts_select_send_rows(rowsJson: string, accountIdsJson: string): string;
	connected_accounts_send_context_plan(inputJson: string): string;
	connected_accounts_summary_plan(inputJson: string): string;
	connected_accounts_merge_token_refs(inputsJson: string, payloadJson: string): string;
	connected_accounts_oauth_row_plan(inputJson: string): string;
	connected_accounts_storage_guard(serialized: string): string;
	connected_accounts_transfer_plan(inputJson: string): string;
	connected_accounts_transfer_command(encryptedPayload: string): string;
}

const BINDING_EXPORTS: readonly (keyof ConnectedAccountsBinding)[] = [
	'connected_accounts_select_send_rows',
	'connected_accounts_send_context_plan',
	'connected_accounts_summary_plan',
	'connected_accounts_merge_token_refs',
	'connected_accounts_oauth_row_plan',
	'connected_accounts_storage_guard',
	'connected_accounts_transfer_plan',
	'connected_accounts_transfer_command'
];

export function isConnectedAccountsBinding(value: unknown): value is ConnectedAccountsBinding {
	if (typeof value !== 'object' || value === null) return false;
	const binding = value as Record<string, unknown>;
	return BINDING_EXPORTS.every((name) => typeof binding[name] === 'function');
}
