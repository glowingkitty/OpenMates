/**
 * Status page utility functions (v3).
 * Architecture: docs/architecture/infrastructure/status-page.md
 */

import type { ServiceStatus, TimelineEntry } from './types';

export function statusColor(status: ServiceStatus | string): string {
	switch (status) {
		case 'operational': return 'var(--color-success, #22c55e)';
		case 'degraded': return 'var(--color-warning, #eab308)';
		case 'down': return 'var(--color-error, #ef4444)';
		default: return 'var(--color-grey-30, #d1d5db)';
	}
}

export function statusLabel(status: ServiceStatus | string): string {
	switch (status) {
		case 'operational': return 'Operational';
		case 'degraded': return 'Degraded';
		case 'down': return 'Down';
		default: return 'Unknown';
	}
}

export function overallStatusLabel(status: ServiceStatus | string): string {
	switch (status) {
		case 'operational': return 'All Systems Operational';
		case 'degraded': return 'Partial Degradation';
		case 'down': return 'Major Outage';
		default: return 'Status Unknown';
	}
}

export function timeAgo(isoString: string): string {
	const diff = Date.now() - new Date(isoString).getTime();
	const minutes = Math.floor(diff / 60000);
	if (minutes < 1) return 'just now';
	if (minutes < 60) return `${minutes}m ago`;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h ago`;
	return `${Math.floor(hours / 24)}d ago`;
}

export function formatDuration(minutes: number | null): string {
	if (minutes === null) return 'ongoing';
	if (minutes < 60) return `${minutes}min`;
	const h = Math.floor(minutes / 60);
	const m = minutes % 60;
	return m > 0 ? `${h}h ${m}min` : `${h}h`;
}

export function uptimePct(timeline: TimelineEntry[] | null | undefined): number | null {
	if (!timeline?.length) return null;
	const countable = timeline.filter((entry) => {
		if (entry.has_run === false) return false;
		return entry.status !== 'unknown' && entry.status !== 'not_run';
	});
	if (countable.length === 0) return null;
	const up = countable.filter((entry) => entry.status === 'operational' || entry.status === 'passed').length;
	return Math.round((up / countable.length) * 1000) / 10;
}

export function fmtUptime(value: number | null): string {
	if (value === null) return '';
	return value === 100 ? '100%' : `${value.toFixed(1)}%`;
}

export function sc(status: ServiceStatus | string): string {
	switch (status) {
		case 'operational':
		case 'passed':
			return '#22c55e';
		case 'degraded':
			return '#f59e0b';
		case 'down':
		case 'failed':
			return '#ef4444';
		default:
			return 'var(--color-grey-50)';
	}
}

export function rc(value: number): string {
	const bounded = Math.max(0, Math.min(100, value));
	const red = [239, 68, 68];
	const green = [34, 197, 94];
	const mix = red.map((start, index) => Math.round(start + ((green[index] - start) * bounded) / 100));
	return `rgb(${mix[0]},${mix[1]},${mix[2]})`;
}

export function fd(date: string): string {
	return new Date(date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export function ft(date: string): string {
	return new Date(date).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

export function timelineColor(entry: TimelineEntry): string {
	if (entry.has_run === false || entry.status === 'not_run') return 'var(--color-grey-40)';
	if (typeof entry.pass_rate === 'number') return rc(entry.tone ?? entry.pass_rate);
	return sc(entry.status ?? 'unknown');
}

export function timelineTitle(entry: TimelineEntry): string {
	if (entry.has_run === false || entry.status === 'not_run') return `${entry.date}: No run`;
	if (typeof entry.passed === 'number' || typeof entry.failed === 'number' || typeof entry.not_run === 'number') {
		const parts = [];
		if (typeof entry.passed === 'number') parts.push(`${entry.passed} passed`);
		if (typeof entry.failed === 'number') parts.push(`${entry.failed} failed`);
		if (typeof entry.not_run === 'number') parts.push(`${entry.not_run} not run`);
		return `${entry.date}: ${parts.join(', ')}`;
	}
	if (typeof entry.pass_rate === 'number') return `${entry.date}: ${entry.pass_rate}%`;
	return `${entry.date}: ${entry.status ?? 'unknown'}`;
}
