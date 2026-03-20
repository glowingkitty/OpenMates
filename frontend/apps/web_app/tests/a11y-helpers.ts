/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Shared accessibility testing utilities for Playwright E2E tests.
 *
 * Provides axe-core integration for automated WCAG violation scanning,
 * scoped component scanning, and a registry of known pre-existing violations.
 *
 * Architecture context: docs/architecture/accessibility.md
 * Test reference: run via scripts/run-tests.sh --suite playwright
 */
export {};

const { AxeBuilder } = require('@axe-core/playwright');

// ─── Types ──────────────────────────────────────────────────────────────────

interface A11yScanOptions {
	/** WCAG conformance level: 'wcag2a', 'wcag2aa' (default), or 'wcag2aaa' */
	wcagLevel?: string;
	/** Axe rule IDs to disable (e.g. 'color-contrast') */
	disableRules?: string[];
	/** CSS selectors to exclude from the scan */
	exclude?: string[];
	/** Violation IDs to allow (won't cause assertion failure) */
	allowedViolations?: string[];
}

interface KnownViolation {
	ruleId: string;
	reason: string;
}

// ─── Known pre-existing violations ──────────────────────────────────────────
// These are tracked for future fix but should not block CI.
// See docs/architecture/accessibility.md § Color Contrast.

const KNOWN_VIOLATIONS: KnownViolation[] = [
	{
		ruleId: 'color-contrast',
		reason:
			'--color-font-secondary (#a9a9a9) and --color-font-field-placeholder (#9e9e9e) are below WCAG AA ratio on light background. Tracked for fix in accessibility.md.'
	}
];

/**
 * Run a full-page axe-core accessibility scan.
 *
 * Returns the raw AxeResults object. Use `assertNoA11yViolations` to throw
 * on unexpected violations.
 */
async function scanPageA11y(page: any, options: A11yScanOptions = {}): Promise<any> {
	const wcagTags = [options.wcagLevel || 'wcag2aa', 'wcag21aa'];

	let builder = new AxeBuilder({ page }).withTags(wcagTags);

	if (options.disableRules?.length) {
		builder = builder.disableRules(options.disableRules);
	}

	if (options.exclude?.length) {
		for (const selector of options.exclude) {
			builder = builder.exclude(selector);
		}
	}

	return await builder.analyze();
}

/**
 * Run a scoped axe-core scan on a specific CSS selector.
 *
 * Useful for scanning modals, dialogs, or individual components without
 * noise from the rest of the page.
 */
async function scanComponentA11y(
	page: any,
	selector: string,
	options: A11yScanOptions = {}
): Promise<any> {
	const wcagTags = [options.wcagLevel || 'wcag2aa', 'wcag21aa'];

	let builder = new AxeBuilder({ page }).include(selector).withTags(wcagTags);

	if (options.disableRules?.length) {
		builder = builder.disableRules(options.disableRules);
	}

	if (options.exclude?.length) {
		for (const selector of options.exclude) {
			builder = builder.exclude(selector);
		}
	}

	return await builder.analyze();
}

/**
 * Assert that an axe-core scan result contains no unexpected violations.
 *
 * Filters out violations whose rule IDs appear in `allowedViolations` or
 * `KNOWN_VIOLATIONS`. Throws a formatted error listing each unexpected
 * violation with its impact, affected nodes, and help URL.
 */
function assertNoA11yViolations(
	results: any,
	options: { allowedViolations?: string[] } = {}
): void {
	const allowed = new Set([
		...(options.allowedViolations || []),
		...KNOWN_VIOLATIONS.map((v) => v.ruleId)
	]);

	const unexpected = (results.violations || []).filter(
		(v: any) => !allowed.has(v.id)
	);

	if (unexpected.length === 0) return;

	const details = unexpected
		.map((v: any) => {
			const nodes = (v.nodes || [])
				.slice(0, 3)
				.map((n: any) => `    → ${n.html?.slice(0, 120)}`)
				.join('\n');
			return `  [${v.impact}] ${v.id}: ${v.description}\n    Help: ${v.helpUrl}\n${nodes}`;
		})
		.join('\n\n');

	throw new Error(
		`${unexpected.length} accessibility violation(s) found:\n\n${details}`
	);
}

/**
 * Convenience: scan a page and assert no unexpected violations in one call.
 * Combines `scanPageA11y` + `assertNoA11yViolations`.
 */
async function expectPageAccessible(page: any, options: A11yScanOptions = {}): Promise<void> {
	const results = await scanPageA11y(page, options);
	assertNoA11yViolations(results, { allowedViolations: options.allowedViolations });
}

/**
 * Convenience: scan a component and assert no unexpected violations in one call.
 * Combines `scanComponentA11y` + `assertNoA11yViolations`.
 */
async function expectComponentAccessible(
	page: any,
	selector: string,
	options: A11yScanOptions = {}
): Promise<void> {
	const results = await scanComponentA11y(page, selector, options);
	assertNoA11yViolations(results, { allowedViolations: options.allowedViolations });
}

module.exports = {
	KNOWN_VIOLATIONS,
	scanPageA11y,
	scanComponentA11y,
	assertNoA11yViolations,
	expectPageAccessible,
	expectComponentAccessible
};
