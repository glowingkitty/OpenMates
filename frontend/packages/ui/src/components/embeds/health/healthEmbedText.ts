/**
 * Text-only renderers for health embed types.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str, resolveResultCount } from '../../../data/embedTextRenderers';

/** app:health:search_appointments — composite */
export function renderHealthSearch(
	c: Record<string, unknown>,
	children?: Record<string, unknown>[]
): string {
	const query = str(c.query) ?? '';
	const lines: string[] = [];
	lines.push(`**Health Search**${query ? ` — "${query}"` : ''}`);

	if (children && children.length > 0) {
		lines.push(`${children.length} appointments:`);
		for (const r of children.slice(0, 5)) {
			const slotDt = str(r.slot_datetime) ?? str(r.next_slot) ?? str(r.date) ?? '';
			const name = str(r.name) ?? str(r.doctor_name) ?? str(r.title) ?? '';
			const speciality = str(r.speciality) ?? '';
			if (slotDt) lines.push(`  ${slotDt}`);
			if (name) lines.push(`  ${name}${speciality ? ` · ${speciality}` : ''}`);
			lines.push('');
		}
	} else {
		const count = resolveResultCount(c);
		if (count !== null) lines.push(`${count} appointments`);
	}
	return lines.join('\n');
}

/** health-appointment — individual */
export function renderAppointment(c: Record<string, unknown>): string {
	const name = str(c.name) ?? str(c.doctor_name) ?? str(c.title) ?? '';
	const slotDt = str(c.slot_datetime) ?? str(c.next_slot) ?? str(c.date) ?? '';
	const lines: string[] = [];
	if (name) lines.push(`**${name}**`);
	if (slotDt) lines.push(slotDt);
	return lines.length > 0 ? lines.join('\n') : '[Appointment]';
}
