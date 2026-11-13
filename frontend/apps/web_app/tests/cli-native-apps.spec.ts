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
			// Documented native gaps (not verified): openmates get-docs maps a backend 404 to invalid_argument instead of
			// http-not-found; plans/tasks/workflows search report "skill currently unavailable" (exit 1) where npm returns a
			// pending client search result. pdf view/read need an uploaded chat embed and are not covered here.
			await diff.check('apps openmates get-docs', ['apps', 'openmates', 'get-docs', '--url', 'architecture/chats'], { structureOnly: true, catalog: ['apps openmates get-docs'], timeoutMs: 120_000 });
			await diff.check('apps design search_icons', ['apps', 'design', 'search_icons', '--query', 'home', '--count', '5'], { structureOnly: true, catalog: ['apps design search_icons'], timeoutMs: 120_000 });
			await diff.check('apps plans search', ['apps', 'plans', 'search', '--query', 'differential'], { expectedGap: 'exit: npm=0 native=1', structureOnly: true, catalog: ['apps plans search'], timeoutMs: 120_000 });
			await diff.check('apps tasks search', ['apps', 'tasks', 'search', '--query', 'differential'], { expectedGap: 'exit: npm=0 native=1', structureOnly: true, catalog: ['apps tasks search'], timeoutMs: 120_000 });
			await diff.check('apps workflows search', ['apps', 'workflows', 'search', '--query', 'differential'], { expectedGap: 'exit: npm=0 native=1', structureOnly: true, catalog: ['apps workflows search'], timeoutMs: 120_000 });

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

			// Missing-required-input refusals: no provider call and no credits, so the exit code and stderr class
			// of both CLIs must agree before any skill runs.
			const refusals: string[][] = [
				['business', 'company_financials'], ['code', 'get_docs'],
				['code', 'search_repos'], ['events', 'search'],
				['fitness', 'search_classes'], ['fitness', 'search_locations'], 
				['jobs', 'search'], 
				['maps', 'search'], ['news', 'search'], ['nutrition', 'search_recipes'],
				['social_media', 'search'], ['social_media', 'get-posts'],
				
				['videos', 'search'], ['videos', 'get_transcript'], ['weather', 'forecast'], ['weather', 'rain_radar'],
				['web', 'read'], ['web', 'search'], ['pdf', 'search'], ['code', 'get_issues'], ['code', 'add_issue'],
				['code', 'get_project_overview'], ['code', 'remove_secrets']
			];
			for (const [app, skill] of refusals) {
				await diff.check(`apps ${app} ${skill} (missing input)`, ['apps', app, skill], {
					mode: 'exit',
					catalog: [`apps ${app} ${skill}`],
					timeoutMs: 120_000
				});
			}
		} finally {
			fs.rmSync(work, { recursive: true, force: true });
			await finishDifferential(diff);
		}
	});
});
