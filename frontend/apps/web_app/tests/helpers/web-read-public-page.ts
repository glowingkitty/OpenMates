// contract-test-file: tooling
/* eslint-disable @typescript-eslint/no-require-imports */
import { expect } from '@playwright/test';
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const { CLI_DIST } = require('./cli-test-helpers');
const ROOT = path.resolve(__dirname, '../../../../..');
const INDEX = path.join(path.dirname(CLI_DIST), 'index.js');
export const PUBLIC_PAGE = 'https://read-page.ci.test/allowed';
export const INPUT = { security: { prompt_injection_protection: 'disabled' }, requests: [{ id: 'public-page', url: PUBLIC_PAGE }] };

function runText(command: string, args: string[], env: Record<string, string | undefined> = {}) {
  const result = spawnSync(command, args, { cwd: ROOT, env: { ...process.env, ...env },
    encoding: 'utf8', timeout: 150_000, maxBuffer: 4 * 1024 * 1024 });
  expect(result.status, `${command} process must complete successfully (${result.error?.code || result.signal || 'exit'})`).toBe(0);
  return String(result.stdout).trim();
}

export function runJson(command: string, args: string[], env: Record<string, string | undefined> = {}) {
  return JSON.parse(runText(command, args, env));
}

export function npmRead(apiUrl: string, apiKey: string) {
  const device = 'web-read-public-npm';
  const bootstrap = `const {OpenMates}=await import(${JSON.stringify(INDEX)});
    const client=new OpenMates({apiUrl:process.env.OPENMATES_API_URL,apiKey:process.env.OPENMATES_API_KEY,deviceId:'${device}'});
    try{await client.chats.list({limit:1});console.log(JSON.stringify({status:200}))}
    catch(error){if(error.status!==403)throw error;console.log(JSON.stringify({status:403}))}`;
  const env = { OPENMATES_API_URL: apiUrl, OPENMATES_API_KEY: apiKey };
  if (runJson('node', ['--input-type=module', '-e', bootstrap], env).status === 403) approveDevice(apiUrl, 'npm', device);
  return runJson('node', ['--input-type=module', '-e', `const {OpenMates}=await import(${JSON.stringify(INDEX)});
    const client=new OpenMates({apiUrl:process.env.OPENMATES_API_URL,apiKey:process.env.OPENMATES_API_KEY,deviceId:'${device}'});
    console.log(JSON.stringify(await client.apps.web.read(${JSON.stringify(INPUT)})));`], env);
}

export function pipRead(apiUrl: string, apiKey: string) {
  const install = spawnSync('python3', ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '-e',
    path.join(ROOT, 'packages/openmates-python')], { cwd: ROOT, encoding: 'utf8', timeout: 150_000 });
  expect(install.status, 'Declared Python SDK dependencies must install').toBe(0);
  const device = 'web-read-public-pip';
  const env = { OPENMATES_API_URL: apiUrl, OPENMATES_API_KEY: apiKey, PYTHONPATH: path.join(ROOT, 'packages/openmates-python') };
  const init = `import json,os\nfrom openmates import OpenMates,OpenMatesApiError\nclient=OpenMates(api_url=os.environ['OPENMATES_API_URL'],api_key=os.environ['OPENMATES_API_KEY'],device_id='${device}')\n`;
  const bootstrap = init + `try:\n client.chats.list(limit=1)\n print(json.dumps({'status':200}))\nexcept OpenMatesApiError as error:\n if error.status_code!=403: raise\n print(json.dumps({'status':403}))`;
  if (runJson('python3', ['-c', bootstrap], env).status === 403) approveDevice(apiUrl, 'pip', device);
  return runJson('python3', ['-c', init + `print(json.dumps(client.apps.web.read(${JSON.stringify(INPUT)})))`], env);
}

function approveDevice(apiUrl: string, access: string, device: string) {
  runJson('node', ['--input-type=module', '-e', `const {OpenMatesClient}=await import(${JSON.stringify(INDEX)});
    const client=new OpenMatesClient({apiUrl:process.env.OPENMATES_API_URL});
    if(!client.hasSession())throw Error('Disposable owner session is missing');
    const keys=(await client.listApiKeys()).api_keys.filter(key=>key.name==='Disposable CI fixture');
    if(keys.length!==1)throw Error('Disposable fixture key is not unique');
    const devices=(await client.settingsGet('api-key-devices')).devices.filter(device=>device.api_key_id===keys[0].id&&device.access_type===${JSON.stringify(access)}&&device.machine_identifier===${JSON.stringify(device)});
    if(devices.length!==1)throw Error('Disposable fixture device is not unique');
    if(!devices[0].approved_at)await client.settingsPost('api-key-devices/'+devices[0].id+'/approve',{});
    console.log(JSON.stringify({approved:true}));`], { OPENMATES_API_URL: apiUrl, OPENMATES_API_KEY: undefined });
}

export async function fixtureAudit(): Promise<{ counts: Record<string, number>; headers: { path: string; user_agent: string; has_authorization: boolean; has_cookie: boolean }[] }> {
  const compose = path.join(ROOT, 'test-results/ci-private/compose.json');
  const id = runText('docker', ['compose', '-f', compose, 'ps', '-q', 'web-read-origin']);
  expect(id, 'Exactly one immutable fixture container must be selected').toMatch(/^[a-f0-9]{64}$/);
  const labels = runJson('docker', ['inspect', '--format', '{{json .Config.Labels}}', id]);
  const source = runText('git', ['rev-parse', 'HEAD']);
  expect(source).toMatch(/^[a-f0-9]{40}$/);
  expect(labels['com.docker.compose.project']).toBe('openmates-ci');
  expect(labels['com.docker.compose.service']).toBe('web-read-origin');
  expect(labels['org.openmates.source']).toBe(source);
  // This read-only controller request stays in the ownership-verified origin.
  // The reader still uses its real pinned public-shaped address and strict TLS.
  return runJson('docker', ['exec', id, 'python', '-c',
    "import ssl,urllib.request; context=ssl.create_default_context(cafile='/tls/ca.pem'); " +
    "client=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context)); " +
    "response=client.open('https://read-page.ci.test/__audit',timeout=5); " +
    "assert response.status==200; print(response.read().decode())"]);
}
