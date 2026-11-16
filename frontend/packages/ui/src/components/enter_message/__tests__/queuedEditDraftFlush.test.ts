import { describe, expect, it } from 'vitest';
import { queuedEditFlushDisposition } from '../queuedEditDraftFlush';

describe('queuedEditFlushDisposition', () => {
	// contract-test: supporting surface=gui.web assertions=chat-queued-followups.editing.cancel
	it('continues when the flush persisted the draft', () => {
		expect(queuedEditFlushDisposition({ flushed: true, editorStillCurrent: true, chatStillCurrent: true }))
			.toEqual({ action: 'continue' });
	});
	// contract-test: supporting surface=gui.web assertions=chat-queued-followups.editing.cancel
	it('keeps Edit open when the flush could not persist but the chat is current (Cancel restores the snapshot)', () => {
		expect(queuedEditFlushDisposition({ flushed: false, editorStillCurrent: true, chatStillCurrent: true }))
			.toEqual({ action: 'continue-unpersisted', reason: 'draft_flush_not_persisted' });
	});
	// contract-test: supporting surface=gui.web assertions=chat-queued-followups.editing.cancel
	it('aborts when the editor or chat changed during the flush', () => {
		expect(queuedEditFlushDisposition({ flushed: true, editorStillCurrent: false, chatStillCurrent: true }).action).toBe('abort');
		expect(queuedEditFlushDisposition({ flushed: false, editorStillCurrent: true, chatStillCurrent: false }).action).toBe('abort');
	});
});
