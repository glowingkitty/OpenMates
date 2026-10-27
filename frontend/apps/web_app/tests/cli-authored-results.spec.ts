/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Deterministic inference input, real saved-chat/encrypted-embed stack.
 * The maintained npm CLI is the executable baseline while native Rust migrates.
 * This spec establishes npm/pip conformance; it makes no Rust/TUI parity claim.
 */
const { test, expect } = require('./helpers/cookie-audit');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { generateTotp, getTestAccount } = require('./signup-flow-helpers');
const { CLI_DIST, deriveApiUrl } = require('./helpers/cli-test-helpers');
const {
  clearWorkflowCliSyncCache, createWorkflowCliHome, loginWorkflowCliViaPair,
  parseCliJson, removeWorkflowCliHome, runWorkflowCli, workflowCliEnv
} = require('./helpers/workflow-cli-e2e-helpers');

const ROOT = path.resolve(__dirname, '../../../..');
const FIXTURE = JSON.parse(fs.readFileSync(path.join(ROOT,
  'backend/apps/ai/testing/fixtures/authored_results.json'), 'utf8'));
const DOCUMENT = (Object.values(FIXTURE.embeds)[0] as any).document;
const DEFINITIONS = JSON.parse(fs.readFileSync(path.join(ROOT,
  'shared/config/authored_result_types.json'), 'utf8')).kinds;
const SDK_ENTRY = path.join(path.dirname(CLI_DIST), 'index.js');
const OWNER_APPROVAL_STAGES = ['import', 'paired-session', 'fixture-key', 'device-registration', 'owner-verification', 'approve-device', 'verify-approval'];
// Serial tests share one genuine saved chat; SDK checks never regenerate embeds.
test.describe.configure({ mode: 'serial' });
let savedContext: { apiUrl: string; home: string; chatId: string; carrierId: string; ids: string[]; contents: any[] } | undefined;

test.afterAll(async () => {
  if (!savedContext) return;
  const { apiUrl, home, chatId } = savedContext;
  try { await runWorkflowCli(apiUrl, home, ['chats', 'delete', chatId, '--yes', '--json'], 30_000); }
  finally { removeWorkflowCliHome(home); savedContext = undefined; }
});

function runLibrary(command: string, args: string[], env: Record<string, string | undefined>, label: string): any {
  const result = spawnSync(command, args, {
    cwd: ROOT, env: { ...process.env, ...env }, encoding: 'utf8',
    timeout: 150_000, maxBuffer: 8 * 1024 * 1024
  });
  // Keep API keys and session credentials out of assertion diagnostics.
  let approvalStage: string | undefined;
  try {
    const diagnostic = JSON.parse(String(result.stdout || '').trim());
    if (OWNER_APPROVAL_STAGES.includes(diagnostic?.approval_stage)) approvalStage = diagnostic.approval_stage;
  } catch { /* Only fixed approval-stage diagnostics may be surfaced. */ }
  const failure = String(result.stderr || '').match(/\b(?:ModuleNotFoundError|ImportError|TypeError|AttributeError|OpenMatesApiError|Error)\b/)?.[0];
  expect(result.status, `${label}: ${approvalStage || failure || result.error?.code || 'exit status'}`).toBe(0);
  return JSON.parse(String(result.stdout || '').trim());
}

