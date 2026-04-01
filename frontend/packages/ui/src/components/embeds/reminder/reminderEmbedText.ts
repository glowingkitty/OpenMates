/**
 * Text-only renderer for reminder embed type.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str } from '../../../data/embedTextRenderers';

/** app:reminder:set-reminder / list-reminders / cancel-reminder */
export function renderReminder(c: Record<string, unknown>): string {
	const prompt = str(c.prompt) ?? str(c.message) ?? str(c.reminder_text) ?? '';
	const time = str(c.trigger_at_formatted) ?? str(c.trigger_at) ?? '';
	const lines: string[] = ['**Reminder**'];
	if (prompt) lines.push(prompt);
	if (time) lines.push(`Time: ${time}`);
	if (c.is_repeating === true) lines.push('Repeating');
	return lines.join('\n');
}
