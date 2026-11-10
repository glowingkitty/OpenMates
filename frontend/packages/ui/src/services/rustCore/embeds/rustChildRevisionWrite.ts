/**
 * Version N+1 of a generated image child (`send_embed_data` with
 * `payload.revision`) through the shared Worker's Rust `embedWrite` unit
 * (`images-generate.revision.same-embed-new-version`; VITE_OPENMATES_RUST_CORE
 * builds only, called by rustStreamedEmbedWrite.ts inside the per-embed write
 * lease after the parent and child keys were loaded).
 *
 * Rust prepares every step (`prepare_child_revision`, also on every replay:
 * it returns only the writes the server has not confirmed); this module only
 * runs them strictly in order and stops at the first failure:
 *   base snapshot N (only when the server asked) -> head N+1 -> history row N+1.
 * Per step the Worker stores the local value, the page sends, and only after a
 * successful send the Worker stores the confirmed value (the local durability
 * marker a later replay reads). A `store_embed_diff` that another tab or device stored first
 * (`embed_diff_conflict` / `immutable_version_mismatch`) is resolved by Rust
 * (`adopt_child_revision_row`) from the canonical bounded-v1 page. The image is
 * never added to the changing message's `embed_ids` and never re-parented.
 * There is no TypeScript fallback: every refusal rejects with its Rust code.
 */
import type { ChatSynchronizationService } from '../../chatSyncService';
import type { CanonicalEmbedWriteLease } from '../../canonicalEmbedWriteCoordinator';
import type { SendEmbedDataPayload, StoreEmbedPayload } from '../../../types/chat';
import { UnitPortError, type UnitPort } from '../host/unitPort';
import type { StreamCompletionInput } from '../embedWriteAdapter';
import type { EmbedWriteProtocol } from './embedDataProtocol';

type EmbedData = SendEmbedDataPayload['payload'];

/** The page IO the sequence needs (injected so the order is unit-tested without a socket). */
export interface ChildRevisionIO {
	sendStoreEmbed(payload: StoreEmbedPayload): Promise<boolean>;
	sendStoreEmbedDiff(payload: Record<string, unknown>): Promise<void>;
	readCanonical(version: number): Promise<{ status: number; body: unknown }>;
	afterHeadStored(result: { embedRef: string; registration: EmbedWriteProtocol['runChildRevisionStep']['response'] }): Promise<void>;
}

/** Rejection codes of a `store_embed_diff` whose row another writer stored first. */
const ROW_TAKEN = new Set(['embed_diff_conflict', 'immutable_version_mismatch']);

function errorCode(error: unknown): string | undefined {
	const code = (error as { code?: unknown } | null)?.code;
	return typeof code === 'string' ? code : undefined;
}

/** True when the event is a child revision (the core validates its shape). */
export function isChildRevisionEvent(embedData: EmbedData): boolean {
	const revision = (embedData as unknown as Record<string, unknown>).revision;
	return revision !== undefined && revision !== null;
}

/**
 * Runs the Rust-prepared steps of one child revision. Resolves false when the
 * head already holds this version (a replay: nothing is written).
 */
export async function runChildRevision(unit: UnitPort<EmbedWriteProtocol>, input: StreamCompletionInput,
	normalizedType: string, io: ChildRevisionIO): Promise<boolean> {
	const embedId = input.embed_id;
	const plan = await unit.request('prepareChildRevision', { payload: input, normalizedType });
	if (plan.already_applied) return false;
	try {
		for (let index = 0; index < plan.steps.length; index++) {
			const step = await unit.request('runChildRevisionStep', { embedId, index });
			if (step.op === 'store_embed') {
				// Not durable (offline queue, conflict, denial): the head stays pending and history
				// N+1 would be refused, so stop here; a replay resends the stored head.
				if (!(await io.sendStoreEmbed(step.store_payload as unknown as StoreEmbedPayload))) {
					throw new UnitPortError('embed_revision_head_not_durable');
				}
				await unit.request('confirmChildRevisionStep', { embedId, index });
				await io.afterHeadStored({ embedRef: step.content_ref, registration: step });
				continue;
			}
			try {
				await io.sendStoreEmbedDiff(step.server_payload);
			} catch (error) {
				if (!ROW_TAKEN.has(errorCode(error) ?? '')) throw error;
				const read = await io.readCanonical(step.version);
				if (read.status !== 200 || read.body === undefined) throw error;
				// The adopted canonical row is stored as confirmed.
				await unit.request('adoptChildRevisionRow', { embedId, index, page: read.body });
				continue;
			}
			await unit.request('confirmChildRevisionStep', { embedId, index });
		}
	} finally {
		await unit.request('endChildRevision', { embedId });
	}
	return true;
}

/** Production IO over the existing senders (WebSocket under the lease, bounded-v1 HTTP read). */
export async function childRevisionIO(service: ChatSynchronizationService, lease: CanonicalEmbedWriteLease,
	readCanonical: (version: number) => Promise<{ status: number; body: unknown }>,
	afterHeadStored: ChildRevisionIO['afterHeadStored']): Promise<ChildRevisionIO> {
	const { sendStoreEmbedImpl, sendStoreEmbedDiffImpl } = await import('../../chatSyncServiceSenders');
	return {
		sendStoreEmbed: (payload) => sendStoreEmbedImpl(service, payload, undefined, lease, 'child-revision'),
		sendStoreEmbedDiff: (payload) => sendStoreEmbedDiffImpl(service, payload as unknown as Parameters<typeof sendStoreEmbedDiffImpl>[1]),
		readCanonical,
		afterHeadStored
	};
}
