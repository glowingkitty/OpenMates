// Unit tests for status page utility functions.
// Covers uptime calculation, color mapping, date formatting, and timeline helpers.
// Architecture: docs/architecture/infrastructure/status-page.md

import { describe, it, expect } from 'vitest';
import { uptimePct, fmtUptime, sc, rc, fd, ft, timelineColor, timelineTitle } from './utils';
import type { TimelineEntry } from './types';

// ─── uptimePct ──────────────────────────────────────────────────────────────

describe('uptimePct', () => {
	it('returns null for empty timeline', () => {
		expect(uptimePct([])).toBeNull();
	});

	it('returns null for null/undefined input', () => {
		expect(uptimePct(null as any)).toBeNull();
		expect(uptimePct(undefined as any)).toBeNull();
	});

	it('returns 100 when all days are operational', () => {
		const timeline: TimelineEntry[] = [
			{ date: '2026-03-20', status: 'operational' },
			{ date: '2026-03-21', status: 'operational' },
			{ date: '2026-03-22', status: 'operational' },
		];
		expect(uptimePct(timeline)).toBe(100);
	});

	it('returns 0 when all days are down', () => {
		const timeline: TimelineEntry[] = [
			{ date: '2026-03-20', status: 'down' },
			{ date: '2026-03-21', status: 'down' },
		];
		expect(uptimePct(timeline)).toBe(0);
	});

	it('calculates correct percentage with mixed statuses', () => {
		const timeline: TimelineEntry[] = [
			{ date: '2026-03-18', status: 'operational' },
			{ date: '2026-03-19', status: 'operational' },
			{ date: '2026-03-20', status: 'degraded' },
			{ date: '2026-03-21', status: 'operational' },
			{ date: '2026-03-22', status: 'down' },
		];
		// 3 operational / 5 total = 60%
		expect(uptimePct(timeline)).toBe(60);
	});

	it('excludes unknown and not_run days from calculation', () => {
		const timeline: TimelineEntry[] = [
			{ date: '2026-03-18', status: 'operational' },
			{ date: '2026-03-19', status: 'unknown' },
			{ date: '2026-03-20', status: 'not_run' },
			{ date: '2026-03-21', status: 'operational' },
		];
		// 2 operational / 2 countable (unknown + not_run excluded) = 100%
		expect(uptimePct(timeline)).toBe(100);
	});

	it('excludes has_run=false days without status', () => {
		const timeline: TimelineEntry[] = [
			{ date: '2026-03-20', has_run: false },
			{ date: '2026-03-21', status: 'operational' },
		];
		expect(uptimePct(timeline)).toBe(100);
	});

	it('returns null when all days are unknown/not_run', () => {
		const timeline: TimelineEntry[] = [
			{ date: '2026-03-20', status: 'unknown' },
			{ date: '2026-03-21', status: 'not_run' },
		];
		expect(uptimePct(timeline)).toBeNull();
	});

	it('counts passed status as up (for test timelines)', () => {
		const timeline: TimelineEntry[] = [
			{ date: '2026-03-20', status: 'passed' },
			{ date: '2026-03-21', status: 'failed' },
			{ date: '2026-03-22', status: 'passed' },
		];
		// 2 passed / 3 total = 66.7%
		expect(uptimePct(timeline)).toBe(66.7);
	});

	it('rounds to one decimal place', () => {
		const timeline: TimelineEntry[] = [
			{ date: '2026-03-20', status: 'operational' },
			{ date: '2026-03-21', status: 'operational' },
			{ date: '2026-03-22', status: 'down' },
		];
		// 2/3 = 66.666... → 66.7
		expect(uptimePct(timeline)).toBe(66.7);
	});
});

// ─── fmtUptime ──────────────────────────────────────────────────────────────

describe('fmtUptime', () => {
	it('returns empty string for null', () => {
		expect(fmtUptime(null)).toBe('');
	});

	it('formats 100 without decimal', () => {
		expect(fmtUptime(100)).toBe('100%');
	});

	it('formats with one decimal place', () => {
		expect(fmtUptime(99.7)).toBe('99.7%');
	});

	it('formats 0 with one decimal', () => {
		expect(fmtUptime(0)).toBe('0.0%');
	});
});

// ─── sc (status color) ─────────────────────────────────────────────────────

describe('sc', () => {
	it('returns green for operational', () => {
		expect(sc('operational')).toBe('#22c55e');
	});

	it('returns amber for degraded', () => {
		expect(sc('degraded')).toBe('#f59e0b');
	});

	it('returns red for down', () => {
		expect(sc('down')).toBe('#ef4444');
	});

	it('returns grey for unknown', () => {
		expect(sc('anything_else')).toBe('var(--color-grey-50)');
	});
});

// ─── rc (rate color) ────────────────────────────────────────────────────────

describe('rc', () => {
	it('returns green at 100%', () => {
		expect(rc(100)).toBe('rgb(34,197,94)');
	});

	it('returns red at 0%', () => {
		expect(rc(0)).toBe('rgb(239,68,68)');
	});

	it('returns intermediate color at 50%', () => {
		const mid = rc(50);
		expect(mid).not.toBe('rgb(34,197,94)');
		expect(mid).not.toBe('rgb(239,68,68)');
	});
});

// ─── timelineColor ──────────────────────────────────────────────────────────

describe('timelineColor', () => {
	it('maps passed to green', () => {
		expect(timelineColor({ date: '2026-03-22', status: 'passed' })).toBe('#22c55e');
	});

	it('maps failed to red', () => {
		expect(timelineColor({ date: '2026-03-22', status: 'failed' })).toBe('#ef4444');
	});

	it('maps not_run to grey', () => {
		expect(timelineColor({ date: '2026-03-22', status: 'not_run' })).toBe('var(--color-grey-40)');
	});

	it('maps has_run=false to grey', () => {
		expect(timelineColor({ date: '2026-03-22', has_run: false })).toBe('var(--color-grey-40)');
	});

	it('uses rate color for pass_rate entries', () => {
		const color = timelineColor({ date: '2026-03-22', pass_rate: 100, tone: 100 });
		expect(color).toBe('rgb(34,197,94)');
	});
});

// ─── timelineTitle ──────────────────────────────────────────────────────────

describe('timelineTitle', () => {
	it('shows "No run" for not_run status', () => {
		expect(timelineTitle({ date: '2026-03-22', status: 'not_run' })).toContain('No run');
	});

	it('shows status for status entries', () => {
		expect(timelineTitle({ date: '2026-03-22', status: 'operational' })).toContain('operational');
	});

	it('shows "No run" for has_run=false', () => {
		expect(timelineTitle({ date: '2026-03-22', has_run: false })).toContain('No run');
	});

	it('shows pass/fail counts when available', () => {
		const title = timelineTitle({ date: '2026-03-22', passed: 10, failed: 2, not_run: 1 });
		expect(title).toContain('10 passed');
		expect(title).toContain('2 failed');
		expect(title).toContain('1 not run');
	});

	it('shows pass_rate when no counts', () => {
		const title = timelineTitle({ date: '2026-03-22', pass_rate: 95 });
		expect(title).toContain('95%');
	});
});
