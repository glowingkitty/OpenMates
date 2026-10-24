/* eslint-disable @typescript-eslint/no-require-imports */
/** Real, key-free Swedish jobs through the authenticated REST, CLI, and SDK surfaces. */
export {};

const { test, expect } = require('./console-monitor');
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const { deriveApiUrl, runCli, parseCliJson, expectCliSuccess } = require('./helpers/cli-test-helpers');
const { installRecorderDeps } = require('./cli-tui-proof-helpers');

const ROOT = path.resolve(__dirname, '../../../..');
const SKILL_PATH = '/v1/apps/jobs/skills/search';
const SEARCH = { countries: ['SE'], requests: [{ id: 'sweden', query: 'utvecklare', provider: 'JobTech', limit: 2 }] };

type Job = {
	id: string;
	title: string;
	company: string | null;
	url: string;
	apply_url: string | null;
	location: string | null;
	country: string;
	remote: boolean | null;
	employment_type: string | null;
	published_at: string | null;
	description: string | null;
	salary_min: number | null;
	salary_max: number | null;
	salary_currency: string | null;
	salary_period: string | null;
	provider: string;
	sector?: string | null;
	role?: string | null;
	seniority?: string | null;
	organization_type?: string | null;
	detail_status?: string | null;
};

function dataOf(payload: any): any {
	return payload?.data && typeof payload.data === 'object' ? payload.data : payload;
}

