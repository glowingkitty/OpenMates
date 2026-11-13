// @vitest-environment node
/**
 * `embedEdit` Worker unit marshalling (feature.embed-user-edits): result
 * mappers, one Enhance run per image (a second press joins it), frame wake-up,
 * borrow refusals and the core-read head passed to each commit. The core binding is a stub; the core's own behaviour is
 * covered by its crate tests.
 */
import { describe, expect, it, vi } from 'vitest';

import {
	createEmbedEditHandlers, EMBED_EDIT_BORROW_TIMEOUT_MS, EMBED_EDIT_USER_BORROW_TIMEOUT_MS, ENHANCE_MAX_BUSY_READS,
	enhanceResult, revisionResult, type EmbedEditDeps
} from '../embedEditUnit';
import type { CoreClientBorrow } from '../../drafts/coreClientBorrow';

const SIGNAL = new AbortController().signal;

const HEAD = { embed_id: 'e1', version_number: 2, encrypted_content: 'cipher', created_at: 1, hashed_chat_id: null };
const headRead = () => vi.fn(async (_handle: string, _generation: number, embedId: string) =>
	JSON.stringify({ head: { ...HEAD, embed_id: embedId }, chat_id: null }));

const committed = {
	commit: { committed: { version: 3, base_version: 2, encrypted_content: 'x', content_hash: 'h' }, cache_synchronized: true },
	event: { state: 'written' }
};

class Waker {
	frames: string[] = [];
	notify_frame(type: string, _payload: string): boolean {
		this.frames.push(type);
		return type === 'image_enhance_ready';
	}
	free() {}
}

const binding = {
	BrowserImageEnhanceWaker: Waker,
	embed_group_updated_events: (rows: string) => JSON.stringify((JSON.parse(rows) as unknown[]).map((_, index) => ({ kind: 'message', index })))
};

function setup(client: Record<string, unknown>, borrowed: CoreClientBorrow | 'none' | 'busy' | 'local' | null = null) {
	const release = vi.fn();
	let wake: (() => void) | null = null;
	const deps: EmbedEditDeps = {
		borrow: vi.fn(async () => borrowed ?? ({ client, status: { handle: 'h', generation: 1, principal: 'p' }, release } as unknown as CoreClientBorrow)),
		sleep: (_ms, woken) => new Promise<void>((resolve) => { wake = resolve; void woken.then(resolve); })
	};
	const handlers = createEmbedEditHandlers(binding, `p${Math.random()}`, deps, new AbortController().signal);
	return { handlers, release, deps, wakeTimer: () => wake?.() };
}

