/**
 * Text-only renderers for mail embed types.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str, trunc, resolveResultCount } from '../../../data/embedTextRenderers';

/** app:mail:search — composite */
export function renderMailSearch(
	c: Record<string, unknown>,
	children?: Record<string, unknown>[]
): string {
	const query = str(c.query) ?? '';
	const lines: string[] = [];
	lines.push(`**Email Search**${query ? ` — "${trunc(query, 60)}"` : ''}`);
	const count = children?.length ?? resolveResultCount(c);
	if (count !== null) lines.push(`${count} emails`);
	return lines.join('\n');
}

/** mail-email — individual email */
export function renderEmail(c: Record<string, unknown>): string {
	const subject = str(c.subject) ?? '';
	const receiver = str(c.receiver) ?? '';
	const lines: string[] = [];
	if (subject) lines.push(`**${subject}**`);
	if (receiver) lines.push(`To: ${receiver}`);
	return lines.length > 0 ? lines.join('\n') : '[Email]';
}
