/* eslint-disable @typescript-eslint/no-require-imports */
/** Real trademark records through authenticated REST, CLI and both SDKs. */
export {};

const { test, expect } = require('./console-monitor');
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const { deriveApiUrl, runCli, parseCliJson, expectCliSuccess } = require('./helpers/cli-test-helpers');

const ROOT = path.resolve(__dirname, '../../../..');
const SKILL_PATH = '/v1/apps/business/skills/search_trademarks';


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

test.describe('Business trademark search programmatic contract', () => {
  test.setTimeout(180_000);
  const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
  const key = process.env.OPENMATES_TEST_ACCOUNT_API_KEY;
  const input = { queries: ['ADIDAS'], regions: ['US'], match: 'exact', max_results: 3 };
  function assertRecords(payload: any) {
    const data = payload?.data || payload;
    expect(data.success).toBe(true);
    expect(data.matches.length).toBeGreaterThan(0);
    expect(data.matches.length).toBeLessThanOrEqual(3);
    expect(data.coverage[0].status).toBe('searched');
    expect(data.coverage[0].region).toBe('US');
    expect(data.status_filter).toBe('active');
    expect(data.match).toBe('exact');
    expect(data.coverage[0].checked_at).toEqual(expect.any(String));
    for (const row of data.matches) {
      expect(row.mark.toLowerCase()).toBe('adidas');
      expect(row.name_match).toBe('exact');
      expect(row.region).toBe('US');
      expect(row.active).toBe(true);
      expect(row.source_url).toMatch(/^https:\/\/tsdr\.uspto\.gov\/#caseNumber=/);
    }
    expect(data.limitation).toContain('legal availability');
    return data;
  }
  // contract-test: supporting surface=rest_api assertions=brand-naming.activation
  test('public catalog discovers the brand naming mode with full instructions', async ({ request }: {request: any}) => {
    const catalog = await request.get(apiUrl + '/v1/apps/metadata');
    expect(catalog.ok()).toBe(true);
    const mode = (await catalog.json()).apps.business.focus_modes.find((item: any) => item.id === 'find_brand_name');
    expect(mode).toBeTruthy();
    expect(mode.name).toBe('Find a brand name');
    expect(mode.process).toHaveLength(4);
    expect(mode.system_prompt).toContain('business.search_trademarks');
  });
  // contract-test: direct surface=rest_api assertions=trademarks.request,trademarks.coverage,trademarks.evidence
  test('REST authenticates and preserves regional limits and records', async ({ request }: {request: any}) => {
    expect([401,403]).toContain((await request.post(apiUrl + SKILL_PATH, { data: input })).status());
    test.skip(!key, 'Disposable fixture API key required');
    const live = await authenticatedRestPost(request, apiUrl, key!, input);
    expect(live.ok()).toBe(true);
    assertRecords(await live.json());
    const unsupported = await authenticatedRestPost(request, apiUrl, key!, {queries:['Name'],regions:['DE']});
    expect(unsupported.ok()).toBe(true);
    const gap = (await unsupported.json()).data || await unsupported.json();
    expect(gap.success).toBe(false);
    expect(gap.matches).toEqual([]);
    expect(gap.coverage[0].status).toBe('unsupported');
    const invalid = await authenticatedRestPost(request, apiUrl, key!, {queries:['Name']});
    if (invalid.ok()) expect(((await invalid.json()).data || await invalid.json()).success).toBe(false);
    else expect([400,422]).toContain(invalid.status());
  });
  // contract-test: direct surface=cli assertions=trademarks.evidence,trademarks.parity
  test('CLI returns bounded official trademark records', async ({ request }: {request: any}, testInfo: any) => {
    test.skip(!key, 'Disposable fixture API key required');
    expect((await request.get(apiUrl + '/health')).ok()).toBe(true);
    childProcess('sudo', ['apt-get','install','-y','xvfb','zutty','xdotool','ffmpeg','fonts-dejavu','libgl1-mesa-dri','x11-xserver-utils'], {}, 'CLI recording dependencies', false);
    childProcess('sudo', ['update-alternatives','--set','x-terminal-emulator','/usr/bin/zutty'], {}, 'CLI terminal selection', false);
    const result = await runCli(apiUrl, ['apps','business','search_trademarks','--input',JSON.stringify(input),'--json'], 90_000,
      {env: {OPENMATES_CLI_RECORD_E2E:'1', OPENMATES_E2E_SPEC:'skill-business-trademarks-api.spec.ts', LIBGL_ALWAYS_SOFTWARE:'true', GALLIUM_DRIVER:'llvmpipe'}});
    expect(result.recording, 'Real terminal recording required').toBeTruthy();
    if (fs.existsSync(result.recording.videoPath))
      await testInfo.attach('openmates-cli-real-terminal-video', {path:result.recording.videoPath, contentType:'video/mp4'});
    if (fs.existsSync(result.recording.manifestPath))
      await testInfo.attach('openmates-cli-real-terminal-manifest', {path:result.recording.manifestPath, contentType:'application/json'});
    expectCliSuccess(result, 'business.search_trademarks CLI');
    expect(fs.existsSync(result.recording.videoPath), 'Capture succeeded but terminal video is missing').toBe(true);
    assertRecords(parseCliJson(result));
  });
  // contract-test: direct surface=sdks.npm assertions=trademarks.evidence,trademarks.parity
  test('npm SDK preserves the trademark contract', async () => {
    test.skip(!key, 'Disposable fixture API key required');
    const env = {OPENMATES_API_KEY:key!, OPENMATES_API_URL:apiUrl};
    const prefix = `import { OpenMates } from './frontend/packages/openmates-cli/dist/index.js';
const client = new OpenMates({apiKey:process.env.OPENMATES_API_KEY,apiUrl:process.env.OPENMATES_API_URL,deviceId:'trademarks-e2e-npm'});`;
    const registered = childProcess('node',['--input-type=module','-e',prefix + `
try { await client.chats.list({limit:1}); console.log(JSON.stringify({status:200})); }
catch(e) { if(e.status !== 403) throw e; console.log(JSON.stringify({status:403})); }`],env,'npm fixture registration');
    if(registered.status === 403) approveFixtureDevice(apiUrl,'npm','trademarks-e2e-npm');
    assertRecords(childProcess('node',['--input-type=module','-e',prefix + `
console.log(JSON.stringify(await client.apps.business.searchTrademarks(${JSON.stringify(input)})));`],env,'npm trademark search'));
  });
  // contract-test: direct surface=sdks.pip assertions=trademarks.evidence,trademarks.parity
  test('pip SDK preserves the trademark contract', async () => {
    test.skip(!key, 'Disposable fixture API key required');
    const env = {OPENMATES_API_KEY:key!,OPENMATES_API_URL:apiUrl,PYTHONPATH:path.join(ROOT,'packages/openmates-python')};
    childProcess('python3',['-m','pip','install','--disable-pip-version-check','--no-input','-e',path.join(ROOT,'packages/openmates-python')],env,'pip dependencies',false);
    const prefix = `import json,os
from openmates import OpenMates,OpenMatesApiError
client=OpenMates(api_key=os.environ['OPENMATES_API_KEY'],api_url=os.environ['OPENMATES_API_URL'],device_id='trademarks-e2e-pip')
`;
    const registered = childProcess('python3',['-c',prefix + `try:
    client.chats.list(limit=1)
    print(json.dumps({'status':200}))
except OpenMatesApiError as e:
    if e.status_code != 403: raise
    print(json.dumps({'status':403}))`],env,'pip fixture registration');
    if(registered.status === 403) approveFixtureDevice(apiUrl,'pip','trademarks-e2e-pip');
    assertRecords(childProcess('python3',['-c',prefix + `print(json.dumps(client.apps.business.search_trademarks({'queries':['ADIDAS'],'regions':['US'],'match':'exact','max_results':3})))`],env,'pip trademark search'));
  });
});
