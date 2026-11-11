// Stale-draft reconnect adapter: probe gathering and version-guarded IndexedDB writes.
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';

const calls: Array<{ op: string; payload: unknown }> = [];
let probeResponse: unknown = { wire: [], probe: [] };
let planResponse: unknown = [];
vi.mock('../sync/syncUnitClient', () => ({
	syncCall: vi.fn(async (op: string, payload: unknown) => {
		calls.push({ op, payload });
		return op === 'staleDraftProbe' ? probeResponse : planResponse;
	}),
}));

const rows: Record<string, Record<string, unknown>> = {};
const chatDB = {
	getOfflineChanges: vi.fn(async () => [{ chat_id: 'queued-chat' }]),
	getRawChat: vi.fn(async (chatId: string) => rows[chatId] ?? null),
	deleteDraftOnlyChat: vi.fn(async () => ({ deleted: true, deletedEmbedIds: [] })),
	saveChatDraftFields: vi.fn(async () => ({ draft_v: 0 })),
};
vi.mock('../../db', () => ({ chatDB }));
const removeChat = vi.fn();
vi.mock('../../chatListCache', () => ({ chatListCache: { removeChat } }));
vi.mock('../../chatMetadataCache', () => ({
	chatMetadataCache: { invalidateChat: vi.fn(), invalidateDraftProjection: vi.fn() },
}));
const editor = writable({ currentChatId: null as string | null, hasUnsavedChanges: false });
vi.mock('../../drafts/draftState', () => ({ draftEditorUIState: editor }));
vi.mock('../../drafts/draftConstants', () => ({ LOCAL_CHAT_LIST_CHANGED_EVENT: 'local-chat-list-changed' }));

type Adapter = typeof import('../sync/rustStaleDraftReconcile');
let buildStaleDraftProbe: Adapter['buildStaleDraftProbe'];
let applyStaleDraftProbeResult: Adapter['applyStaleDraftProbeResult'];
beforeAll(async () => {
	({ buildStaleDraftProbe, applyStaleDraftProbeResult } = await import('../sync/rustStaleDraftReconcile'));
});

const service = { dispatchEvent: vi.fn() } as unknown as Parameters<Adapter['applyStaleDraftProbeResult']>[0];
const probeEntry = { chatId: 'stale-chat', draftV: 3, draftOnly: true };

describe('stale draft reconcile adapter', () => {
	beforeEach(() => {
		calls.length = 0;
		vi.clearAllMocks();
		editor.set({ currentChatId: null, hasUnsavedChanges: false });
		rows['stale-chat'] = { chat_id: 'stale-chat', draft_v: 3, encrypted_draft_md: 'cipher', encrypted_chat_key: 'key' };
		probeResponse = { wire: [{ chat_id: 'stale-chat', draft_v: 3 }], probe: [probeEntry] };
		planResponse = [{ chatId: 'stale-chat', action: 'delete_draft_only', draftV: 3 }];
	});

	// contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
	it('never probes in a Team context', async () => {
		expect(await buildStaleDraftProbe('team-1', 1, [['stale-chat', 3]], new Set())).toBeUndefined();
		expect(calls).toEqual([]);
	});

	// contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
	it('sends projected rows plus queued and pending-deletion ids to the core', async () => {
		const wire = await buildStaleDraftProbe(null, 7, [['stale-chat', 3], ['no-draft', 0]], new Set(['deleting']));
		expect(wire).toEqual([{ chat_id: 'stale-chat', draft_v: 3 }]);
		const probe = calls[0].payload as { rows: Array<Record<string, unknown>>; pendingChatIds: string[] };
		expect(chatDB.getRawChat).toHaveBeenCalledTimes(1);
		expect(probe.rows[0].encrypted_chat_key).toBeUndefined();
		expect(probe.pendingChatIds.sort()).toEqual(['deleting', 'queued-chat']);
	});

	// contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
	it('deletes with the probed version guard and ignores replies for another epoch', async () => {
		await buildStaleDraftProbe(null, 7, [['stale-chat', 3]], new Set());
		await applyStaleDraftProbeResult(service, { context_epoch: 8, stale_draft_probe_result: {} });
		expect(chatDB.deleteDraftOnlyChat).not.toHaveBeenCalled();

		await buildStaleDraftProbe(null, 7, [['stale-chat', 3]], new Set());
		await applyStaleDraftProbeResult(service, { context_epoch: 7, stale_draft_probe_result: {} });
		expect(chatDB.deleteDraftOnlyChat).toHaveBeenCalledWith('stale-chat', 3);
		expect(removeChat).toHaveBeenCalledWith('stale-chat');
	});

	// contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
	it('clears with compare-and-clear and leaves an editor with unsaved changes alone', async () => {
		planResponse = [{ chatId: 'stale-chat', action: 'clear_draft', draftV: 3 }];
		editor.set({ currentChatId: 'stale-chat', hasUnsavedChanges: true });
		await buildStaleDraftProbe(null, 7, [['stale-chat', 3]], new Set());
		await applyStaleDraftProbeResult(service, { context_epoch: 7, stale_draft_probe_result: {} });
		expect(chatDB.saveChatDraftFields).not.toHaveBeenCalled();

		editor.set({ currentChatId: null, hasUnsavedChanges: false });
		await buildStaleDraftProbe(null, 7, [['stale-chat', 3]], new Set());
		await applyStaleDraftProbeResult(service, { context_epoch: 7, stale_draft_probe_result: {} });
		expect(chatDB.saveChatDraftFields).toHaveBeenCalledWith('stale-chat', {
			encrypted_draft_md: null, encrypted_draft_preview: null, draft_v: 0, cleared_draft_v: 3,
		});
	});
});
