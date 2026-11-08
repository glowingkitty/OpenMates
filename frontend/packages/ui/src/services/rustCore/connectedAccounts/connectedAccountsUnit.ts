/**
 * Connected-account handlers of the shared Rust core Worker, served on the
 * pre-bind `settings` unit (settingsUnit.ts spreads them in): stateless
 * decisions with no IO and no per-account state, like the settings policy.
 *
 * Serves connectedAccountsProtocol.ts from the realm's single WASM binding. A
 * binding without the connected-account exports answers `unavailable`; a
 * malformed payload, or any binding rejection, answers the fixed code
 * `protocol` (the Rust boundary's only code).
 */
import { UnitRefusal, type UnitHandlers } from '../host/unitPort';
import { isConnectedAccountsBinding, type ConnectedAccountsUnitProtocol } from './connectedAccountsProtocol';

function record(payload: unknown): Record<string, unknown> {
	if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) throw new UnitRefusal('protocol');
	return payload as Record<string, unknown>;
}
function text(value: unknown): string {
	if (typeof value !== 'string') throw new UnitRefusal('protocol');
	return value;
}
/** Binding results are JSON text; a thrown JsValue is the Rust `protocol` code. */
function call<T>(run: () => string): T {
	let json: string;
	try {
		json = run();
	} catch {
		throw new UnitRefusal('protocol');
	}
	return JSON.parse(json) as T;
}

export function createConnectedAccountsHandlers(value: unknown): UnitHandlers<ConnectedAccountsUnitProtocol> {
	const binding = () => {
		if (!isConnectedAccountsBinding(value)) throw new UnitRefusal('unavailable');
		return value;
	};
	return {
		selectSendRows: (payload) => {
			const p = record(payload);
			const rows = text(p.rows);
			const ids = text(p.accountIds);
			const exports = binding();
			return call(() => exports.connected_accounts_select_send_rows(rows, ids));
		},
		sendContextPlan: (payload) => {
			const input = text(record(payload).input);
			const exports = binding();
			return call(() => exports.connected_accounts_send_context_plan(input));
		},
		summaryPlan: (payload) => {
			const input = text(record(payload).input);
			const exports = binding();
			return call(() => exports.connected_accounts_summary_plan(input));
		},
		mergeTokenRefs: (payload) => {
			const p = record(payload);
			const inputs = text(p.inputs);
			const body = text(p.payload);
			const exports = binding();
			return call(() => exports.connected_accounts_merge_token_refs(inputs, body));
		}
	};
}
