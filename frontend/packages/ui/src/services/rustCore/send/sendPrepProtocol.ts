/**
 * `sendPrep` unit protocol of the shared Rust core Worker (unitPort.ts wire v1).
 *
 * Message preparation, preflight and offline-outbox decisions run in shared Rust
 * (packages/openmates-rust/src/web_send_prep/*.rs). The page keeps IndexedDB, the
 * WebSocket and per-connection batch bookkeeping; it sends minimal change fields
 * and applies the answer. The unit holds no account state and does no IO.
 */
import type { UnitProtocol } from '../host/unitPort';

/** The only fields of a queued offline change that decide replay order. */
export interface OutboxOrderRow {
	chat_id: string;
	team_id?: string | null;
	type: string;
	queue_order?: number | null;
}
export interface OfflineReceiptCounts { processed: number; errors: number; conflicts: number }

/** Routing fields of the user profile; the unit validates and copies them for one turn. */
export interface RoutingProfileFields {
	disabled_ai_models?: unknown;
	disabled_ai_servers?: unknown;
	server_region_preference?: unknown;
}
export interface RoutingRestrictionsAnswer {
	ok: boolean;
	restrictions?: { disabled_ai_models: string[]; disabled_ai_servers: Record<string, string[]>; server_region_preference: 'eu' | 'global' };
}

/** Page-read facts that decide whether a queued deferred draft deletion may replay. */
export interface DeferredDeleteFacts {
	editorOnChat: boolean; editorUnsaved: boolean; localExists: boolean;
	hasDraft: boolean; hasPreview: boolean; draftVersion: number | null;
}

export interface SendPrepUnitProtocol extends UnitProtocol {
	deferredDeleteReplay: { request: DeferredDeleteFacts; response: { eligible: boolean } };
	/** `ready`: indices into `rows` in replay order; `retained`: rows with ambiguous order. */
	orderOffline: { request: { rows: OutboxOrderRow[] }; response: { ready: number[]; retained: number } };
	routingRestrictions: { request: RoutingProfileFields; response: RoutingRestrictionsAnswer };
	offlineReceipt: {
		request: {
			changeIds: string[]; terminalConflictDeleteIds: string[]; successfulIds: string[];
			counts: OfflineReceiptCounts | null;
		};
		response: { accepted: string[]; retiredConflictIds: string[] };
	};
}

/** Worker module exports (snake_case, JSON text) of browser_send_prep.rs. */
export interface SendPrepBinding {
	send_prep_order_offline(input: string): string;
	send_prep_offline_receipt(input: string): string;
	send_prep_routing_restrictions(input: string): string;
	send_prep_deferred_delete(input: string): string;
}

const BINDING_EXPORTS: readonly (keyof SendPrepBinding)[] = ['send_prep_order_offline', 'send_prep_offline_receipt', 'send_prep_routing_restrictions', 'send_prep_deferred_delete'];

export function isSendPrepBinding(value: unknown): value is SendPrepBinding {
	if (typeof value !== 'object' || value === null) return false;
	const binding = value as Record<string, unknown>;
	return BINDING_EXPORTS.every((name) => typeof binding[name] === 'function');
}