function verifyChild(content: any, item: any): void {
  expect(content.type).toBe(DEFINITIONS[item.kind].backend_type);
  expect(content.app_id).toBe(DEFINITIONS[item.kind].app_id);
  expect(content.title).toBe(item.title);
  expect(content.status).toBe('finished');
  expect(content.authoring).toEqual({
    schema_version: 1, kind: item.kind, origin: item.origin,
    sources: item.sources || [], ...(item.observed_at ? { observed_at: item.observed_at } : {})
  });
  for (const [field, value] of Object.entries(item.details)) {
    if (field !== 'title') expect(content[field], `${item.kind}.${field}`).toEqual(value);
  }
  for (const field of ['currency', 'rating', 'reviews', 'insurance', 'availability']) {
    if (!(field in item.details)) expect(content).not.toHaveProperty(field);
  }
  expect(content).not.toHaveProperty('embed_ids');
  expect(content).not.toHaveProperty('execution_status');
  if (item.kind === 'tv.movie') {
    expect(content.type).toBe('tv_movie');
    expect(content.score.scale).toBe(10);
    expect(content.score.source_label).toBe('Supplied score');
  }
  if (item.kind === 'tv.series') {
    expect(content.type).toBe('tv_series');
    expect(content.seasons[0].season_number).toBe(0);
    expect(content.seasons[0].title).toBe('Specials');
    expect(content.seasons.length).toBeLessThan(content.season_count);
    expect(content.seasons.reduce((total: number, season: any) => total + season.episode_count, 0)).toBeLessThan(content.episode_count);
    expect(content).not.toHaveProperty('score');
    expect(content).not.toHaveProperty('streaming_availability');
  }
  if (item.origin === 'draft') {
    expect(content.title).toMatch(/^Draft: /);
    expect(content).not.toHaveProperty('published_at');
    expect(content).not.toHaveProperty('likes_count');
  }
}

function verifyCarrier(content: any): string[] {
  expect(DOCUMENT.items).toHaveLength(25);
  expect(new Set(DOCUMENT.items.map((item: any) => item.kind))).toEqual(new Set(Object.keys(DEFINITIONS)));
  expect(content.type).toBe('authored_results');
  expect(content.status).toBe('finished');
  expect(content.title).toBe(DOCUMENT.title);
  expect(content.embed_ids).toHaveLength(DOCUMENT.items.length);
  expect(new Set(content.embed_ids).size).toBe(DOCUMENT.items.length);
  expect(content.items.map((item: any) => item.kind)).toEqual(DOCUMENT.items.map((item: any) => item.kind));
  expect(content.items.map((item: any) => item.embed_id)).toEqual(content.embed_ids);
  expect(content.view).toEqual({ mode: 'cards', embeds: content.embed_ids });
  expect(content.validation.status).toBe('valid');
  expect(content.validation.warnings).toEqual([]);
  return content.embed_ids;
}

async function approveDevice(apiUrl: string, home: string, access: string, deviceId: string): Promise<void> {
  const otpKey = getTestAccount().otpKey;
  expect(otpKey, 'isolated owner TOTP required for SDK device approval').toBeTruthy();
  // Strong proof belongs to the paired receiver session. Use an unconsumed
  // account-wide TOTP step rather than reusing the browser login's proof/code.
  await new Promise(resolve => setTimeout(resolve, 30_000 - (Date.now() % 30_000) + 1_000));
  const code = `let stage = 'import';
    try {
      const { pathToFileURL } = await import('node:url');
      const { OpenMatesClient } = await import(pathToFileURL(process.env.SDK_ENTRY).href);
      stage = 'paired-session';
      const owner = new OpenMatesClient({ apiUrl: process.env.OPENMATES_API_URL });
      if (!owner.hasSession()) throw new Error();
      stage = 'fixture-key';
      const keys = await owner.listApiKeys();
      const fixture = (keys.api_keys || []).filter(key => key.name === 'Disposable CI fixture');
      if (fixture.length !== 1) throw new Error();
      stage = 'device-registration';
      const registered = await owner.settingsGet('api-key-devices');
      const devices = (registered.devices || []).filter(device =>
        device.api_key_id === fixture[0].id && device.access_type === process.env.DEVICE_ACCESS &&
        device.machine_identifier === process.env.DEVICE_ID);
      if (devices.length !== 1) throw new Error();
      if (!devices[0].approved_at) {
        stage = 'owner-verification';
        await owner.verifyTotpForCurrentSession(process.env.OWNER_TOTP_CODE);
        stage = 'approve-device';
        await owner.settingsPost('api-key-devices/' + devices[0].id + '/approve', {});
      }
      stage = 'verify-approval';
      const current = await owner.settingsGet('api-key-devices');
      if (!(current.devices || []).some(device => device.id === devices[0].id &&
        device.api_key_id === fixture[0].id && device.access_type === process.env.DEVICE_ACCESS &&
        device.machine_identifier === process.env.DEVICE_ID && device.approved_at)) throw new Error();
      console.log(JSON.stringify({ approved: true }));
    } catch {
      console.log(JSON.stringify({ approved: false, approval_stage: stage }));
      process.exitCode = 1;
    }`;
  expect(runLibrary('node', ['--input-type=module', '-e', code], {
    ...workflowCliEnv(apiUrl, home), SDK_ENTRY, DEVICE_ACCESS: access, DEVICE_ID: deviceId,
    OWNER_TOTP_CODE: generateTotp(otpKey)
  }, `${access} owner device approval`).approved).toBe(true);
}

