/**
 * Text-only renderer for sheet embed type.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str } from '../../../data/embedTextRenderers';

/** sheets-sheet — spreadsheet embed */
export function renderSheet(c: Record<string, unknown>): string {
	const title = str(c.title) ?? '';
	const rows = c.row_count ?? c.rows;
	const cols = c.col_count ?? c.cols;
	const lines: string[] = [];
	lines.push(`**Sheet**${title ? ` — ${title}` : ''}`);
	if (rows && cols) lines.push(`${rows} rows × ${cols} columns`);
	const table = str(c.table) ?? str(c.content) ?? '';
	if (table) {
		const tableRows = table.split('\n').filter((l) => l.trim().startsWith('|')).slice(0, 4);
		lines.push(...tableRows);
	}
	return lines.join('\n');
}
