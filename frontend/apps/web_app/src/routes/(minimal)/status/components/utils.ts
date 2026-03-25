/**
 * Status page utility functions (v3).
 * Architecture: docs/architecture/infrastructure/status-page.md
 */

import type { ServiceStatus } from './types';

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
