/**
 * Text-only renderer for document embed type.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str } from '../../../data/embedTextRenderers';

/** docs-doc — document embed */
export function renderDoc(c: Record<string, unknown>): string {
	const title = str(c.title) ?? str(c.filename) ?? '';
	const wordCount = c.word_count;
	const lines: string[] = [];
	lines.push(`**Document**${title ? ` — ${title}` : ''}`);
	if (wordCount) lines.push(`${wordCount} words`);
	return lines.join('\n');
}
