/** PREVIEW-ONLY in-memory sheet model for SheetLiveGridPair (the real model is the core's). */
import type { LiveSheetView } from './sheetLiveTypes';
import { cellKey } from './sheetLiveTypes';

export const previewSheet: LiveSheetView = {
	rows: ['r1', 'r2', 'r3'],
	cols: ['c1', 'c2', 'c3'],
	headers: { c1: 'Item', c2: 'Qty', c3: 'Note' },
	aligns: { c2: 'right' },
	cells: {
		'r1:c1': { display: 'Flour' }, 'r1:c2': { display: '2' }, 'r1:c3': { display: '' },
		'r2:c1': { display: 'Eggs' }, 'r2:c2': { display: '12' }, 'r2:c3': { display: 'free range' },
		'r3:c1': { display: 'Butter' }, 'r3:c2': { display: '1', suggestion: { assistant_value: '2' } }, 'r3:c3': { display: '' },
	},
};

let counter = 0;
const fresh = (prefix: string) => `${prefix}n${++counter}`;
const after = (ids: string[], id: unknown, next: string) => {
	const at = typeof id === 'string' ? ids.indexOf(id) : ids.length - 1;
	return [...ids.slice(0, at + 1), next, ...ids.slice(at + 1)];
};

export function applyPreviewSheetOp(view: LiveSheetView, raw: unknown): LiveSheetView {
	const op = raw as Record<string, string | undefined>;
	const next: LiveSheetView = { ...view, headers: { ...view.headers }, cells: { ...view.cells } };
	switch (op.op) {
		case 'set_cell': next.cells[cellKey(op.row_id as string, op.col_id as string)] = { display: op.value ?? '' }; break;
		case 'dismiss_suggestion': {
			const k = cellKey(op.row_id as string, op.col_id as string);
			next.cells[k] = { display: view.cells[k]?.display ?? '' };
			break;
		}
		case 'set_header': next.headers[op.col_id as string] = op.value ?? ''; break;
		case 'insert_row': next.rows = after(view.rows, op.after_row_id, fresh('r')); break;
		case 'delete_row': next.rows = view.rows.filter((r) => r !== op.row_id); break;
		case 'insert_col': next.cols = after(view.cols, op.after_col_id, fresh('c')); break;
		case 'delete_col': next.cols = view.cols.filter((c) => c !== op.col_id); break;
	}
	return next;
}
