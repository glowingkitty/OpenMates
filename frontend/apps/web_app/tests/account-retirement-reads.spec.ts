/** Isolated real-CMS regression for the reader failures found retiring obsolete test accounts. */
import { expect, test } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import path from 'node:path';

test.describe.configure({ retries: 0 });

// contract-test: supporting surface=rest_api assertions=storage.deletion.global-authoritative,storage.export.persisted-bounded-complete
// eslint-disable-next-line no-empty-pattern -- This database proof creates no browser/account.
test('account retirement reads every UUID key and preserves foreign Project references', async ({}) => {
	test.setTimeout(120_000);
	if (process.env.OPENMATES_CI_ISOLATED !== '1') {
		throw new Error('Account retirement read verification requires isolated CI.');
	}
	const sourceRoot = process.env.OPENMATES_CI_SOURCE_ROOT || path.resolve(__dirname, '../../../..');
	const compose = process.env.OPENMATES_CI_COMPOSE_FILE || path.join(sourceRoot, 'test-results/ci-private/compose.json');
	const output = execFileSync('docker', [
		'compose', '-f', compose, 'exec', '-T', 'api', 'python',
		'/app/backend/scripts/probe_account_retirement_reads.py'
	], { cwd: sourceRoot, encoding: 'utf8', timeout: 90_000 });
	const receipt = JSON.parse(output.trim().split('\n').at(-1)!);
	expect(receipt.status).toBe('passed');
	expect(receipt.personal_keys).toBe(121);
	expect(receipt.uuid_rows).toBe(122);
	expect(receipt.shared_keys_preserved).toBe(true);
	expect(receipt.foreign_keys_preserved).toBe(true);
	expect(receipt.large_query_targets).toBe(500);
	expect(receipt.foreign_project_fence).toBe(true);
});
