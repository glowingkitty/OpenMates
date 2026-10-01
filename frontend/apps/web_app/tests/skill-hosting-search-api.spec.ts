/* eslint-disable @typescript-eslint/no-require-imports */
/** Real Gandi checks through the authenticated programmatic Hosting surfaces. */
export {};

const { test, expect } = require('./console-monitor');
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const { deriveApiUrl, runCli, parseCliJson, expectCliSuccess } = require('./helpers/cli-test-helpers');

const ROOT = path.resolve(__dirname, '../../../..');
const SKILL_PATH = '/v1/apps/hosting/skills/search_domains';
const EXACT_DOMAIN = 'example.com';

type Domain = {
	domain_ascii: string;
	domain_unicode: string;
	availability: 'available' | 'unavailable' | 'unknown';
	registration_tiers: unknown[];
	renewal_tiers: unknown[];
	currency: string;
	country: string;
	provider_url: string;
};

function dataOf(payload: any): any {
	return payload?.data && typeof payload.data === 'object' ? payload.data : payload;
}

function groupOf(payload: any): any {
	const data = dataOf(payload);
	expect(data?.success).toBe(true);
	expect(data?.results).toHaveLength(1);
	return data.results[0];
}

function assertDomain(group: any, domain: string, selected: boolean): Domain {
	expect(group.provider).toBe('Gandi');
	expect(group.country).toBe('DE');
	expect(group.currency).toBe('EUR');
	expect(group.checked_at).toEqual(expect.any(String));
	expect(typeof group.partial).toBe('boolean');
	expect(Array.isArray(group.results)).toBe(true);
	expect(Array.isArray(group.checked_results)).toBe(true);
	expect(group.results.length).toBeLessThanOrEqual(10);
	expect(group.checked_results.length).toBeLessThanOrEqual(40);
	const checked = group.checked_results.find((item: Domain) => item.domain_ascii === domain);
	expect(checked, `${domain} must remain in the checked pool`).toBeTruthy();
	expect(checked.domain_unicode).toEqual(expect.any(String));
	expect(['available', 'unavailable', 'unknown']).toContain(checked.availability);
	expect(Array.isArray(checked.registration_tiers)).toBe(true);
	expect(Array.isArray(checked.renewal_tiers)).toBe(true);
	expect(checked.currency).toBe('EUR');
	expect(checked.country).toBe('DE');
	for (const tier of [...checked.registration_tiers, ...checked.renewal_tiers] as Array<Record<string, unknown>>) {
		expect(tier.duration_range).toEqual(expect.any(Object));
		for (const field of ['price_excluding_tax', 'price_including_tax', 'normal_price']) {
			if (tier[field] != null) expect(typeof tier[field]).toBe('number');
		}
	}
	expect(checked.provider_url).toMatch(/^https:\/\/shop\.gandi\.net\//);
	if (selected) expect(group.results.map((item: Domain) => item.domain_ascii)).toContain(domain);
	return checked;
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

async function authenticatedRestPost(request: any, apiUrl: string, key: string, input: object, timeout = 90_000): Promise<any> {
	const post = () => request.post(`${apiUrl}${SKILL_PATH}`, {
		data: input,
		headers: { Authorization: `Bearer ${key.split('.')[0]}`, 'X-OpenMates-SDK': 'rest_api' },
		timeout
	});
	let response = await post();
	if (response.status() === 403) {
		approveFixtureDevice(apiUrl, 'rest_api');
		response = await post();
	}
	return response;
}

test.describe('Hosting / Search domains programmatic contract', () => {
	test.setTimeout(180_000);
	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	const key = process.env.OPENMATES_TEST_ACCOUNT_API_KEY;

	// contract-test: direct surface=rest_api assertions=hosting-domains.surface-parity
	test('REST requires authentication', async ({ request }: { request: any }) => {
		const input = { requests: [{ id: 'exact', query: EXACT_DOMAIN }] };
		const unauthorized = await request.post(`${apiUrl}${SKILL_PATH}`, { data: input });
		expect([401, 403]).toContain(unauthorized.status());
	});

	// contract-test: direct surface=rest_api assertions=hosting-domains.request.validated,hosting-domains.lookup.exact,hosting-domains.availability.selection,hosting-domains.surface-parity
	test('REST preserves exact in-use checks', async ({ request }: { request: any }) => {
		test.skip(!key, 'OPENMATES_TEST_ACCOUNT_API_KEY required');
		const response = await authenticatedRestPost(request, apiUrl, key!,
			{ requests: [{ id: 'exact', query: EXACT_DOMAIN }] });
		expect(response.ok(), `REST status ${response.status()}`).toBe(true);
		const group = groupOf(await response.json());
		expect(group.id).toBe('exact');
		expect(group.query).toBe(EXACT_DOMAIN);
		const checked = assertDomain(group, EXACT_DOMAIN, true);
		expect(checked.availability).toBe('unavailable');
		expect(group.results).toHaveLength(1);
	});

	// contract-test: direct surface=rest_api assertions=hosting-domains.availability.selection,hosting-domains.lookup.exact
	test('REST available-only keeps unavailable exact check as evidence and normalizes IDN', async ({ request }: { request: any }) => {
		test.skip(!key, 'OPENMATES_TEST_ACCOUNT_API_KEY required');
		const response = await authenticatedRestPost(request, apiUrl, key!, { requests: [
				{ id: 'only', query: EXACT_DOMAIN, availability: 'available_only', max_results: 10 },
				{ id: 'idn', query: 'bücher.de', availability: 'all', max_results: 1 }
			] }, 100_000);
		expect(response.ok(), `REST status ${response.status()}`).toBe(true);
		const groups = dataOf(await response.json()).results;
		expect(groups).toHaveLength(2);
		expect(groups.map((group: any) => group.id)).toEqual(['only', 'idn']);
		assertDomain(groups[0], EXACT_DOMAIN, false);
		expect(groups[0].results).toEqual([]);
		expect(groups[0].warnings.length).toBeGreaterThan(0);
		const idn = assertDomain(groups[1], 'xn--bcher-kva.de', false);
		expect(idn.domain_unicode).toBe('bücher.de');
	});

	// contract-test: direct surface=rest_api assertions=hosting-domains.request.validated
	test('REST rejects invalid limits and unsupported currency', async ({ request }: { request: any }) => {
		test.skip(!key, 'OPENMATES_TEST_ACCOUNT_API_KEY required');
		for (const invalid of [
			{ query: EXACT_DOMAIN, max_results: 21 },
			{ query: EXACT_DOMAIN, tlds: ['com', 'de', 'net', 'org', 'io', 'dev'] },
			{ query: EXACT_DOMAIN, currency: 'XYZ' }
		]) {
			const response = await authenticatedRestPost(request, apiUrl, key!, { requests: [invalid] }, 30_000);
			if (!response.ok()) {
				expect([400, 422]).toContain(response.status());
				continue;
			}
			const data = dataOf(await response.json());
			expect(data.success).toBe(false);
			expect(data.results?.[0]?.error || data.error).toEqual(expect.any(String));
		}
	});

	// contract-test: direct surface=rest_api assertions=hosting-domains.availability.selection,hosting-domains.lookup.exact,hosting-domains.quotes.truthful
	test('REST keyword suggestions fill from checked available names before in-use names', async ({ request }: { request: any }) => {
		test.skip(!key, 'OPENMATES_TEST_ACCOUNT_API_KEY required');
		const response = await authenticatedRestPost(request, apiUrl, key!,
			{ requests: [{ id: 'keyword', query: 'cedarcomet', max_results: 10 }] }, 100_000);
		expect(response.ok(), `REST status ${response.status()}`).toBe(true);
		const group = groupOf(await response.json());
		expect(group.id).toBe('keyword');
		expect(group.error).toBeFalsy();
		expect(group.checked_results.length, 'keyword search must exercise the Gandi suggestion stream').toBeGreaterThan(0);
		expect(group.checked_results.length).toBeLessThanOrEqual(40);
		expect(group.results.length).toBeLessThanOrEqual(10);
		const known = group.checked_results.filter((item: Domain) => item.availability !== 'unknown');
		const available = known.filter((item: Domain) => item.availability === 'available');
		expect(group.results.length).toBe(Math.min(10, known.length));
		expect(group.results.every((item: Domain) => item.availability !== 'unknown')).toBe(true);
		const firstUnavailable = group.results.findIndex((item: Domain) => item.availability === 'unavailable');
		if (firstUnavailable >= 0) {
			expect(group.results.slice(firstUnavailable).every((item: Domain) => item.availability === 'unavailable')).toBe(true);
		}
		if (available.length >= 10) expect(group.results.every((item: Domain) => item.availability === 'available')).toBe(true);
		const hasQuote = group.checked_results.some((item: Domain) =>
			[...item.registration_tiers, ...item.renewal_tiers].some((tier: any) =>
				typeof tier?.price_including_tax === 'number' || typeof tier?.price_excluding_tax === 'number'));
		if (!hasQuote) {
			expect(group.partial).toBe(true);
			expect(group.warnings.length).toBeGreaterThan(0);
		}
	});

	// contract-test: direct surface=rest_api assertions=hosting-domains.lookup.exact,hosting-domains.quotes.truthful
	test('REST .ai exact check preserves supplied minimum terms and price facts', async ({ request }: { request: any }) => {
		test.skip(!key, 'OPENMATES_TEST_ACCOUNT_API_KEY required');
		const response = await authenticatedRestPost(request, apiUrl, key!,
			{ requests: [{ id: 'ai-term', query: 'cedarcomet.ai', max_results: 1 }] });
		expect(response.ok(), `REST status ${response.status()}`).toBe(true);
		const group = groupOf(await response.json());
		expect(group.error).toBeFalsy();
		const checked = assertDomain(group, 'cedarcomet.ai', true);
		expect(checked.availability).not.toBe('unknown');
		if (checked.availability === 'available') {
			const tiers = [...checked.registration_tiers, ...checked.renewal_tiers] as Array<Record<string, any>>;
			for (const tier of tiers) {
				expect(tier.unit).toEqual(expect.any(String));
				expect(Number.isFinite(tier.duration_range?.minimum)).toBe(true);
				expect(tier.duration_range.minimum).toBeGreaterThanOrEqual(2);
				for (const field of ['price_excluding_tax', 'price_including_tax', 'normal_price']) {
					if (tier[field] != null) expect(Number.isFinite(tier[field])).toBe(true);
				}
			}
		}
	});

	// contract-test: direct surface=cli assertions=hosting-domains.lookup.exact,hosting-domains.availability.selection,hosting-domains.surface-parity
	test('CLI returns exact grouped domain evidence', async () => {
		test.skip(!key, 'OPENMATES_TEST_ACCOUNT_API_KEY required');
		const result = await runCli(apiUrl, [
			'apps', 'hosting', 'search_domains',
			'--input', JSON.stringify({ requests: [{ id: 'cli', query: EXACT_DOMAIN, availability: 'all', max_results: 1 }] }),
			'--json'
		], 90_000, { record: false });
		expectCliSuccess(result, 'hosting.search_domains CLI');
		const group = groupOf(parseCliJson(result));
		expect(group.id).toBe('cli');
		assertDomain(group, EXACT_DOMAIN, true);
	});

	// contract-test: direct surface=sdks.npm assertions=hosting-domains.lookup.exact,hosting-domains.surface-parity
	test('npm SDK preserves the grouped search result', async () => {
		test.skip(!key, 'OPENMATES_TEST_ACCOUNT_API_KEY required');
		const bootstrap = `import { OpenMates } from './frontend/packages/openmates-cli/dist/index.js';
			const client = new OpenMates({ apiKey: process.env.OPENMATES_API_KEY, apiUrl: process.env.OPENMATES_API_URL, deviceId: 'hosting-e2e-npm' });
			try { await client.chats.list({ limit: 1 }); console.log(JSON.stringify({ status: 200 })); }
			catch (error) { if (error.status !== 403) throw error; console.log(JSON.stringify({ status: 403 })); }`;
		const env = { OPENMATES_API_KEY: key!, OPENMATES_API_URL: apiUrl };
		const registration = childProcess('node', ['--input-type=module', '-e', bootstrap], env, 'npm device registration');
		expect([200, 403]).toContain(registration.status);
		if (registration.status === 403) approveFixtureDevice(apiUrl, 'npm', 'hosting-e2e-npm');
		const code = `import { OpenMates } from './frontend/packages/openmates-cli/dist/index.js';
			const client = new OpenMates({ apiKey: process.env.OPENMATES_API_KEY, apiUrl: process.env.OPENMATES_API_URL, deviceId: 'hosting-e2e-npm' });
			const output = await client.apps.hosting.searchDomains({ requests: [{ id: 'npm', query: 'example.com', max_results: 1 }] });
			console.log(JSON.stringify(output));`;
		const output = childProcess('node', ['--input-type=module', '-e', code], env, 'npm SDK');
		const group = groupOf(output);
		expect(group.id).toBe('npm');
		assertDomain(group, EXACT_DOMAIN, true);
	});

	// contract-test: direct surface=sdks.pip assertions=hosting-domains.lookup.exact,hosting-domains.surface-parity
	test('pip SDK preserves the grouped search result', async () => {
		test.skip(!key, 'OPENMATES_TEST_ACCOUNT_API_KEY required');
		const env = {
			OPENMATES_API_KEY: key!, OPENMATES_API_URL: apiUrl,
			PYTHONPATH: path.join(ROOT, 'packages/openmates-python')
		};
		childProcess('python3', ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '-e',
			path.join(ROOT, 'packages/openmates-python')], env, 'pip SDK dependency install', false);
		const bootstrap = `import json, os
from openmates import OpenMates, OpenMatesApiError
client = OpenMates(api_key=os.environ['OPENMATES_API_KEY'], api_url=os.environ['OPENMATES_API_URL'], device_id='hosting-e2e-pip')
try:
    client.chats.list(limit=1)
    print(json.dumps({'status': 200}))
except OpenMatesApiError as error:
    if error.status_code != 403:
        raise
    print(json.dumps({'status': 403}))`;
		const registration = childProcess('python3', ['-c', bootstrap], env, 'pip device registration');
		expect([200, 403]).toContain(registration.status);
		if (registration.status === 403) approveFixtureDevice(apiUrl, 'pip', 'hosting-e2e-pip');
		const code = `import json, os
from openmates import OpenMates
client = OpenMates(api_key=os.environ['OPENMATES_API_KEY'], api_url=os.environ['OPENMATES_API_URL'], device_id='hosting-e2e-pip')
output = client.apps.hosting.search_domains({'requests': [{'id': 'pip', 'query': 'example.com', 'max_results': 1}]})
print(json.dumps(output))`;
		const output = childProcess('python3', ['-c', code], env, 'pip SDK');
		const group = groupOf(output);
		expect(group.id).toBe('pip');
		assertDomain(group, EXACT_DOMAIN, true);
	});
});
