/** The Sheets toolbar's binding to the core's typed formatting operations. */
import { readonly, writable } from 'svelte/store';
import { liveItemClient } from '../../../services/live/liveItemClient';
import type { LiveItemClient } from '../../../services/live/liveItemTypes';
import { sheetCursor } from '../../../services/live/liveSurface';
import { asSheetView, type LiveSheetAddress, type LiveSheetFormatChange, type LiveSheetView } from './sheetLiveTypes';

/** Pass client to SheetLiveGrid and dispose the bridge on fullscreen teardown. */
export function createSheetFormattingBridge(itemId: string, core: LiveItemClient = liveItemClient()) {
	const view = writable<LiveSheetView | null>(null);
	const selection = writable<LiveSheetAddress | null>(null);
	const stop = core.on('liveView', (event) => {
		if (event.itemId === itemId) view.set(asSheetView(event.view));
	});
	const client: LiveItemClient = {
		...core,
		liveSetPresence(id, presence) {
			const cursor = sheetCursor(presence);
			if (id === itemId && cursor) selection.set({ rowId: cursor.row_id, colId: cursor.col_id });
			return core.liveSetPresence(id, presence);
		},
	};
	return {
		client,
		view: readonly(view),
		selection: readonly(selection),
		select: (cell: LiveSheetAddress | null) => selection.set(cell),
		applyFormatting: (changes: LiveSheetFormatChange[]) => core.liveApplyOp(itemId, { op: 'sheet_format', changes }),
		undoFormatting: () => core.liveApplyOp(itemId, { op: 'sheet_undo_formatting' }),
		async restoreVersion(source: number, head: number, scope?: { projectId?: string; teamId?: string }) {
			if (!core.liveRestoreVersion) throw new Error('live_restore_unavailable');
			if (!scope) return core.liveRestoreVersion(itemId, source, head);

			// When the grid is closed, hold a replica until the encrypted restore commits.
			let stop = () => {};
			let timeout: ReturnType<typeof setTimeout> | undefined;
			try {
				await new Promise<void>((resolve, reject) => {
					stop = core.on('liveStatus', (event) => {
						if (event.itemId !== itemId) return;
						if (event.status === 'saved') resolve();
						if (event.status === 'offline' || event.status === 'read_only' || event.status === 'access_revoked') {
							reject(new Error('live_restore_unavailable'));
						}
					});
					timeout = setTimeout(() => reject(new Error('live_restore_unavailable')), 10_000);
					void core.liveOpen(itemId, 'sheet', scope.projectId, scope.teamId).catch(reject);
				});
				return await core.liveRestoreVersion(itemId, source, head);
			} finally {
				clearTimeout(timeout);
				stop();
				await core.liveClose(itemId);
			}
		},
		dispose: stop,
	};
}
