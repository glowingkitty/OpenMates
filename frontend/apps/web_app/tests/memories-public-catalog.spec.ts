import { expect, test } from './helpers/cookie-audit';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

// playwright-account: not_required reason=public_metadata_read_only
const exec = promisify(execFile);
const ROOT = resolve(__dirname, '../../../..');
function apiUrl() {
  const configured = process.env.PLAYWRIGHT_TEST_API_URL;
  if (configured) return configured;
  const host = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL!);
  if (host.hostname === 'localhost' || host.hostname === '127.0.0.1') return 'http://localhost:8000';
  throw new Error('An isolated API URL is required.');
}

// contract-test: direct surface=rest_api assertions=app-memories.catalog.declared-types-only,app-memories.definition.context-documents
test('public metadata exposes reviewed app Memories separately from encrypted private types', async ({ request }) => {
  const response = await request.get(`${apiUrl()}/v1/apps/metadata?include_unavailable=true`);
  expect(response.ok()).toBe(true);
  const {apps} = await response.json();
  expect(apps.code.memories).toHaveLength(4);
  expect(apps.design.memories).toHaveLength(2);
  for (const appId of ['code', 'design']) {
    for (const memory of apps[appId].memories) {
      expect(memory.source).toBe('app');
      expect(memory.app_id).toBe(appId);
      expect(memory.id).toMatch(new RegExp(`^app:${appId}:`));
      expect(memory.revision).toMatch(/^[a-f0-9]{64}$/);
      expect(memory.body.length).toBeGreaterThan(0);
      expect(memory.project_id ?? null).toBeNull();
    }
  }
  expect(apps.openmates.settings_and_memories.some((type: {id: string}) => type.id === 'memories')).toBe(true);
});

// contract-test: direct surface=cli assertions=app-memories.catalog.declared-types-only,app-memories.surface.semantic-parity
test('CLI app info retains the published Memory identities and exact guidance bodies', async ({ request }) => {
  const response = await request.get(`${apiUrl()}/v1/apps/code/metadata?include_unavailable=true`);
  expect(response.ok()).toBe(true);
  const metadata = await response.json();
  const cli = existsSync('/workspace/cli/dist/cli.js') ? '/workspace/cli/dist/cli.js' : resolve('../..', 'packages/openmates-cli/dist/cli.js');
  const {stdout} = await exec(process.execPath, [cli, 'apps', 'info', 'code', '--json'], {
    env: {...process.env, OPENMATES_API_URL: apiUrl()}, timeout: 60_000,
  });
  const app = JSON.parse(stdout);
  expect(app.memories.map((memory: {id: string}) => memory.id).sort()).toEqual(metadata.memories.map((memory: {id: string}) => memory.id).sort());
  for (const memory of app.memories) expect(memory.body).toBe(metadata.memories.find((candidate: {id: string}) => candidate.id === memory.id).body);
});

// contract-test: direct surface=sdks.npm assertions=app-memories.catalog.declared-types-only,app-memories.surface.semantic-parity
test('npm SDK discovers the same read-only app Memories without account credentials', async ({request}) => {
  const response = await request.get(`${apiUrl()}/v1/apps/design/metadata?include_unavailable=true`);
  expect(response.ok()).toBe(true);
  const expected = (await response.json()).memories;
  const program = `import {OpenMates} from './frontend/packages/openmates-cli/dist/index.js';
    const client = new OpenMates({apiUrl: process.env.OPENMATES_API_URL, deviceId: 'public-memories-npm'});
    console.log(JSON.stringify(await client.memories.published({appId: 'design'})));`;
  const {stdout} = await exec(process.execPath, ['--input-type=module', '-e', program], {
    cwd: ROOT, env: {...process.env, OPENMATES_API_URL: apiUrl(), OPENMATES_API_KEY: ''}, timeout: 60_000,
  });
  expect(JSON.parse(stdout).memories).toEqual(expected);
});

// contract-test: direct surface=sdks.pip assertions=app-memories.catalog.declared-types-only,app-memories.surface.semantic-parity
test('pip SDK discovers the same read-only app Memories without account credentials', async ({request}) => {
  test.setTimeout(180_000);
  const response = await request.get(`${apiUrl()}/v1/apps/design/metadata?include_unavailable=true`);
  expect(response.ok()).toBe(true);
  const expected = (await response.json()).memories;
  await exec('python3', ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '-e', resolve(ROOT, 'packages/openmates-python')], {cwd: ROOT, timeout: 150_000});
  const program = `import json, os\nfrom openmates import OpenMates\nclient = OpenMates(api_url=os.environ['OPENMATES_API_URL'], device_id='public-memories-pip')\nprint(json.dumps(client.memories.published(app_id='design')))`;
  const {stdout} = await exec('python3', ['-c', program], {
    cwd: ROOT, env: {...process.env, PYTHONPATH: resolve(ROOT, 'packages/openmates-python'), OPENMATES_API_URL: apiUrl(), OPENMATES_API_KEY: ''}, timeout: 60_000,
  });
  expect(JSON.parse(stdout).memories).toEqual(expected);
});
