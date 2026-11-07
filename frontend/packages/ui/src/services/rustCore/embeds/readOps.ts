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

export type EmbedReadProtocol = {
	applyVersionPatches: { request: { items: VersionPatchItem[] }; response: VersionPatchResult[] };
};

export interface EmbedReadBinding {
	/** Rust `embed_read::patch::apply_version_patch`; throws the TS refusal message. */
	embed_apply_version_patch(content: string, patch: string): string;
}

export function isEmbedReadBinding(value: unknown): value is EmbedReadBinding {
	return typeof (value as Partial<EmbedReadBinding> | null)?.embed_apply_version_patch === 'function';
}

function validPatchItem(value: unknown): value is VersionPatchItem {
	const item = value as Record<string, unknown> | null;
	return typeof item === 'object' && item !== null && typeof item.content === 'string' && typeof item.patch === 'string';
}

/** Handlers over `binding`; a binding without the export (older Worker build) refuses with `unavailable`. */
export function createEmbedReadHandlers(binding: Partial<EmbedReadBinding>): UnitHandlers<EmbedReadProtocol> {
	return {
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