function assertSwedishGroup(payload: any): Job[] {
	const data = dataOf(payload);
	expect(data.success).toBe(true);
	expect(data.app_id).toBe('jobs');
	expect(data.skill_id).toBe('search');
	expect(Array.isArray(data.results)).toBe(true);
	expect(data.results).toHaveLength(1);
	const group = data.results[0];
	expect(group.id).toBe('sweden');
	expect(group.query).toBe('utvecklare');
	expect(group.country).toBe('SE');
	expect(group.countries).toEqual(['SE']);
	expect(group.providers).toEqual(['jobtech']);
	expect(group.error).toBeFalsy();
	expect(Array.isArray(group.results)).toBe(true);
	expect(group.results.length, 'The real Swedish source should return active developer listings').toBeGreaterThan(0);
	expect(group.results.length).toBeLessThanOrEqual(2);
	expect(group.result_count).toBe(group.results.length);
	expect(data.result_count).toBe(group.result_count);
	for (const job of group.results as Job[]) {
		expect(job.id).toMatch(/^jobtech:/);
		expect(job.title).toEqual(expect.any(String));
		expect(job.title.length).toBeGreaterThan(0);
		expect(job.provider).toBe('jobtech');
		expect(job.country).toBe('SE');
		expect(job.url).toMatch(/^https:\/\//);
		if (job.apply_url != null) expect(job.apply_url).toMatch(/^https:\/\//);
		if (job.remote != null) expect(typeof job.remote).toBe('boolean');
		if (job.salary_min != null) expect(Number.isFinite(job.salary_min)).toBe(true);
		if (job.salary_max != null) expect(Number.isFinite(job.salary_max)).toBe(true);
		if (job.published_at != null) expect(Number.isFinite(Date.parse(job.published_at))).toBe(true);
	}
	return group.results;
}


function childProcess(command: string, args: string[], env: Record<string, string>, label: string, parseJson = true): any {
	const result = spawnSync(command, args, {
		cwd: ROOT,
		env: { ...process.env, ...env },
		encoding: 'utf8',
		timeout: 150_000,
		maxBuffer: 4 * 1024 * 1024
	});
	const stderr = String(result.stderr || '');
	const errorClass = stderr.match(/\b(ModuleNotFoundError|ImportError|TypeError|AttributeError|SyntaxError|OpenMatesApiError)\b/)?.[1];
	const httpStatus = stderr.match(/\b(?:HTTP|status(?:_code)?)\s*[:= ]\s*(4\d\d|5\d\d)\b/i)?.[1];
	const failureCategory = [errorClass, httpStatus && `HTTP ${httpStatus}`, result.error?.code, result.signal]
		.filter(Boolean).join(', ') || 'unclassified';
	expect(result.status, `${label} failed with exit ${result.status ?? 'unknown'} (${failureCategory})`).toBe(0);
	return parseJson ? JSON.parse(result.stdout) : undefined;
}

function approveFixtureDevice(apiUrl: string, accessType: 'rest_api' | 'npm' | 'pip', deviceId?: string): void {
	const program = `import { OpenMatesClient } from './frontend/packages/openmates-cli/dist/index.js';
		const client = new OpenMatesClient({ apiUrl: process.env.OPENMATES_API_URL });
		if (!client.hasSession()) throw new Error('Fresh owner session is missing');
		const keys = await client.listApiKeys();
		const fixture = (keys.api_keys || []).filter(key => key.name === 'Disposable CI fixture');
		if (fixture.length !== 1) throw new Error('Fresh fixture API key is not unique');
		const current = await client.settingsGet('api-key-devices');
		const matches = (current.devices || []).filter(device =>
			device.api_key_id === fixture[0].id &&
			device.access_type === process.env.OPENMATES_DEVICE_ACCESS &&
			(process.env.OPENMATES_DEVICE_ACCESS === 'rest_api' ||
				device.machine_identifier === process.env.OPENMATES_DEVICE_IDENTITY));
		if (matches.length !== 1) throw new Error('Fixture device registration is not unique');
		if (!matches[0].approved_at) await client.settingsPost('api-key-devices/' + matches[0].id + '/approve', {});
		const verified = await client.settingsGet('api-key-devices');
		if (!(verified.devices || []).some(device => device.id === matches[0].id && device.approved_at))
			throw new Error('Fixture device approval failed');
		console.log(JSON.stringify({ approved: true }));`;
	const approved = childProcess('node', ['--input-type=module', '-e', program], {
		OPENMATES_API_URL: apiUrl,
		OPENMATES_DEVICE_ACCESS: accessType,
		OPENMATES_DEVICE_IDENTITY: deviceId || ''
	}, `${accessType} fixture device approval`);
	expect(approved.approved).toBe(true);
}

async function authenticatedRestPost(request: any, apiUrl: string, key: string, input: object): Promise<any> {
	const post = () => request.post(`${apiUrl}${SKILL_PATH}`, {
		data: input,
		headers: { Authorization: `Bearer ${key.split('.')[0]}`, 'X-OpenMates-SDK': 'rest_api' },
		timeout: 90_000
	});
	let response = await post();
	if (response.status() === 403) {
		approveFixtureDevice(apiUrl, 'rest_api');
		response = await post();
	}
	return response;
}

test.describe('Jobs search programmatic contract', () => {
	test.setTimeout(180_000);
	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	const key = process.env.OPENMATES_TEST_ACCOUNT_API_KEY;

	// contract-test: direct surface=rest_api assertions=app-skills.surface.semantic-parity
	test('REST requires authentication', async ({ request }: { request: any }) => {
		const response = await request.post(`${apiUrl}${SKILL_PATH}`, { data: SEARCH });
		expect([401, 403]).toContain(response.status());
	});

	// contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
	test('public catalog registers only the permitted Swedish jobs provider', async ({ request }: { request: any }) => {
		const response = await request.get(`${apiUrl}/v1/apps/metadata`);
		expect(response.ok()).toBe(true);
		const app = (await response.json()).apps?.jobs;
		expect(app).toBeTruthy();
		const skill = (app.skills || []).find((item: any) => item.id === 'search');
		expect(skill).toBeTruthy();
		expect(skill.providers).toEqual([
			expect.objectContaining({ name: 'JobTech', no_api_key: true }),
		]);
	});

	// contract-test: direct surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.surface.semantic-parity
	test('REST returns real Swedish listings and preserves partial batch errors', async ({ request }: { request: any }) => {
		test.skip(!key, 'Disposable fixture API key required');
		const batch = { countries: ['SE'], requests: [SEARCH.requests[0],
			{ id: 'unsupported', query: 'developer', country: 'DE', provider: 'JobTech', limit: 1 }] };
		const response = await authenticatedRestPost(request, apiUrl, key!, batch);
		expect(response.ok(), `REST status ${response.status()}`).toBe(true);
		const data = dataOf(await response.json());
		expect(data.success).toBe(true);
		expect(data.partial).toBe(true);
		expect(data.results).toHaveLength(2);
		assertSwedishGroup({ ...data, results: [data.results[0]], result_count: data.results[0].result_count });
		expect(data.results[1].id).toBe('unsupported');
		expect(data.results[1].error).toMatch(/does not cover selected countries DE/i);
		expect(data.results[1].results).toEqual([]);
	});

	// contract-test: direct surface=rest_api assertions=app-skills.execution.registered-validated
	test('REST rejects malformed and unknown-provider requests without provider calls', async ({ request }: { request: any }) => {
		test.skip(!key, 'Disposable fixture API key required');
		for (const invalid of [
			{ requests: [] },
			{ countries: [], requests: [{ query: 'developer' }] },
			{ countries: ['FR'], requests: [{ query: 'developer' }] },
			{ countries: ['DE'], requests: [{ query: 'engineer', providers: ['JobTech', 'ExampleJobsD'] }] },
			{ requests: [{ id: 'bad-provider', query: 'developer', country: 'SE', provider: 'Unknown Board' }] }
		]) {
			const response = await authenticatedRestPost(request, apiUrl, key!, invalid);
			if (!response.ok()) {
				expect([400, 422]).toContain(response.status());
				continue;
			}
			const data = dataOf(await response.json());
			expect(data.success).toBe(false);
			expect(data.results?.[0]?.error || data.error).toEqual(expect.any(String));
		}
	});

  // contract-test: supporting surface=rest_api assertions=app-skills.providers.unavailable-no-network
  test('Germany and mixed-country searches return an explicit capability gap', async ({ request }: { request: any }) => {
    test.skip(!key, 'Disposable fixture API key required');
    for (const countries of [['DE'], ['DE', 'SE']]) {
      const response = await authenticatedRestPost(request, apiUrl, key!, {
        countries, requests: [{ query: 'engineer', limit: 2 }],
      });
      expect(response.ok()).toBe(true);
      const data = dataOf(await response.json());
      expect(data.success).toBe(false);
      expect(data.results[0].results).toEqual([]);
      expect(data.results[0].error).toMatch(/covers DE/i);
    }
  });

	// contract-test: direct surface=cli assertions=app-skills.surface.semantic-parity
	test('CLI returns grouped Swedish listings with a real terminal recording', async ({ request }: { request: any }, testInfo: any) => {
		test.skip(!key, 'Disposable fixture API key required');
		const metadata = await request.get(`${apiUrl}/v1/apps/metadata`);
		expect(metadata.ok(), `App catalog status ${metadata.status()}`).toBe(true);
		installRecorderDeps();
		const result = await runCli(apiUrl, ['apps', 'jobs', 'search', '--input', JSON.stringify(SEARCH), '--json'], 90_000,
			{ env: { OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'skill-jobs-search-api.spec.ts', LIBGL_ALWAYS_SOFTWARE: 'true', GALLIUM_DRIVER: 'llvmpipe' } });
		expect(result.recording, 'Real terminal recording required').toBeTruthy();
		if (fs.existsSync(result.recording.videoPath))
			await testInfo.attach('openmates-cli-real-terminal-video', { path: result.recording.videoPath, contentType: 'video/mp4' });
		if (fs.existsSync(result.recording.manifestPath))
			await testInfo.attach('openmates-cli-real-terminal-manifest', { path: result.recording.manifestPath, contentType: 'application/json' });
		expectCliSuccess(result, 'jobs.search CLI');
		expect(fs.existsSync(result.recording.videoPath), 'Terminal video is missing').toBe(true);
		assertSwedishGroup(parseCliJson(result));
	});

	// contract-test: direct surface=sdks.npm assertions=app-skills.surface.semantic-parity
	test('npm SDK preserves grouped Jobs results', async () => {
		test.skip(!key, 'Disposable fixture API key required');
		const env = { OPENMATES_API_KEY: key!, OPENMATES_API_URL: apiUrl };
		const prefix = `import { OpenMates } from './frontend/packages/openmates-cli/dist/index.js';
			const client = new OpenMates({ apiKey: process.env.OPENMATES_API_KEY, apiUrl: process.env.OPENMATES_API_URL, deviceId: 'jobs-e2e-npm' });`;
		const registration = childProcess('node', ['--input-type=module', '-e', prefix + `
			try { await client.chats.list({ limit: 1 }); console.log(JSON.stringify({ status: 200 })); }
			catch (error) { if (error.status !== 403) throw error; console.log(JSON.stringify({ status: 403 })); }`], env, 'npm device registration');
		expect([200, 403]).toContain(registration.status);
		if (registration.status === 403) approveFixtureDevice(apiUrl, 'npm', 'jobs-e2e-npm');
		const output = childProcess('node', ['--input-type=module', '-e', prefix + `
			console.log(JSON.stringify(await client.apps.jobs.search(${JSON.stringify(SEARCH)})));`], env, 'npm Jobs search');
		assertSwedishGroup(output);
	});

	// contract-test: direct surface=sdks.pip assertions=app-skills.surface.semantic-parity
	test('pip SDK preserves grouped Jobs results', async () => {
		test.skip(!key, 'Disposable fixture API key required');
		const env = { OPENMATES_API_KEY: key!, OPENMATES_API_URL: apiUrl,
			PYTHONPATH: path.join(ROOT, 'packages/openmates-python') };
		childProcess('python3', ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '-e',
			path.join(ROOT, 'packages/openmates-python')], env, 'pip SDK dependency install', false);
		const prefix = `import json, os
from openmates import OpenMates, OpenMatesApiError
client = OpenMates(api_key=os.environ['OPENMATES_API_KEY'], api_url=os.environ['OPENMATES_API_URL'], device_id='jobs-e2e-pip')
`;
		const registration = childProcess('python3', ['-c', prefix + `try:
    client.chats.list(limit=1)
    print(json.dumps({'status': 200}))
except OpenMatesApiError as error:
    if error.status_code != 403:
        raise
    print(json.dumps({'status': 403}))`], env, 'pip device registration');
		expect([200, 403]).toContain(registration.status);
		if (registration.status === 403) approveFixtureDevice(apiUrl, 'pip', 'jobs-e2e-pip');
		const code = prefix + `print(json.dumps(client.apps.jobs.search({'countries': ['SE'], 'requests': [{'id': 'sweden', 'query': 'utvecklare', 'provider': 'JobTech', 'limit': 2}]})))`;
		const output = childProcess('python3', ['-c', code], env, 'pip Jobs search');
		assertSwedishGroup(output);
	});
});
