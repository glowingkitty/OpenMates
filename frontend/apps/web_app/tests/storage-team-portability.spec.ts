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


type TeamPortabilityFailure = {
	passed: false;
	stage: string;
	reason: string;
	error_class: string;
};

const failureStages = new Set([
	'runner_bootstrap', 'source_guard', 'docker_exec', 'probe_bootstrap', 'profile_guard',
	'service_initialization', 'isolation_proof', 'fixture_imports', 'fixture_metadata',
	'fixture_object', 'fixture_archive', 'export', 'viewer_authorization', 'import_preflight',
	'metadata_import', 'revoked_authorization', 'fixture_cleanup', 'directus_close', 'secrets_close',
]);
const failureReasons = new Set([
	'probe_exception', 'execution_failed', 'source_mismatch', 'process_exit',
	'process_timeout', 'output_limit', 'docker_unavailable', 'process_signal', 'invalid_receipt',
]);
const failureClasses = new Set([
	'RuntimeError', 'AssertionError', 'KeyError', 'ValueError', 'TypeError', 'AttributeError',
	'ImportError', 'ModuleNotFoundError', 'TimeoutError', 'ConnectionError', 'OSError',
	'ClientError', 'TeamPermissionError', 'TeamDataPortabilityError', 'ExceptionGroup', 'OtherError',
]);

function safeFailure(stdout: string): TeamPortabilityFailure | undefined {
	try {
		const value: unknown = JSON.parse(stdout.trim().split(/\r?\n/).at(-1) || '');
		if (!value || typeof value !== 'object') return;
		const item = value as Record<string, unknown>;
		if (item.passed !== false || typeof item.stage !== 'string' || !failureStages.has(item.stage)
			|| typeof item.reason !== 'string' || !failureReasons.has(item.reason)
			|| typeof item.error_class !== 'string' || !failureClasses.has(item.error_class)) return;
		// Copy only allowlisted values; extra fields and raw subprocess output are private.
		return { passed: false, stage: item.stage, reason: item.reason, error_class: item.error_class };
	} catch {
		return;
	}
}

test.describe.configure({ retries: 0 });

// contract-test: supporting surface=rest_api assertions=teams.membership.role-gated,teams.context.full-switch-local,teams.workspace.surface-parity,teams.connected-accounts.team-owned-isolation,storage.cold.shared-team-authorized,storage.privacy.ciphertext-boundary
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
		'import os,sys,runpy,json',
		'if os.getenv("BUILD_COMMIT_SHA") != sys.argv[1]:',
		' print(json.dumps({"passed":False,"stage":"source_guard","reason":"source_mismatch","error_class":"AssertionError"}));sys.exit(1)',
		'try:',
		' runpy.run_path("/app/scripts/storage_archive_integration.py", run_name="__main__")',
		'except Exception:',
		' print(json.dumps({"passed":False,"stage":"runner_bootstrap","reason":"execution_failed","error_class":"OtherError"}));sys.exit(1)',
	].join('\n');
	const result = spawnSync('docker', [
		'compose', '-f', compose, 'exec', '-T', '-e', 'OPENMATES_CI_TEAM_PORTABILITY_PROBE=1',
		'api', 'python', '-c', runner, source,
	], { encoding: 'utf8', timeout: 150_000, maxBuffer: 1024 * 1024 });
	let failure = safeFailure(result.stdout || '');
	if (result.error || result.status !== 0 || result.signal) {
		const code = (result.error as NodeJS.ErrnoException | undefined)?.code;
		const reason = code === 'ETIMEDOUT' ? 'process_timeout' : code === 'ENOBUFS' ? 'output_limit'
			: code === 'ENOENT' ? 'docker_unavailable' : result.signal ? 'process_signal' : 'process_exit';
		failure ??= { passed: false, stage: 'docker_exec', reason, error_class: 'OtherError' };
	}
	let receipt: TeamPortabilityReceipt | undefined;
	if (!failure) {
		try {
			receipt = JSON.parse(result.stdout.trim().split(/\r?\n/).at(-1) || '');
		} catch {
			failure = { passed: false, stage: 'docker_exec', reason: 'invalid_receipt', error_class: 'OtherError' };
		}
	}
	if (failure) {
		await testInfo.attach('team-portability-safe-failure', {
			body: JSON.stringify(failure), contentType: 'application/json',
		});
		throw new Error(`team_portability_isolated_probe_failed:${failure.stage}:${failure.reason}:${failure.error_class}`);
	}
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
