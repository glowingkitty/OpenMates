/**
 * Text-only renderers for code embed types.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str } from '../../../data/embedTextRenderers';

/** code-code — code block embed */
export function renderCode(c: Record<string, unknown>): string {
	const lang = str(c.language) ?? '';
	const filename = str(c.filename) ?? '';
	const lineCount = c.line_count;
	const lines: string[] = [];

	const header = [filename, lang].filter(Boolean).join(' · ');
	lines.push(`**Code**${header ? ` — ${header}` : ''}`);
	if (lineCount) lines.push(`${lineCount} lines`);

	const code = str(c.code) ?? str(c.content) ?? '';
	if (code) {
		const codeLines = code.split('\n').slice(0, 6);
		lines.push('```' + (lang || ''));
		lines.push(...codeLines);
		if (code.split('\n').length > 6) lines.push('...');
		lines.push('```');
	}
	return lines.join('\n');
}

/** app:code:get_docs — documentation lookup */
export function renderCodeDocs(c: Record<string, unknown>): string {
	const results = c.results as Array<Record<string, unknown>> | undefined;
	const first = Array.isArray(results) ? results[0] : null;
	const libId = (first?.library as Record<string, unknown>)?.id ?? first?.library_id ?? str(c.library);
	const wordCount = first?.word_count ?? c.word_count;
	const lines: string[] = ['**Documentation**'];
	if (libId) lines.push(`Library: ${String(libId)}`);
	if (wordCount) lines.push(`${String(wordCount)} words`);
	return lines.join('\n');
}
