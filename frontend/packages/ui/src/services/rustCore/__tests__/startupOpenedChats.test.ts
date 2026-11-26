import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { invalidateWorkspaceCaches } from '../../workspaceCacheLifecycle';
import { cancelOpenedChatStartup, reportOpenedChatFrame, installOpenedChatStartup, offerOpenedChatStartup, suspendOpenedChatStartup } from '../startupOpenedChats';

const mock = vi.hoisted(() => ({ persistCall: vi.fn() }));
vi.mock('../persist/persistUnitClient', () => mock);
vi.mock('../../../stores/teamStore', () => ({ isActiveTeamContext: () => true }));

const scope = { teamId: null, contextEpoch: 7 };
const latest = { direction: 'latest', limit: 20, respectCompressionBoundary: false };
const planFor = (chatIds: string[], latestChatIds = chatIds) => ({ chatIds, latestChatIds, selector: latest, pageBudget: 10 });
const cursor = { chatId: 'recent', scope: 'scope', createdAt: 5, messageId: 'message' };
const before = { direction: 'before', cursor, limit: 20, respectCompressionBoundary: false };
const complete = {
	start: null, hasMoreBefore: false, hasMoreAfter: false, rowsConfirmed: true, retainedRows: 5, serverMessageCount: null, messagesVersion: 12,
};