async function sdkSnapshot(language: 'npm' | 'pip', apiUrl: string, home: string, chatId: string, ids: string[]): Promise<any> {
  const deviceId = `authored-results-e2e-${language}`;
  const env = {
    OPENMATES_API_URL: apiUrl, OPENMATES_API_KEY: process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
    SDK_ENTRY, CHAT_ID: chatId, EMBED_IDS: JSON.stringify(ids), DEVICE_ID: deviceId,
    PYTHONPATH: path.join(ROOT, 'packages/openmates-python')
  };
  const npmHeader = `import { pathToFileURL } from 'node:url';
    const { OpenMates } = await import(pathToFileURL(process.env.SDK_ENTRY).href);
    const client = new OpenMates({ apiKey: process.env.OPENMATES_API_KEY,
      apiUrl: process.env.OPENMATES_API_URL, deviceId: process.env.DEVICE_ID });`;
  const pipHeader = `import json, os
from openmates import OpenMates, OpenMatesApiError
client = OpenMates(api_key=os.environ['OPENMATES_API_KEY'], api_url=os.environ['OPENMATES_API_URL'], device_id=os.environ['DEVICE_ID'])
`;
  if (language === 'pip') {
    const installed = spawnSync('python3', ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '-e',
      path.join(ROOT, 'packages/openmates-python')], { cwd: ROOT, encoding: 'utf8', timeout: 150_000 });
    expect(installed.status, 'pip SDK dependency installation').toBe(0);
  }
  const registration = language === 'npm'
    ? runLibrary('node', ['--input-type=module', '-e', npmHeader + `
      try { await client.chats.list({ limit: 1 }); console.log(JSON.stringify({ status: 200 })); }
      catch (error) { if (error.status !== 403) throw error; console.log(JSON.stringify({ status: 403 })); }`], env, 'npm registration')
    : runLibrary('python3', ['-c', pipHeader + `
try:
    client.chats.list(limit=1)
    print(json.dumps({'status': 200}))
except OpenMatesApiError as error:
    if error.status_code != 403:
        raise
    print(json.dumps({'status': 403}))`], env, 'pip registration');
  expect([200, 403]).toContain(registration.status);
  if (registration.status === 403) await approveDevice(apiUrl, home, language, deviceId);

  return language === 'npm'
    ? runLibrary('node', ['--input-type=module', '-e', npmHeader + `
      const loaded = await client.chats.load(process.env.CHAT_ID);
      const encrypted = await Promise.all(JSON.parse(process.env.EMBED_IDS).map(id => client.embeds.show(id)));
      console.log(JSON.stringify({ loaded, encrypted }));`], env, 'npm saved chat and owner embeds')
    : runLibrary('python3', ['-c', pipHeader + `
loaded = client.chats.load(os.environ['CHAT_ID'])
encrypted = [client.embeds.show(embed_id) for embed_id in json.loads(os.environ['EMBED_IDS'])]
print(json.dumps({'loaded': loaded, 'encrypted': encrypted}))`], env, 'pip saved chat and owner embeds');
}

