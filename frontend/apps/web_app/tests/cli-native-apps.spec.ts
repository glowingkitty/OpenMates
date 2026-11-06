/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Native vs npm CLI: apps catalog reads, local helpers and a few cheap deterministic skills.
 * Provider-backed or credit-heavy skills are not run here (see the catalog gaps).
 * Harness: helpers/cli-native-differential.ts (npm CLI vs native Rust binary, same account).
 */
export {};
import type { TestInfo } from '@playwright/test';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');

const { email, password, otpKey } = getTestAccount();

test.describe('CLI native differential: apps', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('apps commands match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'apps');
		const work = fs.mkdtempSync(path.join(os.tmpdir(), 'diff-apps-'));
		try {
			await diff.check('apps (help)', ['apps'], { mode: 'exit', catalog: ['apps'] });
			await diff.check('apps list', ['apps', 'list'], { catalog: ['apps list'] });
			await diff.check('apps info', ['apps', 'info', 'web'], { catalog: ['apps info'] });
			await diff.check('apps skill-info', ['apps', 'skill-info', 'web', 'search'], { catalog: ['apps skill-info'] });
			await diff.check('apps examples', ['apps', 'examples', 'web'], { catalog: ['apps examples'] });
			await diff.check('apps run (refusal)', ['apps', 'run', 'web', 'search'], { mode: 'exit', catalog: ['apps run'] });
			// The invalid token is a 404; both CLIs report it as command_failed with the HTTP status.
			await diff.check('apps travel booking-link (invalid token)', ['apps', 'travel', 'booking-link', '--token', 'invalid-differential-token'], { catalog: ['apps travel booking-link'] });
			await diff.check('apps design export-icon', ['apps', 'design', 'export-icon', 'lucide:home', '--output', path.join(work, 'home.svg'), '--color', '#111827'], { catalog: ['apps design export-icon'] });
			await diff.check('apps images detect-ai (missing file)', ['apps', 'images', 'detect-ai', '--file', path.join(work, 'missing.png')], { catalog: ['apps images detect-ai'] });
			await diff.check('apps images detect_ai (missing file)', ['apps', 'images', 'detect_ai', '--file', path.join(work, 'missing.png')], { catalog: ['apps images detect_ai'] });

			// Cheap skills with deterministic results; ids/timestamps are normalized by the harness.
			await diff.check('apps math calculate', ['apps', 'math', 'calculate', '--expression', '2+3*4'], { structureOnly: true, catalog: ['apps math calculate'], timeoutMs: 120_000 });
			// Real diff: npm POSTs /v1/apps/reminder/skills/list-reminders directly (HTTP 200), while the shared
			// Rust SDK first reads the skill details and refuses with "This App skill is currently unavailable."
			// because the backend reports execution_available=false for this non-workflow skill.
			await diff.check('apps reminder list-reminders', ['apps', 'reminder', 'list-reminders'], {
				structureOnly: true,
				catalog: ['apps reminder list-reminders'],
				timeoutMs: 120_000,
				expectedGap: 'This App skill is currently unavailable.'
			});
		} finally {
			fs.rmSync(work, { recursive: true, force: true });
			await finishDifferential(diff);
		}
	});
});
