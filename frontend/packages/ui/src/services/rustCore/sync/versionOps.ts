/**
 * Version-wins plans of the shared Rust core Worker `sync` unit
 * (web_sync/versions.rs). Loaded only by the guarded branches of
 * chatSyncVersionPlans.ts, so default builds never bundle it. Only version
 * counters are sent; the ops are merged into SYNC_OPS via INBOUND_OPS.
 */
import type { Chat } from '../../../types/chat';
import type { DraftDeletedPlan, MessagesVersionPlan, MetadataVersionPlan, MetadataVersions } from '../../chatSyncVersionPlans';
import { syncCall } from './syncUnitClient';

const VERSION_KEYS = ['messages_v', 'metadata_v', 'title_v', 'draft_v'] as const;

/** Copies only the version counters (absent stays absent, so `undefined` keeps its meaning). */
function versionsOnly(source: Record<string, unknown>): Record<string, unknown> {
	const out: Record<string, unknown> = {};
	for (const key of VERSION_KEYS) if (source[key] !== undefined) out[key] = source[key];
	return out;
}

export async function metadataVersions(
	local: Pick<Chat, 'messages_v' | 'title_v' | 'draft_v'> & { metadata_v?: number | null },
	versions: MetadataVersions | undefined,
): Promise<MetadataVersionPlan> {
	return syncCall('metadataVersions', {
		local: versionsOnly(local),
		versions: versions ? versionsOnly(versions) : undefined,
	});
}

export async function draftDeleted(
	local: Pick<Chat, 'draft_v' | 'cleared_draft_v'>,
	draftV: number | undefined,
): Promise<DraftDeletedPlan> {
	return syncCall('draftDeleted', {
		local: { draft_v: local.draft_v, cleared_draft_v: local.cleared_draft_v },
		draftV,
	});
}

export async function messagesVersion(local: number | null | undefined, candidates: number[]): Promise<MessagesVersionPlan> {
	return syncCall('messagesVersion', { local, candidates });
}
