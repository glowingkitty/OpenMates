/** One account-free Team ciphertext export/import probe on the existing storage profile. */
import { expect, test } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { realpathSync } from 'node:fs';

type TeamPortabilityReceipt = {
	passed: boolean;
	source_commit: string;
	team_export_original_ciphertext: boolean;
	team_scope_and_revocation: boolean;
	team_import_preflight_no_writes: boolean;
	team_selected_import_persisted: boolean;
	team_portability_cleanup_verified: boolean;
};

test.describe.configure({ retries: 0 });

// contract-test: supporting surface=rest_api assertions=teams.membership.role-gated,teams.context.full-switch-local,teams.workspace.surface-parity,storage.cold.shared-team-authorized,storage.privacy.ciphertext-boundary
// eslint-disable-next-line no-empty-pattern -- Playwright requires destructured fixtures; this API-only test creates no browser.
test('exports Team ciphertext and imports selected metadata with verified isolated cleanup', async ({}, testInfo) => {
	if (testInfo.retry !== 0) throw new Error("team_portability_single_attempt_required");
	test.setTimeout(180_000);
	const compose = process.env.E2E_STORAGE_TEAM_COMPOSE_FILE || '';
	const source = process.env.E2E_STORAGE_TEAM_SOURCE_COMMIT || '';
	if (process.env.E2E_STORAGE_CAPACITY !== '1' || !/^[0-9a-f]{40}$/.test(source)
		|| !realpathSync(compose).includes('/ci-private/')) {
		throw new Error('team_portability_isolated_source_profile_required');
	}
	const runner = [
		'import os,sys,runpy',
		'assert os.getenv("BUILD_COMMIT_SHA") == sys.argv[1]',
		'runpy.run_path("/app/scripts/storage_archive_integration.py", run_name="__main__")',
	].join('\n');
	const result = spawnSync('docker', [
		'compose', '-f', compose, 'exec', '-T', '-e', 'OPENMATES_CI_TEAM_PORTABILITY_PROBE=1',
		'api', 'python', '-c', runner, source,
	], { encoding: 'utf8', timeout: 150_000, maxBuffer: 1024 * 1024 });
	if (result.error || result.status !== 0 || result.signal) {
		throw new Error('team_portability_isolated_probe_failed');
	}
	const receipt: TeamPortabilityReceipt = JSON.parse(result.stdout.trim().split(/\r?\n/).at(-1) || '');
	expect(receipt).toEqual({
		passed: true, source_commit: source,
		team_export_original_ciphertext: true, team_scope_and_revocation: true,
		team_import_preflight_no_writes: true, team_selected_import_persisted: true,
		team_portability_cleanup_verified: true,
	});
	await testInfo.attach('team-portability-verified-receipt', {
		body: JSON.stringify(receipt), contentType: 'application/json',
	});
});
