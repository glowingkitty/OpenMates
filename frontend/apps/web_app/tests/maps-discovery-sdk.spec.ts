/* eslint-disable @typescript-eslint/no-require-imports */
/** Real npm and pip SDK validation through the isolated API. */
export {};

const { test, expect } = require('./console-monitor');
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');

const ROOT = path.resolve(__dirname, '../../../..');
const NPM_DEVICE = 'maps-discovery-e2e-npm';
const PIP_DEVICE = 'maps-discovery-e2e-pip';
const INPUT = {
	requests: [{
		id: 'invalid-area',
		query: 'Ruins near Berlin',
		categories: ['ruins'],
		area: { latitude: 91, longitude: 13.405, radiusMeters: 10000 }
	}]
};

function run(command: string, args: string[], env: Record<string, string>, label: string): any {
	const result = spawnSync(command, args, {
		cwd: ROOT,
		env: { ...process.env, ...env },
		encoding: 'utf8',
		timeout: 150_000,
		maxBuffer: 4 * 1024 * 1024
	});
	const stderr = String(result.stderr || '');
	const errorClass = stderr.match(/\b(ModuleNotFoundError|ImportError|TypeError|AttributeError|SyntaxError|OpenMatesApiError)\b/)?.[1];
	const httpStatus = stderr.match(/\bHTTP\s+(4\d\d|5\d\d)\b/i)?.[1];
	const failure = [errorClass, httpStatus && `HTTP ${httpStatus}`, result.error?.code, result.signal]
		.filter(Boolean).join(', ') || 'unclassified';
	expect(result.status, `${label} exited ${result.status ?? 'without a status'} (${failure})`).toBe(0);
	const output = String(result.stdout || '').trim();
	expect(output, `${label} returned no JSON`).toBeTruthy();
	return JSON.parse(output);
}

function approveFixtureDevice(apiUrl: string, accessType: 'npm' | 'pip', deviceId: string): void {
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
			device.machine_identifier === process.env.OPENMATES_DEVICE_IDENTITY);
		if (matches.length !== 1) throw new Error('Fixture device registration is not unique');
		if (!matches[0].approved_at) await client.settingsPost('api-key-devices/' + matches[0].id + '/approve', {});
		const verified = await client.settingsGet('api-key-devices');
		if (!(verified.devices || []).some(device => device.id === matches[0].id && device.approved_at))
			throw new Error('Fixture device approval failed');
		console.log(JSON.stringify({ approved: true }));`;
	const result = run('node', ['--input-type=module', '-e', program], {
		OPENMATES_API_URL: apiUrl,
		OPENMATES_DEVICE_ACCESS: accessType,
		OPENMATES_DEVICE_IDENTITY: deviceId
	}, `${accessType} fixture device approval`);
	expect(result.approved).toBe(true);
}

test.describe('Maps discovery SDK validation', () => {
	test.setTimeout(180_000);
	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	const key = process.env.OPENMATES_TEST_ACCOUNT_API_KEY;

	// contract-test: direct surface=sdks.npm assertions=maps-search.discovery.bounded-provider-routing
	test('npm SDK returns the grouped discovery validation failure', async () => {
		test.skip(!key, 'OPENMATES_TEST_ACCOUNT_API_KEY required');
		const env = { OPENMATES_API_KEY: key!, OPENMATES_API_URL: apiUrl };
		const bootstrap = `import { OpenMates } from './frontend/packages/openmates-cli/dist/index.js';
			const client = new OpenMates({ apiKey: process.env.OPENMATES_API_KEY, apiUrl: process.env.OPENMATES_API_URL, deviceId: '${NPM_DEVICE}' });
			try { await client.chats.list({ limit: 1 }); console.log(JSON.stringify({ status: 200 })); }
			catch (error) { if (error.status !== 403) throw error; console.log(JSON.stringify({ status: 403 })); }`;
		const registration = run('node', ['--input-type=module', '-e', bootstrap], env, 'npm device registration');
		expect([200, 403]).toContain(registration.status);
		if (registration.status === 403) approveFixtureDevice(apiUrl, 'npm', NPM_DEVICE);
		const code = `import { OpenMates } from './frontend/packages/openmates-cli/dist/index.js';
			const client = new OpenMates({ apiKey: process.env.OPENMATES_API_KEY, apiUrl: process.env.OPENMATES_API_URL, deviceId: '${NPM_DEVICE}' });
			const response = await client.apps.maps.search(${JSON.stringify(INPUT)});
			const data = response?.data;
			const group = data?.results?.[0];
			console.log(JSON.stringify({
				success: response?.success,
				creditsCharged: response?.credits_charged,
				provider: data?.provider,
				groupCount: data?.results?.length,
				groupId: group?.id,
				groupStatus: group?.status,
				groupProvider: group?.provider,
				resultCount: group?.results?.length,
				groupErrorHasLatitude: typeof group?.error === 'string' && group.error.includes('latitude'),
				topErrorHasLatitude: typeof response?.error === 'string' && response.error.includes('latitude'),
				dataErrorHasLatitude: typeof data?.error === 'string' && data.error.includes('latitude'),
			}));`;
		const response = run('node', ['--input-type=module', '-e', code], env, 'npm maps.search');
		expect(response).toEqual({
			success: false, creditsCharged: 0, provider: 'Geoapify', groupCount: 1,
			groupId: 'invalid-area', groupStatus: 'invalid_request', groupProvider: 'Geoapify',
			resultCount: 0, groupErrorHasLatitude: true, topErrorHasLatitude: true,
			dataErrorHasLatitude: true
		});
	});

	// contract-test: direct surface=sdks.pip assertions=maps-search.discovery.bounded-provider-routing
	test('pip SDK returns the grouped discovery validation failure', async () => {
		test.skip(!key, 'OPENMATES_TEST_ACCOUNT_API_KEY required');
		const env = {
			OPENMATES_API_KEY: key!,
			OPENMATES_API_URL: apiUrl,
			PYTHONPATH: path.join(ROOT, 'packages/openmates-python')
		};
		const install = spawnSync('python3', ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '-e',
			path.join(ROOT, 'packages/openmates-python')], {
			cwd: ROOT, env: { ...process.env, ...env }, encoding: 'utf8', timeout: 150_000
		});
		expect(install.status, `pip SDK dependency install exited ${install.status ?? 'without a status'}`).toBe(0);
		const bootstrap = `import json, os