function verifySdkSnapshot(snapshot: any, chatId: string, carrierId: string, ids: string[], contents: any[]): void {
  expect(snapshot.loaded.chat.id).toBe(chatId);
  expect(snapshot.loaded.chat.encrypted_chat_key).toBeTruthy();
  const messages = snapshot.loaded.messages.filter((message: any) => message.role === 'assistant');
  expect(messages).toHaveLength(1);
  expect(messages[0].encrypted_content).toBeTruthy();
  expect(messages[0].encrypted_content).not.toContain('Here are your supplied records');
  expect(messages[0].content).toContain(carrierId);
  const loaded = new Map((snapshot.loaded.embeds || []).map((embed: any) => [embed.embed_id || embed.id, embed]));
  for (const [index, id] of [carrierId, ...ids].entries()) {
    const decrypted: any = loaded.get(id);
    expect(decrypted, `SDK saved embed ${id}`).toBeTruthy();
    expect(decrypted.content).toEqual(contents[index]);
    const raw = snapshot.encrypted[index].embed;
    expect(raw.embed_id || raw.id).toBe(id);
    expect(typeof raw.encrypted_content).toBe('string');
    expect(raw.encrypted_content).not.toContain(contents[index].title);
    expect(raw).not.toHaveProperty('content');
    if (index > 0) expect(raw.parent_embed_id).toBe(carrierId);
  }
}

// contract-test: direct surface=cli assertions=authored-results.creation.relevant-and-independent,authored-results.eligibility.all-suitable-results,authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts,authored-results.groups.same-response-and-reuse,authored-results.lifecycle.encrypted-and-stable,authored-results.actions.truthful-and-explicit,authored-results.surfaces.shared-semantics,tv-titles.authoring.relevant-and-flexible,tv-titles.series.supplied-seasons,tv-titles.lifecycle.groups-and-actions
test('saved authored results preserve all admitted typed records through fresh CLI reads', async ({ page }: any, info: any) => {
  test.setTimeout(600_000);
  expect(process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'isolated fixture SDK key required').toBeTruthy();
  info.annotations.push({ type: 'migration-dependency', description: 'Native Rust CLI and Rust SDK conformance await the existing client migration; this covers the maintained npm CLI and npm/pip SDKs.' });
  const home = createWorkflowCliHome('authored-results');
  const wsTracePath = path.join(home, 'cli-ws-metadata.jsonl');
  const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
  let chatId: string | undefined;
  let retainedForSdk = false;
  try {
    await loginWorkflowCliViaPair(page, apiUrl, home, 'AUTHORED_RESULTS');
    // The marker replaces inference alone; no model/provider selection is made.
    fs.writeFileSync(wsTracePath, '', { mode: 0o600 });
    const probeUrl = pathToFileURL(path.join(__dirname, 'helpers/cli-ws-metadata-probe.mjs')).href;
    info.annotations.push({ type: 'diagnostic-probe', description: 'cli-ws-metadata/v1: metadata only, before original CLI WebSocket dispatch' });
    let creation;
    try {
      creation = await runWorkflowCli(apiUrl, home, ['chats', 'new',
        'Create cards from my supplied test records and label the recipe and social post as requested drafts. <<<TEST_MOCK:authored_results>>>', '--json'], 120_000,
        { OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'cli-authored-results-create',
          NODE_OPTIONS: `${process.env.NODE_OPTIONS || ''} --import=${probeUrl}`.trim(),
          OPENMATES_E2E_WS_TRACE_FILE: wsTracePath, OPENMATES_E2E_WS_TRACE_PROTOCOL: '1' });
    } finally {
      await info.attach('authored-results-cli-ws-metadata-v1', { path: wsTracePath, contentType: 'application/x-ndjson' });
    }
    // Attach real terminal capture even when a later assertion fails.
    expect(creation.recording, 'real terminal recording required').toBeTruthy();
    await info.attach('authored-results-cli-create', { path: creation.recording.videoPath, contentType: 'video/mp4' });
    await info.attach('authored-results-cli-create-manifest', { path: creation.recording.manifestPath, contentType: 'application/json' });
    const created = parseCliJson(creation, 'create saved authored chat');
    expect(created.error, 'CLI creation must complete before authored records can be read').toBeUndefined();
    expect(created.status).toBe('completed');
    chatId = created.chatId;
    expect(chatId).toMatch(/^[a-f0-9-]{36}$/);
    const refs = [...String(created.assistant).matchAll(/"embed_id"\s*:\s*"([a-f0-9-]+)"/g)];
    expect(refs).toHaveLength(1);
    const carrierId = refs[0][1];
    expect(created.assistant).toContain('The draft recipe and social post remain proposals.');
    expect(created.assistant).not.toContain('<<<TEST_MOCK:');

    const read = async (id: string) => parseCliJson(await runWorkflowCli(apiUrl, home,
      ['embeds', 'show', id, '--chat', chatId!, '--json'], 60_000), `read authored embed ${id}`);
    const carrier = await read(carrierId);
    const ids = verifyCarrier(carrier.content);
    const children = [];
    for (const [index, id] of ids.entries()) {
      const child = await read(id);
      expect(child.embedId).toBe(id);
      verifyChild(child.content, DOCUMENT.items[index]);
      children.push(child.content);
    }
    const contents = [carrier.content, ...children];

    // Drop local sync state and reload the authorized browser before fresh reads.
    await page.reload();
    clearWorkflowCliSyncCache(home);
    const saved = parseCliJson(await runWorkflowCli(apiUrl, home,
      ['chats', 'show', chatId!, '--json'], 90_000), 'fresh saved chat');
    const assistant = saved.messages.filter((message: any) => message.role === 'assistant');
    expect(assistant).toHaveLength(1);
    expect(assistant[0].content).toContain(carrierId);
    expect((await read(carrierId)).content).toEqual(carrier.content);
    for (const [index, id] of ids.entries()) expect((await read(id)).content).toEqual(children[index]);

    const anonymous = await page.request.get(`${apiUrl}/v1/sdk/embeds/${carrierId}`, { headers: { Authorization: '' } });
    expect([401, 403, 404]).toContain(anonymous.status());
    expect(await anonymous.text()).not.toContain(DOCUMENT.title);
    savedContext = { apiUrl, home, chatId: chatId!, carrierId, ids, contents };
    retainedForSdk = true;
  } finally {
    if (!retainedForSdk) {
      try { if (chatId) await runWorkflowCli(apiUrl, home, ['chats', 'delete', chatId, '--yes', '--json'], 30_000); }
      finally { removeWorkflowCliHome(home); }
    }
  }
});

