// Status page helper functions.
// Shared across all status page components.
// Architecture: docs/architecture/infrastructure/status-page.md

import type { TimelineEntry } from './types';

/** Convert a string to a kebab-case test ID. */
export function tid(value: string): string {
	return value
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/^-|-$/g, '');
}

/** Map a service status to its color. */
export function sc(s: string): string {
	return s === 'operational'
		? '#22c55e'
		: s === 'degraded'
			? '#f59e0b'
			: s === 'down'
				? '#ef4444'
				: 'var(--color-grey-50)';
}

/** Compute an RGB color from a pass rate (0–100). Green at 100, red at 0. */
export function rc(rate: number): string {
	const r = Math.round(34 + (239 - 34) * (1 - rate / 100));
	const g = Math.round(197 + (68 - 197) * (1 - rate / 100));
	const b = Math.round(94 + (68 - 94) * (1 - rate / 100));
	return `rgb(${r},${g},${b})`;
}

/** Format an ISO date string to short form (e.g. "Mar 22"). */
export function fd(iso: string): string {
	try {
		return new Date(iso + 'T00:00:00').toLocaleDateString(undefined, {
			month: 'short',
			day: 'numeric'
		});
	} catch {
		return iso;
	}
}

/** Format an ISO datetime string to HH:MM. */
export function ft(iso: string): string {
	try {
		return new Date(iso).toLocaleTimeString([], {
			hour: '2-digit',
			minute: '2-digit',
			hour12: false
		});
	} catch {
		return iso;
	}
}

/** Format an ISO datetime string to full date-time. */
export function fdt(iso: string): string {
	try {
		return new Date(iso).toLocaleString(undefined, {
			month: 'short',
			day: 'numeric',
			year: 'numeric',
			hour: '2-digit',
			minute: '2-digit',
			hour12: false
		});
	} catch {
		return iso;
	}
}

/** Determine the color for a timeline entry. */
export function timelineColor(entry: TimelineEntry): string {
	if (entry.status) {
		return entry.status === 'passed'
			? '#22c55e'
			: entry.status === 'failed'
				? '#ef4444'
				: entry.status === 'not_run'
					? 'var(--color-grey-40)'
					: sc(entry.status);
	}
	if (entry.has_run === false) {
		return 'var(--color-grey-40)';
	}
	return rc(entry.tone ?? entry.pass_rate ?? 0);
}

/** Generate tooltip text for a timeline entry. */
export function timelineTitle(entry: TimelineEntry): string {
	if (entry.status) {
		if (entry.status === 'not_run') {
			return `${fd(entry.date)}: No run`;
		}
		return entry.run_at
			? `${fdt(entry.run_at)}: ${entry.status}`
			: `${fd(entry.date)}: ${entry.status}`;
	}
	if (entry.has_run === false) {
		return `${fd(entry.date)}: No run`;
	}

	const parts = [`${fd(entry.date)}`];
	if (entry.run_at) {
		parts.push(fdt(entry.run_at));
	}
	if (
		typeof entry.passed === 'number' ||
		typeof entry.failed === 'number' ||
		typeof entry.not_run === 'number'
	) {
		parts.push(`${entry.passed ?? 0} passed`);
		parts.push(`${entry.failed ?? 0} failed`);
		if ((entry.not_run ?? 0) > 0) {
			parts.push(`${entry.not_run ?? 0} not run`);
		}
	} else if (typeof entry.pass_rate === 'number') {
		parts.push(`${entry.pass_rate}%`);
	}
	return parts.join(' · ');
}

/** Suite display name mapping. */
export const SUITE_NAMES: Record<string, string> = {
	playwright: 'End to End Tests',
	vitest: 'Unit Tests (Frontend)',
	pytest_unit: 'Unit Tests (Backend)'
};

/** Overall status label mapping. */
export const STATUS_LABELS: Record<string, string> = {
	operational: 'All Systems Operational',
	degraded: 'Partial Degradation',
	down: 'Major Outage',
	unknown: 'Status Unknown'
};