from openmates import OpenMates, OpenMatesApiError
client = OpenMates(api_key=os.environ['OPENMATES_API_KEY'], api_url=os.environ['OPENMATES_API_URL'], device_id='${PIP_DEVICE}')
try:
    client.chats.list(limit=1)
    print(json.dumps({'status': 200}))
except OpenMatesApiError as error:
    if error.status_code != 403:
        raise
    print(json.dumps({'status': 403}))`;
		const registration = run('python3', ['-c', bootstrap], env, 'pip device registration');
		expect([200, 403]).toContain(registration.status);
		if (registration.status === 403) approveFixtureDevice(apiUrl, 'pip', PIP_DEVICE);
		const code = `import json, os
from openmates import OpenMates
client = OpenMates(api_key=os.environ['OPENMATES_API_KEY'], api_url=os.environ['OPENMATES_API_URL'], device_id='${PIP_DEVICE}')
response = client.apps.maps.search(${JSON.stringify(INPUT)})
data = response.get('data') or {}
groups = data.get('results') or []
group = groups[0] if groups else {}
print(json.dumps({
    'success': response.get('success'),
    'creditsCharged': response.get('credits_charged'),
    'provider': data.get('provider'),
    'groupCount': len(groups),
    'groupId': group.get('id'),
    'groupStatus': group.get('status'),
    'groupProvider': group.get('provider'),
    'resultCount': len(group.get('results') or []),
    'groupErrorHasLatitude': 'latitude' in str(group.get('error') or ''),
    'topErrorHasLatitude': 'latitude' in str(response.get('error') or ''),
    'dataErrorHasLatitude': 'latitude' in str(data.get('error') or ''),
}))`;
		const response = run('python3', ['-c', code], env, 'pip maps.search');
		expect(response).toEqual({
			success: false, creditsCharged: 0, provider: 'Geoapify', groupCount: 1,
			groupId: 'invalid-area', groupStatus: 'invalid_request', groupProvider: 'Geoapify',
			resultCount: 0, groupErrorHasLatitude: true, topErrorHasLatitude: true,
			dataErrorHasLatitude: true
		});
	});
});
