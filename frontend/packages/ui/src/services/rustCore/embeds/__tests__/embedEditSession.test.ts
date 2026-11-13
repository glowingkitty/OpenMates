// @vitest-environment node
/**
 * Page client of the `embedEdit` unit (feature.embed-user-edits): a write the
 * unit refuses because the page's history session is still the local-only
 * admission asks for the existing server-checked upgrade (serverSessionRegistry)
 * and is sent once more; every other refusal, a missing upgrade hook and a
 * failed or timed-out upgrade keep the original refusal (the editors show their
 * error state). The upgrade waits for this page's running streamed-embed
 * writes; the chat-open reconcile never upgrades and runs after a later
 * admission. The Worker and the admission are stubs.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
	RECONCILE_DEFERRED, reconcileOrDefer, SERVER_SESSION_RETRY_BUDGET_MS, SERVER_SESSION_TIMEOUT_MS, showEventNotice,
	withServerSession
} from '../embedEditSession';
import {
	ensureServerCheckedSession, notifyServerCheckedSession, onceServerCheckedSession, registerServerCheckedSession
} from '../../host/serverSessionRegistry';
import { withCanonicalEmbedWrite } from '../../../canonicalEmbedWriteCoordinator';
import { UnitPortError } from '../../host/unitPort';

const SAVED = { version: 3, base_version: 2, event: { state: 'written' }, cache_synchronized: true };

afterEach(() => { vi.useRealTimers(); });

describe('withServerSession', () => {
	// contract-test: direct surface=gui.web assertions=embed-user-edits.edit.next-version,embed-user-edits.enhance.button
	it('upgrades a local-only session once and resends the refused write', async () => {
		const send = vi.fn().mockRejectedValueOnce(new UnitPortError('local_session')).mockResolvedValueOnce(SAVED);
		const ensure = vi.fn(async () => true);
		await expect(withServerSession(send, ensure)).resolves.toEqual(SAVED);
		expect(ensure).toHaveBeenCalledWith(SERVER_SESSION_TIMEOUT_MS);
		expect(send).toHaveBeenCalledTimes(2);
		const unbound = vi.fn().mockRejectedValueOnce(new UnitPortError('not_admitted')).mockResolvedValueOnce(SAVED);
		await expect(withServerSession(unbound, async () => true)).resolves.toEqual(SAVED);
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.edit.next-version
	it('keeps the refusal when the upgrade is missing, fails, or the resend is refused again', async () => {
		const refused = () => vi.fn().mockRejectedValue(new UnitPortError('local_session'));
		await expect(withServerSession(refused(), async () => false)).rejects.toMatchObject({ code: 'local_session' });
		await expect(withServerSession(refused(), async () => { throw new Error('session_expired'); }))
			.rejects.toMatchObject({ code: 'local_session' });
		const twice = refused();
		await expect(withServerSession(twice, async () => true)).rejects.toMatchObject({ code: 'local_session' });
		expect(twice).toHaveBeenCalledTimes(2);
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.edit.next-version
	it('gives the resend only what is left of the retry budget, never the full port timeout', async () => {
		const send = vi.fn().mockRejectedValueOnce(new UnitPortError('local_session')).mockResolvedValueOnce(SAVED);
		await expect(withServerSession(send, async () => true)).resolves.toEqual(SAVED);
		expect(send.mock.calls[0]).toEqual([]);
		const resendTimeout = send.mock.calls[1][0] as number;
		expect(resendTimeout).toBeGreaterThan(0);
		expect(resendTimeout).toBeLessThanOrEqual(SERVER_SESSION_RETRY_BUDGET_MS);
		expect(SERVER_SESSION_TIMEOUT_MS).toBeLessThan(SERVER_SESSION_RETRY_BUDGET_MS);
		expect(SERVER_SESSION_RETRY_BUDGET_MS).toBeLessThan(45_000);
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.edit.next-version
	it('never upgrades or resends for any other refusal', async () => {
		const send = vi.fn().mockRejectedValue(new UnitPortError('embed_version_conflict'));
		const ensure = vi.fn(async () => true);
		await expect(withServerSession(send, ensure)).rejects.toMatchObject({ code: 'embed_version_conflict' });
		expect(ensure).not.toHaveBeenCalled();
		expect(send).toHaveBeenCalledTimes(1);
	});
});

describe('showEventNotice', () => {
	const notice = { chat_id: 'chat', message_id: 'event', created_at: 1, content: '{"type":"embed_updated"}' };

	// contract-test: direct surface=gui.web assertions=embed-user-edits.event.chat-notice
	it('hands a written event row to the open chat', async () => {
		const dispatch = vi.fn(async () => undefined);
		await showEventNotice({ event: { state: 'written' }, notice }, dispatch);
		expect(dispatch).toHaveBeenCalledWith(notice);
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.event.chat-notice
	it('logs only the stable code of a deferred event and shows no row', async () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
		const dispatch = vi.fn(async () => undefined);
		await showEventNotice({ event: { state: 'deferred', code: 'chat_key_unavailable' } }, dispatch);
		expect(dispatch).not.toHaveBeenCalled();
		expect(warn).toHaveBeenCalledWith(expect.any(String), 'chat_key_unavailable');
		warn.mockRestore();
	});
});

describe('upgrade ordering and deferred reconcile', () => {
	// contract-test: direct surface=gui.web assertions=embed-user-edits.edit.next-version
	it('starts the upgrade of a user write only after the running streamed-embed writes settled', async () => {
		let finishWrite: () => void = () => {};
		const write = withCanonicalEmbedWrite('streaming-embed', () => new Promise<void>((resolve) => { finishWrite = resolve; }));
		const admit = vi.fn(async () => {});
		const stop = registerServerCheckedSession(admit);
		const send = vi.fn().mockRejectedValueOnce(new UnitPortError('local_session')).mockResolvedValueOnce(SAVED);
		const saving = withServerSession(send);
		await new Promise((resolve) => setTimeout(resolve, 10));
		expect(admit).not.toHaveBeenCalled();
		finishWrite();
		await write;
		await expect(saving).resolves.toEqual(SAVED);
		expect(admit).toHaveBeenCalledTimes(1);
		stop();
	});

	// contract-test: direct surface=gui.web assertions=embed-user-edits.event.project-edit-reaches-chat
	it('defers the chat-open reconcile on a local session without an upgrade and runs it after the next admission', async () => {
		const admit = vi.fn(async () => {});
		const stop = registerServerCheckedSession(admit);
		const report = { written: 1, already_present: 0, unresolved: [] };
		const send = vi.fn().mockRejectedValueOnce(new UnitPortError('local_session'))
			.mockRejectedValueOnce(new UnitPortError('not_admitted')).mockResolvedValue(report);
		await expect(reconcileOrDefer('chat-a', send, onceServerCheckedSession)).resolves.toMatchObject({ deferred: RECONCILE_DEFERRED });
		await expect(reconcileOrDefer('chat-b', send, onceServerCheckedSession)).resolves.toMatchObject({ deferred: RECONCILE_DEFERRED });
		expect(admit).not.toHaveBeenCalled();
		notifyServerCheckedSession();
		await vi.waitFor(() => expect(send).toHaveBeenCalledTimes(4));
		expect(send.mock.calls.slice(2).map((call) => call[0]).sort()).toEqual(['chat-a', 'chat-b']);
		await expect(reconcileOrDefer('chat-c', vi.fn().mockRejectedValue(new UnitPortError('forbidden'))))
			.rejects.toMatchObject({ code: 'forbidden' });
		stop();
	});
});

describe('serverSessionRegistry', () => {
	// contract-test: direct surface=gui.web assertions=embed-user-edits.edit.next-version
	it('runs the registered upgrade, reports a missing one and bounds a stuck one', async () => {
		await expect(ensureServerCheckedSession(1_000)).resolves.toBe(false);
		const admit = vi.fn(async () => {});
		const unregister = registerServerCheckedSession(admit);
		await expect(ensureServerCheckedSession(1_000)).resolves.toBe(true);
		expect(admit).toHaveBeenCalledTimes(1);
		unregister();
		await expect(ensureServerCheckedSession(1_000)).resolves.toBe(false);

		vi.useFakeTimers();
		const stop = registerServerCheckedSession(() => new Promise<void>(() => {}));
		const stuck = ensureServerCheckedSession(500);
		const settled = expect(stuck).rejects.toThrow('server_session_timeout');
		await vi.advanceTimersByTimeAsync(500);
		await settled;
		stop();
	});
});