describe('embedEdit result mapping', () => {
	// contract-test: direct surface=gui.web assertions=embed-user-edits.edit.next-version
	it('keeps only the version, event and cache state of a committed revision', () => {
		expect(revisionResult(committed)).toEqual({ version: 3, base_version: 2, event: { state: 'written' }, cache_synchronized: true, content_hash: 'h' });
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.enhance.button,embed-user-edits.edit.next-version
	it('maps a saved Enhance and one saved earlier', () => {
		expect(enhanceResult({ state: 'committed', operation_id: 'op', outcome: committed }))
			.toEqual({ operation_id: 'op', version: 3, event: { state: 'written' } });
		expect(enhanceResult({ state: 'already_committed', operation_id: 'op', version: 4 })).toEqual({ operation_id: 'op', version: 4 });
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.event.chat-notice
	it('passes the written chat row through to the page', () => {
		const notice = { chat_id: 'chat', message_id: 'event', created_at: 1, content: '{"type":"embed_updated"}' };
		expect(revisionResult({ ...committed, notice }).notice).toEqual(notice);
		expect(enhanceResult({ state: 'committed', operation_id: 'op', outcome: { ...committed, notice } }).notice).toEqual(notice);
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.edit.next-version
	it('refuses an unknown shape', () => {
		expect(() => revisionResult({ commit: {} })).toThrow();
		expect(() => enhanceResult({ state: 'other', operation_id: 'op' })).toThrow();
	});
});

describe('embedEdit Enhance run', () => {
	const scope = { kind: 'chat', chat_id: 'chat-1' } as const;

	// contract-test: direct surface=gui.web assertions=embed-user-edits.enhance.button
	it('joins a second press to the running job and saves once when the ready frame arrives', async () => {
		let reads = 0;
		const client = {
			embed_user_edit_head: headRead(),
			start_image_enhance: vi.fn(async () => JSON.stringify({ operation_id: 'op-1', state: 'pending' })),
			wait_image_enhance: vi.fn(async () => {
				reads += 1;
				return JSON.stringify({ operation_id: 'op-1', state: 'ready' });
			}),
			save_image_enhance_result: vi.fn(async () => JSON.stringify({ state: 'committed', operation_id: 'op-1', outcome: committed }))
		};
		const { handlers, release } = setup(client);
		const first = handlers.enhanceImage({ embedId: 'e1', scope }, SIGNAL) as Promise<unknown>;
		const second = handlers.enhanceImage({ embedId: 'e1', scope }, SIGNAL) as Promise<unknown>;
		await vi.waitFor(() => expect(handlers.runningEnhance({ embedId: 'e1' }, SIGNAL)).toEqual({ operation_id: 'op-1', scope }));
		expect(handlers.enhanceFrame({ type: 'image_enhance_ready', payload: { operation_id: 'op-1' } }, SIGNAL)).toBe(true);
		await expect(first).resolves.toEqual({ operation_id: 'op-1', version: 3, event: { state: 'written' } });
		await expect(second).resolves.toEqual({ operation_id: 'op-1', version: 3, event: { state: 'written' } });
		expect(client.start_image_enhance).toHaveBeenCalledTimes(1);
		expect(client.save_image_enhance_result).toHaveBeenCalledTimes(1);
		expect(reads).toBe(1);
		expect(client.embed_user_edit_head).toHaveBeenCalledTimes(2);
		const head = JSON.stringify(HEAD);
		expect(client.start_image_enhance).toHaveBeenCalledWith('h', 1, 'e1', head, JSON.stringify(scope));
		expect(client.save_image_enhance_result).toHaveBeenCalledWith('h', 1, 'e1', head, JSON.stringify(scope), 'op-1');
		expect(release).toHaveBeenCalledTimes(3);
		expect(handlers.runningEnhance({ embedId: 'e1' }, SIGNAL)).toBeNull();
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.enhance.button
	it('keeps reading while the core says the job is pending and passes the core code of a failure', async () => {
		const client = {
			embed_user_edit_head: headRead(),
			start_image_enhance: vi.fn(async () => JSON.stringify({ operation_id: 'op-2', state: 'pending' })),
			wait_image_enhance: vi.fn()
				.mockRejectedValueOnce('enhance_timeout')
				.mockRejectedValueOnce('enhance_failed'),
			save_image_enhance_result: vi.fn()
		};
		const { handlers, wakeTimer } = setup(client);
		const run = handlers.enhanceImage({ embedId: 'e2', scope }, SIGNAL) as Promise<unknown>;
		await vi.waitFor(() => expect((handlers.runningEnhance({ embedId: 'e2' }, SIGNAL) as { operation_id: string | null } | null)?.operation_id).toBe('op-2'));
		wakeTimer();
		await vi.waitFor(() => expect(client.wait_image_enhance).toHaveBeenCalledTimes(1));
		wakeTimer();
		await expect(run).rejects.toMatchObject({ code: 'enhance_failed' });
		expect(client.save_image_enhance_result).not.toHaveBeenCalled();
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.event.project-edit-reaches-chat
	it('maps borrow refusals and hides non-code error text', async () => {
		const refused = setup({}, 'busy');
		await expect(refused.handlers.reconcileNotices({ chatId: 'c' }, SIGNAL) as Promise<unknown>).rejects.toMatchObject({ code: 'core_busy' });
		const leaky = setup({ reconcile_embed_update_notices: async () => { throw new Error('secret detail: key=abc'); } });
		await expect(leaky.handlers.reconcileNotices({ chatId: 'c' }, SIGNAL) as Promise<unknown>).rejects.toMatchObject({ code: 'embed_edit_failed' });
		expect(leaky.release).toHaveBeenCalledTimes(1);
		const local = setup({}, 'local');
		await expect(local.handlers.restoreVersion({ embedId: 'e', scope, restoredFrom: 1 }, SIGNAL) as Promise<unknown>)
			.rejects.toMatchObject({ code: 'local_session' });
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.edit.next-version,embed-user-edits.enhance.button
	it('waits longer for a busy core on a user-pressed write than on the chat-open reconcile', async () => {
		const { handlers, deps } = setup({
			embed_user_edit_head: headRead(),
			commit_embed_content_revision: vi.fn(async () => JSON.stringify(committed)),
			reconcile_embed_update_notices: vi.fn(async () => JSON.stringify({ written: 0 }))
		});
		await handlers.commitContentRevision({ embedId: 'e7', scope, baseVersion: 2, content: 'c' }, SIGNAL);
		await handlers.reconcileNotices({ chatId: 'c' }, SIGNAL);
		const bounds = (deps.borrow as ReturnType<typeof vi.fn>).mock.calls.map((call) => call[2]);
		expect(bounds).toEqual([EMBED_EDIT_USER_BORROW_TIMEOUT_MS, EMBED_EDIT_BORROW_TIMEOUT_MS]);
		expect(EMBED_EDIT_USER_BORROW_TIMEOUT_MS).toBeGreaterThan(EMBED_EDIT_BORROW_TIMEOUT_MS);
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.enhance.button
	it('reads a pending job again when the core stays busy, and gives up with core_busy only after the bound', async () => {
		const client = {
			embed_user_edit_head: headRead(),
			start_image_enhance: vi.fn(async () => JSON.stringify({ operation_id: 'op-3', state: 'pending' })),
			wait_image_enhance: vi.fn(async () => JSON.stringify({ operation_id: 'op-3', state: 'ready' })),
			save_image_enhance_result: vi.fn(async () => JSON.stringify({ state: 'committed', operation_id: 'op-3', outcome: committed }))
		};
		const lent = { client, status: { handle: 'h', generation: 1, principal: 'p' }, release: vi.fn() } as unknown as CoreClientBorrow;
		const borrow = vi.fn<EmbedEditDeps['borrow']>()
			.mockResolvedValueOnce(lent).mockResolvedValueOnce('busy').mockResolvedValueOnce('busy').mockResolvedValue(lent);
		const handlers = createEmbedEditHandlers(binding, `p${Math.random()}`, { borrow, sleep: async () => {} }, new AbortController().signal);
		await expect(handlers.enhanceImage({ embedId: 'e8', scope }, SIGNAL) as Promise<unknown>)
			.resolves.toEqual({ operation_id: 'op-3', version: 3, event: { state: 'written' } });
		expect(client.wait_image_enhance).toHaveBeenCalledTimes(1);
		expect(borrow.mock.calls.map((call) => call[2])).toEqual([EMBED_EDIT_USER_BORROW_TIMEOUT_MS, EMBED_EDIT_BORROW_TIMEOUT_MS,
			EMBED_EDIT_BORROW_TIMEOUT_MS, EMBED_EDIT_BORROW_TIMEOUT_MS, EMBED_EDIT_USER_BORROW_TIMEOUT_MS]);

		const stuck = vi.fn<EmbedEditDeps['borrow']>().mockResolvedValueOnce(lent).mockResolvedValue('busy');
		const blocked = createEmbedEditHandlers(binding, `p${Math.random()}`, { borrow: stuck, sleep: async () => {} }, new AbortController().signal);
		await expect(blocked.enhanceImage({ embedId: 'e9', scope }, SIGNAL) as Promise<unknown>).rejects.toMatchObject({ code: 'core_busy' });
		expect(stuck).toHaveBeenCalledTimes(1 + ENHANCE_MAX_BUSY_READS);
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.restore.creates-version
	it('refuses a restore of an invalid version before borrowing', async () => {
		const { handlers, release } = setup({ restore_embed_version: vi.fn() });
		await expect(handlers.restoreVersion({ embedId: 'e', scope, restoredFrom: 0 }, SIGNAL) as Promise<unknown>)
			.rejects.toMatchObject({ code: 'embed_edit_bad_version' });
		expect(release).not.toHaveBeenCalled();
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.restore.creates-version
	it('restores on the head the core read, with the core code when that read fails', async () => {
		const restore = vi.fn(async () => JSON.stringify(committed));
		const { handlers, release } = setup({ embed_user_edit_head: headRead(), restore_embed_version: restore });
		await expect(handlers.restoreVersion({ embedId: 'e3', scope, restoredFrom: 1 }, SIGNAL) as Promise<unknown>)
			.resolves.toEqual({ version: 3, base_version: 2, event: { state: 'written' }, cache_synchronized: true, content_hash: 'h' });
		expect(restore).toHaveBeenCalledWith('h', 1, 'e3', JSON.stringify({ ...HEAD, embed_id: 'e3' }), JSON.stringify(scope), 1);
		expect(release).toHaveBeenCalledTimes(1);
		const failing = setup({ embed_user_edit_head: vi.fn().mockRejectedValue('embed_key_unavailable'), restore_embed_version: restore });
		await expect(failing.handlers.restoreVersion({ embedId: 'e3', scope, restoredFrom: 1 }, SIGNAL) as Promise<unknown>)
			.rejects.toMatchObject({ code: 'embed_key_unavailable' });
		expect(restore).toHaveBeenCalledTimes(1);
		expect(failing.release).toHaveBeenCalledTimes(1);
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.edit.next-version,embed-user-edits.event.chat-notice
	it('commits a content edit on the head the core read, with the version the edit was made on', async () => {
		const commit = vi.fn(async () => JSON.stringify(committed));
		const { handlers, release } = setup({ embed_user_edit_head: headRead(), commit_embed_content_revision: commit });
		await expect(handlers.commitContentRevision({ embedId: 'e4', scope, baseVersion: 2, content: 'title: Plan v3' }, SIGNAL) as Promise<unknown>)
			.resolves.toEqual({ version: 3, base_version: 2, event: { state: 'written' }, cache_synchronized: true, content_hash: 'h' });
		expect(commit).toHaveBeenCalledWith('h', 1, 'e4', JSON.stringify({ ...HEAD, embed_id: 'e4' }), 2, JSON.stringify(scope), 'title: Plan v3');
		expect(release).toHaveBeenCalledTimes(1);
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.event.project-edit-reaches-chat
	it('commits a Projects workspace edit in Project scope so the core writes the event into the embed chat', async () => {
		const commit = vi.fn(async () => JSON.stringify({ ...committed, event: { state: 'no_chat' } }));
		const project = { kind: 'project', project_id: 'project-1' } as const;
		const { handlers } = setup({ embed_user_edit_head: headRead(), commit_embed_content_revision: commit });
		await expect(handlers.commitContentRevision({ embedId: 'e5', scope: project, baseVersion: 2, content: 'c' }, SIGNAL) as Promise<unknown>)
			.resolves.toMatchObject({ version: 3, event: { state: 'no_chat' } });
		expect(commit).toHaveBeenCalledWith('h', 1, 'e5', JSON.stringify({ ...HEAD, embed_id: 'e5' }), 2, JSON.stringify(project), 'c');
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.edit.next-version
	it('passes the core conflict code through and refuses a bad request before borrowing', async () => {
		const commit = vi.fn().mockRejectedValue('embed_version_conflict');
		const { handlers, release } = setup({ embed_user_edit_head: headRead(), commit_embed_content_revision: commit });
		await expect(handlers.commitContentRevision({ embedId: 'e6', scope, baseVersion: 1, content: 'c' }, SIGNAL) as Promise<unknown>)
			.rejects.toMatchObject({ code: 'embed_version_conflict' });
		expect(release).toHaveBeenCalledTimes(1);
		await expect(handlers.commitContentRevision({ embedId: 'e6', scope, baseVersion: 0, content: 'c' }, SIGNAL) as Promise<unknown>)
			.rejects.toMatchObject({ code: 'embed_edit_bad_version' });
		await expect(handlers.commitContentRevision({ embedId: 'e6', scope, baseVersion: 1, content: '' }, SIGNAL) as Promise<unknown>)
			.rejects.toMatchObject({ code: 'embed_edit_bad_content' });
		expect(release).toHaveBeenCalledTimes(1);
		expect(commit).toHaveBeenCalledTimes(1);
	});
});
