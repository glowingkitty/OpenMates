/**
 * Decides whether entering a queued edit may continue after the ordinary draft
 * flush. The flush persists the independent composer draft before it is
 * replaced; the in-memory snapshot (restored by Cancel) is the owner of that
 * draft, so a flush that could not persist must not abort Edit while the row's
 * editor and chat are still current.
 */
export type QueuedEditFlushDisposition =
	| { action: 'continue' }
	| { action: 'continue-unpersisted'; reason: 'draft_flush_not_persisted' }
	| { action: 'abort'; reason: 'context_changed' };

export function queuedEditFlushDisposition(input: {
	flushed: boolean;
	editorStillCurrent: boolean;
	chatStillCurrent: boolean;
}): QueuedEditFlushDisposition {
	if (!input.editorStillCurrent || !input.chatStillCurrent) return { action: 'abort', reason: 'context_changed' };
	if (input.flushed) return { action: 'continue' };
	return { action: 'continue-unpersisted', reason: 'draft_flush_not_persisted' };
}
