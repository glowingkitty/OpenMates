/** View model the core's live sheet sends in `liveView`; the grid only renders it. */
export interface LiveSheetCell {
	display: string;
	formula?: string;
	/** Set while an assistant proposes a value that is not applied yet. */
	suggestion?: { assistant_value: string };
}

export interface LiveSheetView {
	rows: string[];
	cols: string[];
	headers: Record<string, string>;
	aligns?: Record<string, string>;
	cells: Record<string, LiveSheetCell>;
	/** The v1 formatting snapshot in A1 coordinates, with the heading at row 1. */
	formatting?: Record<string, unknown>;
	canUndoFormatting?: boolean;
}

/** Stable address for toolbar targets. A null row denotes the heading. */
export interface LiveSheetAddress { rowId: string | null; colId: string }

/** A group of these changes is validated and committed as one edit. */
export type LiveSheetFormatChange =
	| { kind: 'cellStyle'; cell: LiveSheetAddress; patch: Record<string, unknown> }
	| { kind: 'columnWidth'; colId: string; value: number | null }
	| { kind: 'rowHeight'; rowId: string | null; value: number | null }
	| { kind: 'merge'; start: LiveSheetAddress; end: LiveSheetAddress | null }
	| { kind: 'frozenRows' | 'frozenColumns'; value: number | null };

export const cellKey = (rowId: string, colId: string): string => `${rowId}:${colId}`;

/** Narrows an opaque `liveView` payload; null while the core has not sent a sheet yet. */
export function asSheetView(view: unknown): LiveSheetView | null {
	if (!view || typeof view !== 'object') return null;
	const v = view as Partial<LiveSheetView>;
	if (!Array.isArray(v.rows) || !Array.isArray(v.cols)) return null;
	return {
		rows: v.rows, cols: v.cols, headers: v.headers ?? {}, aligns: v.aligns ?? {}, cells: v.cells ?? {},
		formatting: v.formatting, canUndoFormatting: v.canUndoFormatting,
	};
}
