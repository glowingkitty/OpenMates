/**
 * `embedData` read ops that run shared Rust `embed_read` logic in the Worker:
 * exact replay of legacy artifact version patches (`applyVersionPatch`).
 * The unit merges `createEmbedReadHandlers` into its op table (one line); the
 * page calls `applyVersionPatchInRust` (embedDataClient.ts).
 */
import { UnitRefusal, type UnitHandlers } from '../host/unitPort';
import { EMBED_DATA_MAX_ITEMS } from './embedDataProtocol';

/** One patch to replay on `content`. */
export interface VersionPatchItem {
	content: string;
	patch: string;
}

/** Per-item result: the patched text, or the fixed refusal code (`version_patch_refused`). */
export type VersionPatchResult = { ok: true; content: string } | { ok: false; code: string };

/** Stored and incoming facts of one inbound embed event (Rust `EmbedEventFacts`). */
export interface EmbedEventAdmissionRequest {
	currentStatus: string;
	incomingStatus: string | null;
	currentVersion: number | null;
	incomingVersion: number | null;
	versionExempt: boolean;
}

export type EmbedReadProtocol = {
	applyVersionPatches: { request: { items: VersionPatchItem[] }; response: VersionPatchResult[] };
	/** Rust `embed_read::admission`: true when the inbound embed event may be applied. */
	admitEmbedEvent: { request: EmbedEventAdmissionRequest; response: boolean };
	/** Rust `embed_read::run_json`: one canonical embed sender decision (embedSenderPolicy.ts), JSON text in and out. */
	decideSender: { request: { op: string; input: string }; response: string };
};

/** Sender decision op names (`sender*`, embedSenderPolicy.ts `EmbedSenderOp`). */
const SENDER_OP = /^sender[A-Z][A-Za-z]{1,40}$/;
/** Largest sender decision document (a canonical page carries at most 128 wrapper rows). */
const SENDER_INPUT_MAX = 4 * 1024 * 1024;

export interface EmbedReadBinding {
	/** Rust `embed_read::patch::apply_version_patch`; throws the TS refusal message. */
	embed_apply_version_patch(content: string, patch: string): string;
	/** Rust `embed_read::admission::is_embed_event_admitted`. */
	embed_event_admitted(currentStatus: string, incomingStatus: string | undefined, currentVersion: number | undefined,
		incomingVersion: number | undefined, versionExempt: boolean): boolean;
	/** Rust `embed_read::run_json`; throws `embed_sender:<reason>` for an unknown op or malformed document. */
	embed_sender_decide(op: string, input: string): string;
}

export function isEmbedReadBinding(value: unknown): value is EmbedReadBinding {
	return typeof (value as Partial<EmbedReadBinding> | null)?.embed_apply_version_patch === 'function';
}

function nullableNumber(value: unknown): value is number | null {
	return value === null || (typeof value === 'number' && Number.isFinite(value));
}

function validPatchItem(value: unknown): value is VersionPatchItem {
	const item = value as Record<string, unknown> | null;
	return typeof item === 'object' && item !== null && typeof item.content === 'string' && typeof item.patch === 'string';
}

/** Handlers over `binding`; a binding without the export (older Worker build) refuses with `unavailable`. */
export function createEmbedReadHandlers(binding: Partial<EmbedReadBinding>): UnitHandlers<EmbedReadProtocol> {
	return {
		decideSender(payload) {
			const r = payload as Partial<{ op: unknown; input: unknown }> | null;
			if (typeof r !== 'object' || r === null || typeof r.op !== 'string' || !SENDER_OP.test(r.op)
				|| typeof r.input !== 'string' || r.input.length > SENDER_INPUT_MAX) {
				throw new UnitRefusal('embed_data_bad_request');
			}
			const decide = binding.embed_sender_decide;
			if (!decide) throw new UnitRefusal('unavailable');
			let decision: unknown;
			try {
				decision = decide.call(binding, r.op, r.input);
			} catch (error) {
				// Rust refuses with `embed_sender:<reason>` (a page bug: malformed document); never user content.
				throw new UnitRefusal(typeof error === 'string' && error.startsWith('embed_sender:') ? 'embed_sender_refused' : 'embed_data_failed');
			}
			if (typeof decision !== 'string') throw new UnitRefusal('embed_data_failed');
			return decision;
		},
		admitEmbedEvent(payload) {
			const r = payload as Partial<EmbedEventAdmissionRequest> | null;
			if (typeof r !== 'object' || r === null || typeof r.currentStatus !== 'string' || typeof r.versionExempt !== 'boolean'
				|| !(r.incomingStatus === null || typeof r.incomingStatus === 'string')
				|| !nullableNumber(r.currentVersion) || !nullableNumber(r.incomingVersion)) {
				throw new UnitRefusal('embed_data_bad_request');
			}
			const admit = binding.embed_event_admitted;
			if (!admit) throw new UnitRefusal('unavailable');
			const decision = admit.call(binding, r.currentStatus, r.incomingStatus ?? undefined, r.currentVersion ?? undefined,
				r.incomingVersion ?? undefined, r.versionExempt);
			if (typeof decision !== 'boolean') throw new UnitRefusal('embed_data_failed');
			return decision;
		},
		applyVersionPatches(payload) {
			const items = (payload as { items?: unknown } | null)?.items;
			if (!Array.isArray(items) || items.length > EMBED_DATA_MAX_ITEMS || !items.every(validPatchItem)) {
				throw new UnitRefusal('embed_data_bad_request');
			}
			const apply = binding.embed_apply_version_patch;
			if (!isEmbedReadBinding(binding) || !apply) throw new UnitRefusal('unavailable');
			return items.map((item): VersionPatchResult => {
				try {
					return { ok: true, content: apply.call(binding, item.content, item.patch) };
				} catch (error) {
					// Rust refusals throw a fixed TS-parity sentence; anything else is a protocol fault.
					if (typeof error === 'string' && error !== 'unavailable') return { ok: false, code: 'version_patch_refused' };
					throw new UnitRefusal('embed_data_failed');
				}
			});
		}
	};
}
