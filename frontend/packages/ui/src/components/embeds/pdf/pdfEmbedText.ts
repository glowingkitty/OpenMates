/**
 * Text-only renderer for PDF embed type.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str } from '../../../data/embedTextRenderers';

/** pdf — PDF document embed */
export function renderPdf(c: Record<string, unknown>): string {
	const filename = str(c.filename) ?? '';
	const pageCount = c.page_count;
	const lines: string[] = [];
	lines.push(`**PDF**${filename ? ` — ${filename}` : ''}`);
	if (pageCount) lines.push(`${pageCount} pages`);
	return lines.join('\n');
}
