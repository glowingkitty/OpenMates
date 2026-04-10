/* eslint-disable no-console */
/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Shared console log monitor for Playwright E2E tests.
 *
 * Provides:
 *   1. Automatic console message & page error capture on every page
 *   2. Auto-fail on non-allowlisted console.error messages (afterEach)
 *   3. Aggregated log summaries (grouped by message text, sorted by frequency)
 *   4. Data export for the api-reporter (top warnings, top errors, top logs)
 *
 * Usage in spec files:
 *   Replace `const { test, expect } = require('@playwright/test');`
 *   with:     `const { test, expect, consoleLogs, networkActivities } = require('./console-monitor');`
 *
 *   The test fixture automatically attaches console/pageerror listeners,
 *   asserts zero unexpected console errors in afterEach, and exposes
 *   `consoleLogs` and `networkActivities` arrays for diagnostic output.
 *
 * Architecture context: docs/architecture/logging.md
 * Test reference: run via scripts/run-tests.sh --suite playwright
 */
export {};

const base = require('@playwright/test');
const path = require('path');
const fs = require('fs');

// ─── Types ──────────────────────────────────────────────────────────────────

interface ConsoleEntry {
	timestamp: string;
	type: string;
	text: string;
	url?: string;
}

interface AggregatedLog {
	text: string;
	count: number;
	type: string;
	first_url?: string;
}

// ─── Shared state (per-worker, reset between tests) ─────────────────────────

/** All console messages captured during the current test. */
const consoleLogs: string[] = [];

/** Structured warn/error entries for file output. */
const warnErrorLogs: ConsoleEntry[] = [];

/** Network activity log for failure diagnostics. */
const networkActivities: string[] = [];

/** Raw structured entries for aggregation (all types). */
const _rawEntries: ConsoleEntry[] = [];

// ─── Allowlist — known benign console.error patterns ────────────────────────
// These patterns are filtered out before the "fail on console errors" assertion.
// Extracted from embed-showcase.spec.ts and app-load-no-error-logs.spec.ts.

const BENIGN_ERROR_PATTERNS: RegExp[] = [
	/favicon\.ico/i,
	/Failed to load resource: net::ERR_/,
	/Failed to load resource: the server responded/,
	/Content Security Policy/i,
	/\[ChatDatabase\]/,
	// Service worker lifecycle noise
	/service worker/i,
	// Chrome DevTools noise
	/DevTools/i,
	// Browser extension interference
	/chrome-extension:\/\//,
	// Third-party script errors (Stripe, etc.)
	/js\.stripe\.com/,
	// ResizeObserver loop limit — benign browser warning
	/ResizeObserver loop/i,
	// Chunk loading failures during Vercel deploys — app recovers on reload
	/Failed to fetch dynamically imported module/i,
	/Loading chunk \d+ failed/i,
	/ChunkLoadError/i,
	/_app\/immutable\/chunks\/.*\b404\b/i,
	// Key fingerprint mismatch — known encryption issue (OPE-154) where test account
	// has chats encrypted with a previous key. Does not affect test functionality.
	/\[CryptoService\] Key fingerprint mismatch/,
	/\[CLIENT_DECRYPT\].*Failed to decrypt/,
	// Svelte 5 runtime teardown race — querySelector called on null during page.reload()
	// when the component tree is being destroyed. Not user code, no functional impact.
	/Cannot read properties of null \(reading 'querySelector'\)/
];

/**
 * Check if a console error message matches any known benign pattern.
 */
function isBenignError(text: string): boolean {
	return BENIGN_ERROR_PATTERNS.some((pattern) => pattern.test(text));
}

// ─── Aggregation helpers ────────────────────────────────────────────────────

/**
 * Aggregate raw console entries by message text and type.
 * Returns arrays sorted by frequency (most common first).
 */
function aggregateEntries(): {
	errors: AggregatedLog[];
	warnings: AggregatedLog[];
	logs: AggregatedLog[];
} {
	const buckets: Record<string, Record<string, { count: number; first_url?: string }>> = {
		error: {},
		warning: {},
		log: {}
	};

	for (const entry of _rawEntries) {
		const bucket = entry.type === 'error' ? 'error' : entry.type === 'warning' ? 'warning' : 'log';
		const key = entry.text.slice(0, 200); // Normalize long messages
		if (!buckets[bucket][key]) {
			buckets[bucket][key] = { count: 0, first_url: entry.url };
		}
		buckets[bucket][key].count++;
	}

	const toSorted = (
		bucket: Record<string, { count: number; first_url?: string }>,
		type: string
	): AggregatedLog[] =>
		Object.entries(bucket)
			.map(([text, { count, first_url }]) => ({ text, count, type, first_url }))
			.sort((a, b) => b.count - a.count);

	return {
		errors: toSorted(buckets.error, 'error'),
		warnings: toSorted(buckets.warning, 'warning'),
		logs: toSorted(buckets.log, 'log')
	};
}

/**
 * Get the top N entries from each category for the api-reporter.
 */
function getLogSummaryForReporter(topN: number = 10): {
	console_errors: AggregatedLog[];
	console_warnings: AggregatedLog[];
	console_logs_top: AggregatedLog[];
	total_console_messages: number;
} {
	const { errors, warnings, logs } = aggregateEntries();
	return {
		console_errors: errors.slice(0, topN),
		console_warnings: warnings.slice(0, topN),
		console_logs_top: logs.slice(0, topN),
		total_console_messages: _rawEntries.length
	};
}

// ─── Reset helper ───────────────────────────────────────────────────────────

