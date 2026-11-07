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
};

export interface EmbedReadBinding {
	/** Rust `embed_read::patch::apply_version_patch`; throws the TS refusal message. */
	embed_apply_version_patch(content: string, patch: string): string;
	/** Rust `embed_read::admission::is_embed_event_admitted`. */
	embed_event_admitted(currentStatus: string, incomingStatus: string | undefined, currentVersion: number | undefined,
		incomingVersion: number | undefined, versionExempt: boolean): boolean;
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
