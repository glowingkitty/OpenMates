/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/** A rotated cookie from an ordinary authenticated response must reach CLI disk state. */
const {test, expect} = require('./helpers/cookie-audit');
const {getTestAccount} = require('./signup-flow-helpers');
const {skipWithoutCredentials} = require('./helpers/env-guard');
const {createWorkflowCliHome, loginWorkflowCliViaPair, removeWorkflowCliHome, workflowApiUrl, workflowCliEnv} = require('./helpers/workflow-cli-e2e-helpers');
const {createHash} = require('node:crypto');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../../../..');
const CLI = path.join(ROOT, 'frontend/packages/openmates-cli/dist/cli.js');
const SDK = path.join(ROOT, 'frontend/packages/openmates-cli/dist/index.js');
const COMPOSE = path.join(ROOT, 'test-results/ci-private/compose.json');

function storedCookie(home: string): string {
	const file = path.join(home, '.openmates', 'session.json');
	const mode = fs.statSync(file).mode & 0o777;
	expect(mode & 0o077, 'The persisted CLI session must be owner-only.').toBe(0);
	const session = JSON.parse(fs.readFileSync(file, 'utf8'));
	const cookie = session?.cookies?.auth_refresh_token;
	expect(typeof cookie).toBe('string');
	expect(cookie.length).toBeGreaterThan(0);
	return cookie;
}

function evictOnlyFixtureSession(cookie: string): void {
	const digest = createHash('sha256').update(cookie).digest('hex');
	const program = [
		'import json, os, re, sys, redis',
		'assert os.environ.get("OPENMATES_CI_ISOLATED") == "1"',
		'digest = sys.stdin.read().strip()',
		'assert re.fullmatch("[a-f0-9]{64}", digest)',
		'host, port = os.environ["DRAGONFLY_URL"].rsplit(":", 1)',
		'client = redis.Redis(host=host, port=int(port), password=os.environ["DRAGONFLY_PASSWORD"])',
		'key = "session:" + digest',
		'link = json.loads(client.get(key))',
		'assert link.get("user_id") and client.ttl(key) > 0',
		'assert client.delete(key) == 1',
		'print("fixture session cache entry evicted")',
	].join('\n');
	const result = execFileSync('docker', ['compose', '-f', COMPOSE, 'exec', '-T', '-e',
		'OPENMATES_CI_ISOLATED=1', 'api', 'python', '-c', program], {
		cwd: ROOT, input: digest, encoding: 'utf8', timeout: 30_000,
	});
	expect(result.trim()).toBe('fixture session cache entry evicted');
}

function sdkProcess(apiUrl: string, home: string, program: string): any {
	const source = `
		const {pathToFileURL} = require('node:url');
		(async () => {
			const {OpenMatesClient} = await import(pathToFileURL(process.argv[1]).href);
			const client = OpenMatesClient.load({apiUrl: process.env.OPENMATES_API_URL});
			${program}
		})().catch(error => {console.error(error instanceof Error ? error.message : String(error)); process.exit(1)});
	`;
	return JSON.parse(execFileSync('node', ['-e', source, SDK], {
		cwd: ROOT, env: workflowCliEnv(apiUrl, home), encoding: 'utf8', timeout: 60_000,
	}).trim());
}

// contract-test: direct surface=cli assertions=auth.session.lifecycle,auth.session.authoritative-enforcement,auth.session.isolation
// contract-test: direct surface=rest_api assertions=auth.session.lifecycle
test('persists a refresh cookie rotated by an ordinary Projects response', async ({page}: {page: any}) => {
	test.setTimeout(120_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted' ||
		process.env.OPENMATES_CI_ISOLATED !== '1', 'Requires the disposable isolated GitHub CI stack.');
	const {email, password, otpKey} = getTestAccount();
	skipWithoutCredentials(test, email, password, otpKey);
	const apiUrl = workflowApiUrl();
	expect(new URL(apiUrl).hostname).toBe('localhost');
	expect(process.env.PLAYWRIGHT_TEST_BASE_URL).toBe('http://localhost:5173');
	expect(fs.existsSync(COMPOSE)).toBe(true);
	expect(fs.existsSync(CLI)).toBe(true);
	expect(fs.existsSync(SDK)).toBe(true);
	const home = createWorkflowCliHome('session-cookie-rotation');
	// The isolated runner also provisions a shared per-worker CLI state path.
	// Override it so pairing and both child SDK processes use this spec's home.
	const previousStateDir = process.env.OPENMATES_STATE_DIR;
	process.env.OPENMATES_STATE_DIR = path.join(home, '.openmates');
	try {
		await loginWorkflowCliViaPair(page, apiUrl, home, 'CLI_SESSION_COOKIE_ROTATION');
		const before = storedCookie(home);
		evictOnlyFixtureSession(before);
		const first = sdkProcess(apiUrl, home, `
			const observations = [];
			const originalFetch = globalThis.fetch;
			globalThis.fetch = async (input, init) => {
				const response = await originalFetch(input, init);
				const pathname = new URL(String(input)).pathname;
				if (pathname === '/v1/projects' || pathname === '/v1/user-tasks') observations.push({
					path: pathname, status: response.status,
					rotated: response.headers.getSetCookie().some(value => value.startsWith('auth_refresh_token=')),
				});
				return response;
			};
			await client.listProjects({personal: true});
			await client.listUserTasks({personal: true});
			process.stdout.write(JSON.stringify({observations}));
		`);
		expect(first.observations).toEqual([
			{path: '/v1/projects', status: 200, rotated: true},
			{path: '/v1/user-tasks', status: 200, rotated: false},
		]);
		const after = storedCookie(home);
		expect(after, 'The ordinary GET replacement cookie must be persisted.').not.toBe(before);
		const second = sdkProcess(apiUrl, home, `
			const user = await client.whoAmI();
			process.stdout.write(JSON.stringify({authenticated: Boolean(user.id || user.user_id)}));
		`);
		expect(second.authenticated).toBe(true);
		expect(storedCookie(home)).toBe(after);
	} finally {
		if (previousStateDir === undefined) delete process.env.OPENMATES_STATE_DIR;
		else process.env.OPENMATES_STATE_DIR = previousStateDir;
		removeWorkflowCliHome(home);
	}
});