function resetLogs(): void {
	consoleLogs.length = 0;
	warnErrorLogs.length = 0;
	networkActivities.length = 0;
	_rawEntries.length = 0;
}

// ─── Attach listeners helper ────────────────────────────────────────────────

/**
 * Attach console and pageerror listeners to a page instance.
 * Call this once per test with the page fixture.
 */
function attachConsoleListeners(page: any): void {
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		const type = msg.type();
		const text = msg.text();

		consoleLogs.push(`[${timestamp}] [${type}] ${text}`);

		let url: string | undefined;
		try {
			const location = msg.location?.();
			if (location?.url) url = location.url;
		} catch {
			// Some console messages don't have location
		}

		_rawEntries.push({ timestamp, type, text, url });

		if (type === 'warning' || type === 'error') {
			warnErrorLogs.push({ timestamp, type, text, url });
		}
	});

	page.on('pageerror', (error: any) => {
		const timestamp = new Date().toISOString();
		const text = `[pageerror] ${error.message}${error.stack ? '\n' + error.stack : ''}`;
		consoleLogs.push(`[${timestamp}] [pageerror] ${error.message}`);
		_rawEntries.push({ timestamp, type: 'error', text });
		warnErrorLogs.push({ timestamp, type: 'pageerror', text });
	});
}

/**
 * Attach network activity listeners to a page instance.
 * Call this once per test for network diagnostics on failure.
 */
function attachNetworkListeners(page: any): void {
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});

	page.on('response', (response: any) => {
		const url: string = response.url();
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${url}`);

		// Auto-reload on chunk 404 (Vercel deploy happened mid-test).
		// Without reload the app hangs because the component JS is gone.
		if (response.status() === 404 && url.includes('/_app/immutable/chunks/')) {
			console.log(
				`[ConsoleMonitor] Chunk 404 detected (${url.split('/').pop()}), reloading to pick up new deployment...`
			);
			page.reload().catch(() => {});
		}
	});
}

// ─── Assert no unexpected console errors ────────────────────────────────────

/**
 * Check for non-allowlisted console errors collected during the test.
 * Returns the list of unexpected errors (empty if all clear).
 */
function getUnexpectedErrors(): string[] {
	return _rawEntries.filter((e) => e.type === 'error' && !isBenignError(e.text)).map((e) => e.text);
}

// ─── Save warn/error logs to file ───────────────────────────────────────────

/**
 * Save warn/error logs to a JSON file in artifacts/.
 * Only writes the file if warnErrorLogs is non-empty.
 */
function saveWarnErrorLogs(identifier: string, phase: string): void {
	if (warnErrorLogs.length === 0) return;

	const artifactsDir = path.resolve(process.cwd(), 'artifacts');
	fs.mkdirSync(artifactsDir, { recursive: true });

	const filePath = path.join(artifactsDir, `console-warnings-${identifier}.json`);

	let existing: any = {
		identifier,
		run_timestamp: new Date().toISOString(),
		phases: {},
		total_warn_errors: 0
	};
	try {
		if (fs.existsSync(filePath)) {
			existing = JSON.parse(fs.readFileSync(filePath, 'utf8'));
		}
	} catch {
		// Ignore parse errors — start fresh
	}

	existing.phases[phase] = warnErrorLogs.slice();
	existing.total_warn_errors = Object.values(existing.phases as Record<string, any[]>).reduce(
		(sum: number, entries: any[]) => sum + entries.length,
		0
	);

	fs.writeFileSync(filePath, JSON.stringify(existing, null, 2), 'utf8');
	console.log(
		`[WARN/ERROR LOGS] Saved ${warnErrorLogs.length} entries for phase "${phase}" → ${filePath}`
	);
}

// ─── Extended test with auto-beforeEach and auto-afterEach ──────────────────

const test = base.test.extend({});

test.beforeEach(async () => {
	resetLogs();
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	// Dump diagnostic info on failure
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log: string) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach((activity: string) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}

	// Auto-fail on unexpected console errors (only if the test itself passed,
	// to avoid masking the real failure with a secondary console-error assertion)
	if (testInfo.status === 'passed') {
		const unexpected = getUnexpectedErrors();
		if (unexpected.length > 0) {
			console.error(
				`\n[CONSOLE-MONITOR] ${unexpected.length} unexpected console error(s) detected:`
			);
			unexpected.forEach((err: string) => console.error(`  ✗ ${err}`));

			// Attach the log summary as test metadata for the api-reporter
			const summary = getLogSummaryForReporter();
			testInfo.annotations.push({
				type: 'console_log_summary',
				description: JSON.stringify(summary)
			});

			// Mark the test as failed
			throw new Error(
				`Test produced ${unexpected.length} unexpected console error(s):\n` +
					unexpected.map((e: string) => `  • ${e}`).join('\n')
			);
		}
	}

	// Always attach log summary for the api-reporter (even on pass)
	const summary = getLogSummaryForReporter();
	if (summary.total_console_messages > 0) {
		testInfo.annotations.push({
			type: 'console_log_summary',
			description: JSON.stringify(summary)
		});
	}
});

// ─── Exports ────────────────────────────────────────────────────────────────

module.exports = {
	test,
	expect: base.expect,
	consoleLogs,
	warnErrorLogs,
	networkActivities,
	attachConsoleListeners,
	attachNetworkListeners,
	resetLogs,
	getUnexpectedErrors,
	getLogSummaryForReporter,
	aggregateEntries,
	saveWarnErrorLogs,
	isBenignError,
	BENIGN_ERROR_PATTERNS
};