describe('opened chat startup platform', () => {
	let dispose: (() => void) | undefined;
	let connection = 0;
	beforeEach(() => {
		connection += 10;
		invalidateWorkspaceCaches();
		mock.persistCall.mockReset();
	});
	afterEach(() => dispose?.());

	// contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
	it('reads the offered head first, follows Rust cursor plans, and reports counts only', async () => {
		mock.persistCall.mockResolvedValueOnce(planFor(['recent', 'previous']))
			.mockResolvedValueOnce({ done: false, selector: before })
			.mockResolvedValueOnce({ done: true, selector: null })
			.mockResolvedValueOnce({ done: true, selector: null });
		const read = vi.fn().mockResolvedValueOnce({ ...complete, start: cursor, hasMoreBefore: true })
			.mockResolvedValue(complete);
		const resume = vi.fn();
		const coverage = vi.fn();
		const close = vi.fn();
		dispose = installOpenedChatStartup({ prepare: async () => ({ read, close }), resume, coverage });

		await offerOpenedChatStartup(['recent', 'previous'], scope, connection);

		expect(resume).toHaveBeenCalledWith('recent', scope);
		expect(read.mock.calls).toEqual([['recent', latest], ['recent', before], ['previous', latest]]);
		expect(coverage.mock.calls).toEqual([
			[{ newestTail: true, completeChats: 0, requestedChats: 2 }],
			[{ newestTail: true, completeChats: 1, requestedChats: 2 }],
			[{ newestTail: true, completeChats: 2, requestedChats: 2 }],
		]);
		expect(close).toHaveBeenCalledOnce();
	});

	// contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
	it('retains an authenticated priority frame delivered before the Worker adapter installs', async () => {
		mock.persistCall.mockResolvedValueOnce(planFor(['recent']))
			.mockResolvedValueOnce({ done: true, selector: null });
		const coverage = vi.fn();
		const read = vi.fn().mockResolvedValue(complete);
		await offerOpenedChatStartup(['recent'], scope, connection);
		expect(mock.persistCall).not.toHaveBeenCalled();

		dispose = installOpenedChatStartup({ prepare: async () => ({ read, close: vi.fn() }), coverage });

		await vi.waitFor(() => expect(coverage).toHaveBeenCalledWith({
			newestTail: true, completeChats: 1, requestedChats: 1,
		}));
	});

	// contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
	it('drops a late read and resumes the unfinished cohort after explicit navigation', async () => {
		const plan = planFor(['recent']);
		mock.persistCall.mockResolvedValueOnce(plan).mockResolvedValueOnce(plan)
			.mockResolvedValueOnce({ done: true, selector: null });
		const coverage = vi.fn();
		const close = vi.fn();
		const resume = vi.fn();
		const read = vi.fn().mockImplementationOnce(async () => {
			cancelOpenedChatStartup();
			return complete;
		}).mockResolvedValue(complete);
		dispose = installOpenedChatStartup({ prepare: async () => ({ read, close }), coverage, resume });

		await expect(offerOpenedChatStartup(['recent'], scope, connection)).rejects.toThrow('cancelled');
		expect(coverage).not.toHaveBeenCalled();
		await vi.waitFor(() => expect(coverage).toHaveBeenCalledOnce());
		await offerOpenedChatStartup(['recent'], scope, connection);
		expect(read).toHaveBeenCalledTimes(2);
		expect(resume).toHaveBeenCalledOnce();
		expect(close).toHaveBeenCalledTimes(2);
	});

	// contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
	it('resumes a partial same-workspace offer only on the reconnected socket', async () => {
		const plan = planFor(['recent']);
		const older = { ...cursor, createdAt: 3, messageId: 'older' };
		const oldBoundary = { ...before, cursor: older };
		const rebound = { ...before, cursor: { ...older, scope: 'replacement-lease' } };
		const tail = { ...complete, start: cursor, hasMoreBefore: true };
		mock.persistCall.mockResolvedValueOnce(plan)
			.mockResolvedValueOnce({ done: false, selector: before })
			.mockResolvedValueOnce({ done: false, selector: oldBoundary })
			.mockResolvedValueOnce(plan)
			.mockResolvedValueOnce({ done: false, selector: rebound, reusedRows: 10 })
			.mockResolvedValueOnce({ done: true, selector: null });
		const read = vi.fn()
			.mockResolvedValueOnce(tail)
			.mockResolvedValueOnce({ ...tail, start: older })
			.mockImplementationOnce(async () => {
				suspendOpenedChatStartup(connection);
				throw new Error('cancelled');
			})
			.mockResolvedValueOnce({ ...tail, start: { ...cursor, scope: 'replacement-lease' } })
			.mockResolvedValueOnce(complete);
		const prepare = vi.fn(async () => ({ read, close: vi.fn() }));
		const resume = vi.fn();
		dispose = installOpenedChatStartup({ prepare, resume });

		await expect(offerOpenedChatStartup(['recent'], scope, connection)).rejects.toThrow('cancelled');
		await offerOpenedChatStartup(['recent'], scope, connection);
		expect(prepare).toHaveBeenCalledOnce();

		await offerOpenedChatStartup(['recent'], scope, connection + 1);
		expect(read.mock.calls).toEqual([
			['recent', latest], ['recent', before], ['recent', oldBoundary],
			['recent', latest], ['recent', rebound],
		]);
		expect(mock.persistCall.mock.calls[4][1].progress).toMatchObject({
			pagesRead: 1, confirmedCoverage: { cursor: older, messagesVersion: 12, retainedRows: 10 },
		});
		expect(mock.persistCall.mock.calls[5][1].progress).toMatchObject({
			pagesRead: 2, previous: rebound.cursor, expectedVersion: 12, retainedRows: 15,
		});
		expect(prepare).toHaveBeenCalledTimes(2);
		expect(resume).toHaveBeenCalledOnce();
	});

	// contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
	it('keeps the last acknowledged boundary at the lease budget and resumes on a new socket', async () => {
		const plan = { ...planFor(['recent']), pageBudget: 1 };
		const tail = { ...complete, start: cursor, hasMoreBefore: true };
		const rebound = { ...before, cursor: { ...cursor, scope: 'replacement' } };
		mock.persistCall.mockResolvedValueOnce(plan)
			.mockResolvedValueOnce({ done: false, selector: before })
			.mockResolvedValueOnce(plan)
			.mockResolvedValueOnce({ done: false, selector: rebound, reusedRows: 5 });
		const read = vi.fn().mockResolvedValueOnce(tail)
			.mockResolvedValueOnce({ ...tail, start: rebound.cursor });
		dispose = installOpenedChatStartup({ prepare: async () => ({ read, close: vi.fn() }) });

		await offerOpenedChatStartup(['recent'], scope, connection);
		await offerOpenedChatStartup(['recent'], scope, connection);
		expect(read.mock.calls).toEqual([['recent', latest]]);
		suspendOpenedChatStartup(connection);
		await offerOpenedChatStartup(['recent'], scope, connection + 1);

		expect(read.mock.calls).toEqual([['recent', latest], ['recent', latest]]);
		expect(mock.persistCall.mock.calls[3][1].progress).toMatchObject({
			pagesRead: 1, confirmedCoverage: { cursor, messagesVersion: 12, retainedRows: 5 },
		});
	});

	// contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases,chat-navigation.open.local-first-coherent
	it('refreshes a promoted cross-device head without replaying confirmed older chats', async () => {
		const completed = { done: true, selector: null };
		mock.persistCall
			.mockResolvedValueOnce(planFor(['recent', 'previous']))
			.mockResolvedValueOnce(completed).mockResolvedValueOnce(completed)
			.mockResolvedValueOnce(planFor(['previous', 'recent', 'new'], ['previous', 'new']))
			.mockResolvedValueOnce({ ...completed, reusedRows: 5 }).mockResolvedValueOnce(completed)
			.mockResolvedValueOnce(planFor(['new', 'previous', 'recent'], ['new']))
			.mockResolvedValueOnce(completed);
		const read = vi.fn()
			.mockResolvedValueOnce(complete)
			.mockResolvedValueOnce(complete)
			.mockResolvedValueOnce({
				...complete, start: { ...cursor, chatId: 'previous' },
				hasMoreBefore: true, retainedRows: 2, serverMessageCount: 5,
			})
			.mockResolvedValue(complete);
		const resume = vi.fn();
		dispose = installOpenedChatStartup({ prepare: async () => ({ read, close: vi.fn() }), resume });
		await offerOpenedChatStartup(['recent', 'previous'], scope, connection);
		await offerOpenedChatStartup(['previous', 'recent', 'new'], scope, connection);

		expect(read.mock.calls).toEqual([
			['recent', latest], ['previous', latest], ['previous', latest], ['new', latest],
		]);
		expect(mock.persistCall.mock.calls[4][1].progress.confirmedCoverage).toEqual({
			cursor: null, messagesVersion: 12, retainedRows: 5,
		});
		expect(resume.mock.calls).toEqual([['recent', scope], ['previous', scope]]);

		cancelOpenedChatStartup();
		await offerOpenedChatStartup(['new', 'previous', 'recent'], scope, connection + 1, {
			new: 13, previous: 12, recent: 12,
		});
		expect(read.mock.calls.at(-1)).toEqual(['new', latest]);
		expect(resume).toHaveBeenCalledTimes(2);
	});

	// contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
	it('keeps background reads suspended through a stale paint until the selected view renders', async () => {
		mock.persistCall.mockResolvedValueOnce(planFor(['recent']))
			.mockResolvedValueOnce({ done: true, selector: null });
		const read = vi.fn().mockResolvedValue(complete);
		dispose = installOpenedChatStartup({ prepare: async () => ({ read, close: vi.fn() }) });
		cancelOpenedChatStartup('selected');
		await offerOpenedChatStartup(['recent'], scope, connection);
		reportOpenedChatFrame('previous');
		expect(read).not.toHaveBeenCalled();
		reportOpenedChatFrame('selected');
		await vi.waitFor(() => expect(read).toHaveBeenCalledOnce());
	});

	// contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
	it('keeps a completed matching offer idle through repeated delivery and reconnect', async () => {
		mock.persistCall.mockResolvedValueOnce(planFor(['recent']))
			.mockResolvedValueOnce({ done: true, selector: null })
			.mockResolvedValueOnce(planFor(['recent'], []));
		const read = vi.fn().mockResolvedValue(complete);
		const prepare = vi.fn(async () => ({ read, close: vi.fn() }));
		const resume = vi.fn();
		dispose = installOpenedChatStartup({ prepare, resume });

		const versions = { recent: 12 };
		await offerOpenedChatStartup(['recent'], scope, connection, versions);
		await offerOpenedChatStartup(['recent'], scope, connection, versions);
		suspendOpenedChatStartup(connection);
		await offerOpenedChatStartup(['recent'], scope, connection + 1, versions);

		expect(mock.persistCall).toHaveBeenCalledTimes(3);
		expect(mock.persistCall).toHaveBeenLastCalledWith('startupOpened', {
			kind: 'begin', ids: ['recent'], messagesVersions: versions, refreshHead: false,
			complete: { recent: { messagesVersion: 12, verifiedOnConnection: false } },
		});
		expect(prepare).toHaveBeenCalledOnce();
		expect(resume).toHaveBeenCalledOnce();
	});

	// contract-test: supporting surface=gui.web assertions=sync.startup.opened-offline-and-archive,chat-navigation.open.local-first-coherent
	it('refreshes changed and missing versions in opened order after reconnect', async () => {
		const ids = ['recent', 'changed', 'missing', 'matching'];
		const done = { done: true, selector: null };
		mock.persistCall.mockResolvedValueOnce(planFor(ids))
			.mockResolvedValueOnce(done).mockResolvedValueOnce(done).mockResolvedValueOnce(done).mockResolvedValueOnce(done)
			.mockResolvedValueOnce(planFor(ids, ['recent', 'changed', 'missing']))
			.mockResolvedValueOnce(done).mockResolvedValueOnce(done)
			.mockResolvedValueOnce({ ...done, reusedRows: 5 });
		const read = vi.fn()
			.mockResolvedValueOnce(complete).mockResolvedValueOnce(complete)
			.mockResolvedValueOnce(complete).mockResolvedValueOnce(complete)
			.mockResolvedValueOnce({ ...complete, messagesVersion: 13 })
			.mockResolvedValueOnce({ ...complete, messagesVersion: 19 })
			.mockResolvedValueOnce({
				...complete, start: { ...cursor, chatId: 'missing' },
				hasMoreBefore: true, retainedRows: 2, serverMessageCount: 5,
			});
		const resume = vi.fn();
		dispose = installOpenedChatStartup({ prepare: async () => ({ read, close: vi.fn() }), resume });

		await offerOpenedChatStartup(ids, scope, connection);
		cancelOpenedChatStartup();
		suspendOpenedChatStartup(connection);
		const versions = { recent: 13, changed: 19, matching: 12 };
		await offerOpenedChatStartup(ids, scope, connection + 1, versions);

		expect(read.mock.calls.slice(4)).toEqual([['recent', latest], ['changed', latest], ['missing', latest]]);
		expect(mock.persistCall.mock.calls[5][1]).toMatchObject({ messagesVersions: versions });
		expect(mock.persistCall.mock.calls[8][1].progress).toMatchObject({
			messagesVersion: 12,
			confirmedCoverage: { cursor: null, messagesVersion: 12, retainedRows: 5 },
		});
		expect(resume).toHaveBeenCalledOnce();
	});

	// contract-test: supporting surface=gui.web assertions=sync.startup.opened-offline-and-archive
	it('does not prepare a transcript reader when a matching durable receipt is restored', async () => {
		const ids = ['recent'];
		mock.persistCall.mockResolvedValueOnce(planFor(ids, []));
		const prepare = vi.fn();
		const loadReceipts = vi.fn(async () => new Map([['recent', {
			revision: 'confirmed', encryptedChatKey: 'wrapped', completion: { messagesVersion: 12, retainedRows: 5 },
		}]]));
		const coverage = vi.fn();
		dispose = installOpenedChatStartup({ prepare, loadReceipts, coverage });

		await offerOpenedChatStartup(ids, scope, connection, { recent: 12 });

		expect(loadReceipts).toHaveBeenCalledOnce();
		expect(prepare).not.toHaveBeenCalled();
		expect(mock.persistCall).toHaveBeenCalledWith('startupOpened', {
			kind: 'begin', ids, messagesVersions: { recent: 12 }, refreshHead: false,
			complete: { recent: { messagesVersion: 12, verifiedOnConnection: false } },
		});
		expect(coverage).toHaveBeenCalledWith({ newestTail: true, completeChats: 1, requestedChats: 1 });
	});

	// contract-test: supporting surface=gui.web assertions=sync.startup.opened-offline-and-archive
	it('refuses completion when a foreign committed change interrupts the page chain', async () => {
		mock.persistCall.mockResolvedValueOnce(planFor(['recent']))
			.mockResolvedValueOnce({ done: false, selector: before });
		const read = vi.fn()
			.mockResolvedValueOnce({
				...complete, start: cursor, hasMoreBefore: true,
				witness: { before: null, after: 'first-write', encryptedChatKey: 'wrapped' },
			})
			.mockResolvedValueOnce({
				...complete, witness: { before: 'foreign-write', after: 'second-write', encryptedChatKey: 'wrapped' },
			});
		const saveReceipt = vi.fn();
		dispose = installOpenedChatStartup({ prepare: async () => ({ read, close: vi.fn() }), saveReceipt });

		await offerOpenedChatStartup(['recent'], scope, connection);

		expect(read.mock.calls).toEqual([['recent', latest], ['recent', before]]);
		expect(saveReceipt).not.toHaveBeenCalled();
		expect(mock.persistCall).toHaveBeenCalledTimes(2);
	});

	// contract-test: supporting surface=gui.web assertions=auth.session.isolation,sync.startup.bounded-phases
	it('clears buffered offers on workspace invalidation and Worker adapter disposal', async () => {
		await offerOpenedChatStartup(['recent'], scope, connection);
		invalidateWorkspaceCaches();
		const prepare = vi.fn();
		const resume = vi.fn();
		dispose = installOpenedChatStartup({ prepare, resume });
		expect(mock.persistCall).not.toHaveBeenCalled();

		const release = installOpenedChatStartup({ prepare, resume });
		const abandoned = offerOpenedChatStartup(['previous'], scope, connection + 1);
		release();
		await expect(abandoned).rejects.toThrow('cancelled');
		dispose = installOpenedChatStartup({ prepare, resume });

		expect(prepare).not.toHaveBeenCalled();
		expect(resume).not.toHaveBeenCalled();
		expect(mock.persistCall).not.toHaveBeenCalled();
	});
});