// contract-test: direct surface=sdks.npm assertions=authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts,authored-results.groups.same-response-and-reuse,authored-results.lifecycle.encrypted-and-stable,authored-results.surfaces.shared-semantics,tv-titles.authoring.relevant-and-flexible,tv-titles.series.supplied-seasons,tv-titles.lifecycle.groups-and-actions
test('npm SDK decrypts the same saved authored carrier and typed children', async () => {
  test.setTimeout(240_000);
  expect(savedContext, 'prior CLI lifecycle must succeed').toBeTruthy();
  const { apiUrl, home, chatId, carrierId, ids, contents } = savedContext!;
  verifySdkSnapshot(await sdkSnapshot('npm', apiUrl, home, chatId, [carrierId, ...ids]), chatId, carrierId, ids, contents);
});

// contract-test: direct surface=sdks.pip assertions=authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts,authored-results.groups.same-response-and-reuse,authored-results.lifecycle.encrypted-and-stable,authored-results.surfaces.shared-semantics,tv-titles.authoring.relevant-and-flexible,tv-titles.series.supplied-seasons,tv-titles.lifecycle.groups-and-actions
test('pip SDK decrypts the same saved authored carrier and typed children', async () => {
  test.setTimeout(240_000);
  expect(savedContext, 'prior CLI lifecycle must succeed').toBeTruthy();
  const { apiUrl, home, chatId, carrierId, ids, contents } = savedContext!;
  verifySdkSnapshot(await sdkSnapshot('pip', apiUrl, home, chatId, [carrierId, ...ids]), chatId, carrierId, ids, contents);
});
