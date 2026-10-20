import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';

const archive = mkdtempSync(join(tmpdir(), 'openmates-build-version-'));
after(() => rmSync(archive, { recursive: true, force: true }));
const moduleUrl = new URL('./build-version.mjs', import.meta.url).href;
const checkout = fileURLToPath(new URL('../../../../', import.meta.url));

function load(overrides = {}, cwd = archive, clock = 1) {
	const env = { ...process.env };
	for (const key of ['OPENMATES_BUILD_VERSION', 'VERCEL_GIT_COMMIT_SHA', 'VERCEL_URL', 'GIT_DIR', 'GIT_WORK_TREE']) delete env[key];
	Object.assign(env, overrides);
	return spawnSync(process.execPath, ['--input-type=module', '-e',
		`Date.now = () => ${clock}; const { getVersionName } = await import(${JSON.stringify(moduleUrl)}); console.log(getVersionName());`
	], { cwd, env, encoding: 'utf8' });
}

test('archive upload uses the same deployment version in separate build workers', () => {
	const env = { VERCEL_URL: 'open-mates-webapp-reviewed.vercel.app' };
	const html = load(env, archive, 1000);
	const client = load(env, archive, 2000);
	assert.equal(html.status, 0, html.stderr);
	assert.equal(client.status, 0, client.stderr);
	assert.equal(html.stdout.trim(), env.VERCEL_URL);
	assert.equal(html.stdout, client.stdout);
});

test('explicit archive version and Vercel commit take precedence', () => {
	const env = { OPENMATES_BUILD_VERSION: 'reviewed-source', VERCEL_GIT_COMMIT_SHA: 'commit', VERCEL_URL: 'deployment' };
	assert.equal(load(env).stdout.trim(), 'reviewed-source');
	delete env.OPENMATES_BUILD_VERSION;
	assert.equal(load(env).stdout.trim(), 'commit');
});

test('ordinary checkouts retain their exact Git version', () => {
	const expected = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: checkout, encoding: 'utf8' }).trim();
	const result = load({}, checkout);
	assert.equal(result.status, 0, result.stderr);
	assert.equal(result.stdout.trim(), expected);
});

test('unidentified archives fail the build instead of shipping inconsistent bootstraps', () => {
	const result = load({ OPENMATES_BUILD_VERSION: ' ', VERCEL_GIT_COMMIT_SHA: '', VERCEL_URL: '' });
	assert.notEqual(result.status, 0);
	assert.match(result.stderr, /Set OPENMATES_BUILD_VERSION/);
});
