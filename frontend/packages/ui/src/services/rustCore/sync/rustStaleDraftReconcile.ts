/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) reconnect reconciliation of stale local
 * drafts: the page adapter over the `sync` unit ops `staleDraftProbe` and
 * `staleDraftPlan` (packages/openmates-rust/src/web_sync/stale_drafts.rs).
 *
 * Rust decides which local rows are probed (idle, no queued change, Personal)
 * and what the server's answer may change. The page only reads IndexedDB rows
 * and the offline queue, sends the probe with the Phase 2 request and runs the
 * version-guarded IndexedDB writes. Spec: architecture.drafts
 * (drafts.sync.version-authoritative, drafts.draft-only.lifecycle).
 */
import { get } from 'svelte/store';
import type { Chat } from '../../../types/chat';
import type { ChatSynchronizationService } from '../../chatSyncService';
import { syncCall } from './syncUnitClient';
import { isDraftChatClaimedForSend } from '../../drafts/draftSendClaims';
import type { SyncStaleDraftProbeEntry } from './syncProtocol';

type JsonRecord = Record<string, unknown>;

/** Row fields the eligibility rule reads (no plaintext, no keys). */
const ROW_PROJECTION = [
	'chat_id', 'team_id', 'chat_visibility', 'messages_v', 'title_v', 'draft_v', 'encrypted_draft_md',
	'title', 'encrypted_title', 'chat_summary', 'encrypted_chat_summary', 'icon', 'encrypted_icon', 'category',
	'encrypted_category', 'ideabucket_triggered_at', 'team_draft_pending_sync', 'team_chat_pending_commit',
	'is_incognito', 'is_anonymous', 'is_hidden_candidate', 'updated_at', 'last_edited_overall_timestamp', 'created_at',
] as const;

/** Upper bound of IndexedDB row reads per reconnect (the probe itself is capped in Rust). */
const MAX_CANDIDATE_READS = 1000;

/** Probe of the request in flight, keyed by the context epoch it was sent for. */
let sentProbe: { epoch: unknown; probe: SyncStaleDraftProbeEntry[] } | null = null;

/**
 * Builds the `stale_draft_probe` field for a Personal Phase 2 request from the
 * chats the request already lists (`draftVersions`: chat id to local draft_v).
 * Returns `undefined` when nothing is probed (Team context, no idle drafts).
 */
export async function buildStaleDraftProbe(
	teamId: string | null,
	epoch: unknown,
	draftVersions: Iterable<[string, number]>,
	pendingDeletions: ReadonlySet<string>,
): Promise<Array<{ chat_id: string; draft_v: number }> | undefined> {
	sentProbe = null;
	if (teamId) return undefined;
	try {
		return await collectProbe(epoch, draftVersions, pendingDeletions);
	} catch (error) {
		// The probe is optional: without it this reconnect simply reconciles nothing
		// extra, and phased sync must still start.
		console.warn('[ChatSyncService] Stale draft probe unavailable for this reconnect:', error);
		sentProbe = null;
		return undefined;
	}
}

async function collectProbe(
	epoch: unknown,
	draftVersions: Iterable<[string, number]>,
	pendingDeletions: ReadonlySet<string>,
): Promise<Array<{ chat_id: string; draft_v: number }> | undefined> {
	const candidates: string[] = [];
	for (const [chatId, draftV] of draftVersions) {
		if (draftV > 0) candidates.push(chatId);
		if (candidates.length >= MAX_CANDIDATE_READS) break;
	}
	if (candidates.length === 0) return undefined;
	const { chatDB } = await import('../../db');
	const [changes, rows] = await Promise.all([
		chatDB.getOfflineChanges(),
		Promise.all(candidates.map((chatId) => chatDB.getRawChat(chatId))),
	]);
	const projected = rows.filter((row): row is Chat => row !== null).map((row) => {
		const out: JsonRecord = {};
		for (const key of ROW_PROJECTION) out[key] = (row as unknown as JsonRecord)[key];
		return out;
	});
	const pendingChatIds = [...new Set([...changes.map((change) => change.chat_id), ...pendingDeletions])];
	const { wire, probe } = await syncCall('staleDraftProbe', {
		now: Math.floor(Date.now() / 1000), rows: projected, pendingChatIds,
	});
	if (probe.length === 0) return undefined;
	sentProbe = { epoch, probe };
	return wire;
}

/**
 * Applies `stale_draft_probe_result` of a Personal Phase 2 reply. Each write is
 * guarded by the probed draft version inside its IndexedDB transaction, and an
 * editor with unsaved changes on that chat is left alone.
 */
export async function applyStaleDraftProbeResult(
	service: ChatSynchronizationService,
	payload: { team_id?: string | null; context_epoch?: unknown; stale_draft_probe_result?: unknown },
): Promise<void> {
	const sent = sentProbe;
	if (!sent || payload.team_id || sent.epoch !== payload.context_epoch) return;
	sentProbe = null;
	let plan: Awaited<ReturnType<typeof syncCall<'staleDraftPlan'>>>;
	try {
		plan = await syncCall('staleDraftPlan', { probe: sent.probe, result: payload.stale_draft_probe_result ?? null });
	} catch (error) {
		// Keep every local draft when the decision is unavailable; Phase 2 storage continues.
		console.warn('[ChatSyncService] Stale draft plan unavailable; keeping local drafts:', error);
		return;
	}
	if (plan.length === 0) return;
	const [{ chatDB }, { chatListCache }, { chatMetadataCache }, { draftEditorUIState }, { LOCAL_CHAT_LIST_CHANGED_EVENT }] =
		await Promise.all([
			import('../../db'), import('../../chatListCache'), import('../../chatMetadataCache'),
			import('../../drafts/draftState'), import('../../drafts/draftConstants'),
		]);
	let changed = false;
	for (const { chatId, action, draftV } of plan) {
		const editor = get(draftEditorUIState);
		if (editor.currentChatId === chatId && editor.hasUnsavedChanges) continue;
		try {
			if (action === 'delete_draft_only') {
				// A send in progress stores its first message in this chat next; deleting the
				// draft shell now would remove the message row the send is about to read.
				if (isDraftChatClaimedForSend(chatId)) continue;
				const { deleted } = await chatDB.deleteDraftOnlyChat(chatId, draftV);
				if (!deleted) continue;
				chatListCache.removeChat(chatId);
				chatMetadataCache.invalidateChat(chatId, 'delete');
				service.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id: chatId } }));
			} else {
				// Compare-and-clear: a draft saved after the probe has a newer
				// draft_v than `cleared_draft_v` and is kept by the draft merge.
				const saved = await chatDB.saveChatDraftFields(chatId, {
					encrypted_draft_md: null, encrypted_draft_preview: null, draft_v: 0, cleared_draft_v: draftV,
				});
				if (!saved || saved.draft_v !== 0) continue;
				chatMetadataCache.invalidateDraftProjection(chatId);
			}
			changed = true;
			console.info(`[ChatSyncService] Reconciled stale local draft for chat ${chatId} (${action})`);
		} catch (error) {
			// Per-chat IndexedDB failure: logged; the remaining chats still apply.
			console.error(`[ChatSyncService] Failed to reconcile stale local draft for chat ${chatId}:`, error);
		}
	}
	if (changed && typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT));
}
