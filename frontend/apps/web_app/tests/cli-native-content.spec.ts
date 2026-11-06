/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Native vs npm CLI: ideabucket, privacy, docs, wiki, mentions and inspirations commands.
 * Harness: helpers/cli-native-differential.ts (npm CLI vs native Rust binary, same account).
 */
export {};
import type { TestInfo } from '@playwright/test';

const path = require('node:path');
const { test } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { finishDifferential, setupDifferential } = require('./helpers/cli-native-differential');
const { bothIds, parseJson, pickString } = require('./helpers/cli-native-fixtures');

const { email, password, otpKey } = getTestAccount();
const UNKNOWN = '00000000-0000-4000-8000-000000000000';

test.describe('CLI native differential: content commands', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('ideabucket, privacy, docs, wiki, mentions and inspirations match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'content');
		try {
			// Group help screens.
			for (const group of ['ideabucket', 'mentions', 'privacy']) {
				await diff.check(`${group} help`, [group], { mode: 'exit', catalog: [group] });
			}

			// Docs and wiki (public, read-only).
			await diff.check('docs help', ['docs'], { mode: 'exit', catalog: ['docs'] });
			// Documented gap: native help appends one line about its refuse-existing-file download policy.
			await diff.check('docs help subcommand', ['docs', 'help'], { mode: 'text', expectedGap: '$: npm="Docs commands:', catalog: ['docs help'] });
			const docsList = await diff.check('docs list', ['docs', 'list'], { catalog: ['docs list'] });
			const docSlug = docsList.raw ? pickString(parseJson(docsList.raw.npm), ['slug', 'path']) : '';
			await diff.check('docs search', ['docs', 'search', 'cli'], { catalog: ['docs search'] });
			await diff.check('docs show', ['docs', 'show', docSlug || 'cli'], { mode: 'text', catalog: ['docs show'] });
			await diff.check('docs download', ['docs', 'download', docSlug || 'cli', '--output', path.join(diff.npmHome, 'doc.md')], {
				mode: 'exit',
				nativeArgs: ['docs', 'download', docSlug || 'cli', '--output', path.join(diff.nativeHome, 'doc.md')],
				catalog: ['docs download']
			});
			await diff.check('wiki help', ['wiki'], { mode: 'exit', catalog: ['wiki'] });
			await diff.check('wiki help subcommand', ['wiki', 'help'], { mode: 'text', catalog: ['wiki help'] });
			const wikiSearch = await diff.check('wiki search', ['wiki', 'search', 'Berlin', '--language', 'en'], { catalog: ['wiki search'] });
			const wikiTitle = wikiSearch.raw ? pickString(parseJson(wikiSearch.raw.npm), ['canonical_title', 'title']) : '';
			await diff.check('wiki show', ['wiki', 'show', wikiTitle || 'Berlin', '--language', 'en'], { catalog: ['wiki show'] });

			// Mentions and inspirations (read-only account data).
			await diff.check('mentions list', ['mentions', 'list'], { catalog: ['mentions list'] });
			await diff.check('mentions list --type', ['mentions', 'list', '--type', 'mate'], { catalog: ['mentions list'] });
			await diff.check('mentions search', ['mentions', 'search', 'web'], { catalog: ['mentions search'] });
			await diff.check('inspirations', ['inspirations', '--lang', 'en'], { catalog: ['inspirations'] });

			// Privacy: device-local state in each CLI's isolated home; nothing is downloaded.
			// Documented gaps: the native binary ships no offline privacy runtime, so status reports a
			// different reason and install/update are not implemented (npm first asks for --yes).
			await diff.check('privacy status', ['privacy', 'status'], { expectedGap: '$.reason: npm=', catalog: ['privacy status'] });
			await diff.check('privacy disable', ['privacy', 'disable'], { mode: 'text', catalog: ['privacy disable'] });
			await diff.check('privacy enable (no model)', ['privacy', 'enable'], { mode: 'exit', catalog: ['privacy enable'] });
			await diff.check('privacy install (needs --yes)', ['privacy', 'install'], { mode: 'exit', expectedGap: 'stderr class: npm=confirmation-required native=other', catalog: ['privacy install'] });
			await diff.check('privacy update (needs --yes)', ['privacy', 'update'], { mode: 'exit', expectedGap: 'stderr class: npm=confirmation-required native=other', catalog: ['privacy update'] });
			await diff.check('privacy remove', ['privacy', 'remove', '--yes'], { mode: 'text', catalog: ['privacy remove'] });

			// Ideabucket: read, reversible settings, per-CLI throwaway idea.
			const settings = parseJson(await diff.npm(['ideabucket', 'settings', 'get', '--json'])) ?? {};
			await diff.check('ideabucket settings get', ['ideabucket', 'settings', 'get'], { catalog: ['ideabucket settings get'] });
			await diff.check('ideabucket status', ['ideabucket', 'status'], { catalog: ['ideabucket status'] });
			await diff.check('ideabucket settings set', ['ideabucket', 'settings', 'set', '--times', '09:15'], { ignoreKeys: ['itemVersion'], catalog: ['ideabucket settings set'] });
			const restoreTimes = Array.isArray(settings.times) ? settings.times.join(',') : typeof settings.times === 'string' ? settings.times : '';
			if (restoreTimes) await diff.npm(['ideabucket', 'settings', 'set', '--times', restoreTimes, '--json']);
			const added = await diff.check('ideabucket add', ['ideabucket', 'add', 'Differential idea: compare both CLIs'], { ignoreKeys: ['payloadHash'], catalog: ['ideabucket add'] });
			const bucket = bothIds(added, ['bucket_id', 'bucketId', 'id']);
			await diff.check('ideabucket status <bucket>', ['ideabucket', 'status', bucket.npm || UNKNOWN], {
				nativeArgs: ['ideabucket', 'status', bucket.native || UNKNOWN],
				catalog: ['ideabucket status']
			});
			await diff.check('ideabucket process (unknown bucket)', ['ideabucket', 'process', UNKNOWN], { catalog: ['ideabucket process'] });
			await diff.check('ideabucket audio (missing file)', ['ideabucket', 'audio', path.join(diff.npmHome, 'missing.webm')], {
				mode: 'exit',
				nativeArgs: ['ideabucket', 'audio', path.join(diff.nativeHome, 'missing.webm')],
				catalog: ['ideabucket audio']
			});
		} finally {
			await finishDifferential(diff);
		}
	});
});
