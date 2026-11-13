/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Native vs npm CLI: connect-account, connected-accounts, learning-mode, newchatsuggestions,
 * finance, feedback, support, benchmark, version, help and update/upgrade (dry-run only).
 * Credit-spending benchmark runs and real self-updates are never executed.
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

function promptBudgetArtifact(score: number, durationMs: number): Record<string, unknown> {
	return {
		command: 'benchmark prompt-budget',
		corpusHash: 'differential-corpus',
		summary: { averageTurnDurationMs: durationMs, averageJudgeScore: score, averageContinuityScore: score },
		cases: [{ id: 'case-1', promptHashes: ['hash-a'], turns: [{ turn: 1, judge: { score } }], continuityJudge: { score } }]
	};
}

test.describe('CLI native differential: misc groups', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('misc command groups match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'misc');
		const work = fs.mkdtempSync(path.join(os.tmpdir(), 'diff-misc-'));
		try {
			for (const group of ['connect-account', 'feedback', 'finance', 'learning-mode', 'benchmark']) {
				await diff.check(`${group} (help)`, [group], { mode: 'exit', catalog: [group] });
			}
			await diff.check('help', ['help'], { mode: 'exit', catalog: ['help'] });
			// Documented gap: the native binary reports its own crate version and has no update-availability check yet.
			await diff.check('version', ['version'], { expectedGap: '$.check_error: npm=null native="Native update availability checks are not implemented yet."', catalog: ['version'] });
			await diff.check('support', ['support'], { catalog: ['support'] });
			await diff.check('feedback assistant-response', ['feedback', 'assistant-response', '--rating', '5'], { catalog: ['feedback assistant-response'] });
			await diff.check('newchatsuggestions', ['newchatsuggestions', '--limit', '3'], { catalog: ['newchatsuggestions'] });
			await diff.check('finance check-accounts', ['finance', 'check-accounts'], { catalog: ['finance check-accounts'] });
			await diff.check('finance check_accounts', ['finance', 'check_accounts'], { catalog: ['finance check_accounts'] });

			// Self-update: dry-run only; never replaces either installation. Documented gap: the native binary
			// updates through cargo from crates.io, where the openmates crate is not published yet.
			await diff.check('update --dry-run', ['update', '--dry-run'], { expectedGap: 'exit: npm=0 native=2', catalog: ['update'] });
			await diff.check('upgrade --dry-run', ['upgrade', '--dry-run'], { expectedGap: 'exit: npm=0 native=2', catalog: ['upgrade'] });

			// Benchmarks: the spend-credit runs must refuse without --confirm-spend-credits; compare is local.
			// The live runners themselves are not ported to native (catalog gap); only the refusal is compared.
			await diff.check('benchmark model (no spend confirmation)', ['benchmark', 'model', 'openai/gpt-oss-120b'], { mode: 'exit', catalog: ['benchmark model'] });
			await diff.check('benchmark prompt-budget (no spend confirmation)', ['benchmark', 'prompt-budget', '--phase', 'baseline'], { mode: 'exit', catalog: ['benchmark prompt-budget'] });
			const baseline = path.join(work, 'baseline.json');
			const postchange = path.join(work, 'postchange.json');
			fs.writeFileSync(baseline, JSON.stringify(promptBudgetArtifact(5, 2000)));
			fs.writeFileSync(postchange, JSON.stringify(promptBudgetArtifact(3, 1500)));
			await diff.check('benchmark prompt-budget compare', ['benchmark', 'prompt-budget', 'compare', '--baseline', baseline, '--postchange', postchange], { catalog: ['benchmark prompt-budget compare'] });

			// Connect-account: pure URL builders and dry-run exchanges; no live provider calls.
			await diff.check('connect-account revolut-business consent-url', ['connect-account', 'revolut-business', 'consent-url', '--client-id', 'differential-client'], { catalog: ['connect-account revolut-business consent-url'] });
			await diff.check('connect-account revolut exchange-code --dry-run', ['connect-account', 'revolut', 'exchange-code', '--client-id', 'differential-client', '--code', 'differential-code', '--dry-run'], { catalog: ['connect-account revolut exchange-code'] });
			await diff.check('connect-account revolut-business exchange-code --dry-run', ['connect-account', 'revolut-business', 'exchange-code', '--client-id', 'differential-client', '--code', 'differential-code', '--dry-run'], { catalog: ['connect-account revolut-business exchange-code'] });
			await diff.check('connect-account revolut-business (certificate)', ['connect-account', 'revolut-business', '--output', path.join(work, 'revolut-cert'), '--overwrite'], { structureOnly: true, catalog: ['connect-account revolut-business'] });
			await diff.check('connect-account proton (no bridge)', ['connect-account', 'proton'], { mode: 'exit', catalog: ['connect-account proton'] });
			// Documented gap: npm asks for the hidden passcode before validating the payload and waits on stdin;
			// native validates the payload first and fails immediately.
			await diff.check('connected-accounts import (invalid payload)', ['connected-accounts', 'import', '--payload', 'OMCA1invalid'], { expectedGap: 'exit: npm=null native=1', timeoutMs: 20_000, catalog: ['connected-accounts import'] });

			// Learning mode: each CLI enables and disables from the same starting state.
			const passcode = '4826';
			await diff.check('learning-mode status', ['learning-mode', 'status'], { catalog: ['learning-mode status'] });
			await diff.check('learning-mode enable', ['learning-mode', 'enable', '--age-group', '13_15', '--passcode', passcode], {
				catalog: ['learning-mode enable'],
				between: async () => { await diff.npm(['learning-mode', 'disable', '--passcode', passcode, '--json']); }
			});
			await diff.check('learning-mode disable', ['learning-mode', 'disable', '--passcode', passcode], {
				catalog: ['learning-mode disable'],
				between: async () => { await diff.npm(['learning-mode', 'enable', '--age-group', '13_15', '--passcode', passcode, '--json']); }
			});
		} finally {
			fs.rmSync(work, { recursive: true, force: true });
			await finishDifferential(diff);
		}
	});
});
