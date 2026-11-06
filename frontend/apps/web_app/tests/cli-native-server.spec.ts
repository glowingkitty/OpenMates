/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Native vs npm CLI: self-host `server` commands that only read or write a throwaway
 * fixture installation (--path is always passed, so the CI checkout is never targeted).
 * Commands that drive Docker, systemd, Caddy, sudo, backups or real hosts are not run here.
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
const REPO_ROOT = path.resolve(__dirname, '../../../..');

/** Minimal source-mode installation: compose marker, backend config and a placeholder .env. */
function createFixtureInstall(root: string): string {
	const install = path.join(root, 'install');
	fs.mkdirSync(path.join(install, 'backend', 'core'), { recursive: true });
	fs.mkdirSync(path.join(install, 'backend', 'config'), { recursive: true });
	fs.writeFileSync(path.join(install, 'backend', 'core', 'docker-compose.yml'), 'services: {}\n');
	fs.copyFileSync(path.join(REPO_ROOT, 'backend', 'config', 'backend_config.yml'), path.join(install, 'backend', 'config', 'backend_config.yml'));
	fs.writeFileSync(path.join(install, '.env'), [
		'SERVER_ENVIRONMENT=development',
		'WEBAPP_URL=https://app.example.test',
		'SECRET__MISTRAL_AI__API_KEY=placeholder-not-a-secret',
		'SECRET__BRAVE__API_KEY=',
		''
	].join('\n'), { mode: 0o600 });
	return install;
}

test.describe('CLI native differential: server', () => {
	skipWithoutCredentials(test, email, password, otpKey);

	// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
	test('fixture-scoped server commands match the npm CLI', async ({ page }: { page: any }, testInfo: TestInfo) => {
		const diff = await setupDifferential(page, testInfo, 'server');
		const work = fs.mkdtempSync(path.join(os.tmpdir(), 'diff-server-'));
		try {
			const install = createFixtureInstall(work);
			const empty = path.join(work, 'empty');
			fs.mkdirSync(empty);
			const p = ['--path', install];

			for (const group of [[], ['ai'], ['caddy'], ['monitoring'], ['notifications']]) {
				const name = ['server', ...group].join(' ');
				await diff.check(`${name} (help)`, ['server', ...group], { mode: 'exit', catalog: [name] });
			}
			// Documented gap: native reports a non-installation --path as invalid_argument without echoing
			// the path; npm throws "<path> does not appear to be an OpenMates installation" (command_failed).
			await diff.check('server env list (not an installation)', ['server', 'env', 'list', '--path', empty], { expectedGap: 'stderr class: npm=other native=validation', catalog: ['server env list'] });
			// Documented gap (npm defect): npm prints raw secret values in env listings; native redacts them.
			const redacted = { expectedGap: '"<redacted>"' };

			await diff.check('server env', ['server', 'env', ...p], { ...redacted, catalog: ['server env'] });
			await diff.check('server env list', ['server', 'env', 'list', ...p], { ...redacted, catalog: ['server env list'] });
			await diff.check('server env list providers', ['server', 'env', 'list', 'providers', ...p], { ...redacted, catalog: ['server env list'] });
			await diff.check('server env get', ['server', 'env', 'get', 'SECRET__MISTRAL_AI__API_KEY', ...p], { catalog: ['server env get'] });
			await diff.check('server env check', ['server', 'env', 'check', ...p], { catalog: ['server env check'] });
			await diff.check('server env doctor', ['server', 'env', 'doctor', ...p], { catalog: ['server env doctor'] });
			await diff.check('server env set', ['server', 'env', 'set', 'DIFFERENTIAL_FLAG', '--value', 'on', ...p], { catalog: ['server env set'] });
			await diff.check('server env unset', ['server', 'env', 'unset', 'DIFFERENTIAL_FLAG', '--yes', ...p], { catalog: ['server env unset'] });

			await diff.check('server features', ['server', 'features', ...p], { mode: 'text', catalog: ['server features'] });
			await diff.check('server features list', ['server', 'features', 'list', ...p], { mode: 'text', catalog: ['server features list'] });
			await diff.check('server features explain', ['server', 'features', 'explain', 'embed:code:application', ...p], { mode: 'text', catalog: ['server features explain'] });
			await diff.check('server features enable', ['server', 'features', 'enable', 'embed:code:application', ...p], { mode: 'text', catalog: ['server features enable'] });
			await diff.check('server features disable', ['server', 'features', 'disable', 'embed:code:application', ...p], { mode: 'text', catalog: ['server features disable'] });
			await diff.check('server features reset', ['server', 'features', 'reset', 'embed:code:application', ...p], { mode: 'text', catalog: ['server features reset'] });

			await diff.check('server ai models list', ['server', 'ai', 'models', 'list', ...p], { catalog: ['server ai models list'] });
			await diff.check('server backup list', ['server', 'backup', 'list', ...p], { catalog: ['server backup list'] });
			await diff.check('server update status', ['server', 'update', 'status', ...p], { catalog: ['server update status'] });
		} finally {
			fs.rmSync(work, { recursive: true, force: true });
			await finishDifferential(diff);
		}
	});
});
