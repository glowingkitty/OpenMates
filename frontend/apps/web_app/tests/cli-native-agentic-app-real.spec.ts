// proof-video: not_required reason=real_inference_dev_only (CLI JSON contract plus web screenshots; never run in CI)
/** Real inference acceptance: hosted recipe app through the native Rust CLI. Held out of isolated CI. */
import { test, expect, chromium, type Page, type TestInfo } from '@playwright/test';
import fs from 'node:fs';
import { spawn } from 'node:child_process';
// eslint-disable-next-line @typescript-eslint/no-require-imports -- shared CommonJS helpers
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
// eslint-disable-next-line @typescript-eslint/no-require-imports -- shared CommonJS helpers
const { generateTotp } = require('./signup-flow-helpers');
// eslint-disable-next-line @typescript-eslint/no-require-imports -- shared CommonJS helpers
const { createRustHome, runRust, rustEnv } = require('./helpers/rust-cli-terminal');
// eslint-disable-next-line @typescript-eslint/no-require-imports -- shared CommonJS helpers
const { parseJson, pickString } = require('./helpers/cli-native-fixtures');

// playwright-account: required reason=real_ai_personal_dev_only
const enabled = process.env.AGENTIC_APP_REAL_AI_DEV === '1';
const APP = 'https://app.dev.openmates.org';
const API = 'https://api.dev.openmates.org';
const PROMPT =
  '@Gemini-3.8-Flash Build me a simple recipe web app where I can add recipes with ingredients and steps and see them in a list. Keep it small.';
test.describe.configure({ mode: 'serial', retries: 0, timeout: 1_200_000 });
test.skip(!enabled, 'Requires explicit dev-only real-inference execution and the personal account lease.');

type Row = { embed_id?: string; kind?: string; path?: string | null; status?: string; code?: string };

/** Every string under `keys` anywhere in a decoded JSON value. */
function collect(value: unknown, keys: string[], out: string[] = []): string[] {
  if (Array.isArray(value)) value.forEach((entry) => collect(entry, keys, out));
  else if (value && typeof value === 'object') {
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
      if (keys.includes(key) && typeof entry === 'string') out.push(entry);
      else collect(entry, keys, out);
    }
  }
  return out;
}

// contract-test: direct surface=cli assertions=projects.files.application-single-source,projects.files.adopt-embed
// eslint-disable-next-line no-empty-pattern -- Playwright requires an object pattern; this test launches its own browser
test('real Gemini turn builds a hosted recipe app into a new Project via the native CLI', async ({}, info: TestInfo) => {
  // The dev host's installed Chromium may differ from the repo's Playwright build (PW_CHROMIUM).
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PW_CHROMIUM || undefined });
  const binary = process.env.OPENMATES_NATIVE_CLI || '';
  expect(binary && fs.existsSync(binary), 'OPENMATES_NATIVE_CLI must name the native CLI binary').toBeTruthy();
  for (const key of ['EMAIL', 'PASSWORD', 'OTP_KEY']) expect(process.env[`OPENMATES_PERSONAL_TEST_ACOUNT_${key}`]).toBeTruthy();
  const context = await browser.newContext({ baseURL: APP, viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2 });
  // Never let this run touch a non-dev API host.
  await context.route('**/v1/**', (route) => {
    const host = new URL(route.request().url()).hostname;
    return host.startsWith('api.') && host.endsWith('.openmates.org') && host !== 'api.dev.openmates.org'
      ? route.abort('blockedbyclient') : route.continue();
  });
  const page: Page = await context.newPage();
  const home = createRustHome('agentic-app-real');
  const env = { ...rustEnv(home, API, APP), OPENMATES_TEST_SEND_PHASE_DIAGNOSTIC: '1' };
  const evidence: Record<string, unknown> = { target: APP };
  let chatId = '';
  let created: string[] = [];
  let signedIn = false;
  const run = async (args: string[], timeoutMs = 120_000) => {
    const r = await runRust(binary, env, args, timeoutMs);
    // Never print stdout wholesale: client metadata can contain key material.
    expect(r.code, `${args.slice(0, 3).join(' ')} exit ${r.code}\nstderr: ${r.stderr}\nstdout tail: ${String(r.stdout).slice(-600)}`).toBe(0);
    return parseJson(r);
  };
  const projectIds = async () => collect(await run(['projects', 'list', '--personal', '--json']), ['project_id', 'projectId', 'id']);
  try {
    await loginToTestAccount(page, () => {}, async () => {}, { credentials: {
      email: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_EMAIL,
      password: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_PASSWORD,
      otpKey: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_OTP_KEY,
    } });

    // The pair login needs a terminal for the PIN prompt. `script` provides the
    // pty; the terminal recorder used in CI is not installed on the dev host.
    const login = spawn('script', ['-qfec', `"${binary}" login`, '/dev/null'], { env, stdio: ['pipe', 'pipe', 'pipe'] });
    let output = '';
    login.stdout.on('data', (chunk: Buffer) => { output += chunk.toString(); });
    login.stderr.on('data', (chunk: Buffer) => { output += chunk.toString(); });
    const exited = new Promise<number>((resolve) => login.on('exit', (code) => resolve(code ?? -1)));
    const waitFor = async (pattern: RegExp, timeoutMs: number) => {
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        const match = output.match(pattern);
        if (match) return match;
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
      throw new Error(`native login did not print ${pattern}`);
    };
    try {
      const token = (await waitFor(/#pair=([A-Za-z0-9]+)/, 30_000))[1];
      await page.goto(`${APP}/#pair=${token}`);
      const allow = page.getByTestId('pair-allow-button');
      await expect(allow).toBeVisible({ timeout: 15_000 });
      await allow.click();
      const pinDisplay = page.getByTestId('pair-pin-display');
      // The personal account has a passkey, so approval asks for an identity
      // check; answer it with the account's own 2FA code.
      const useTwoFactor = page.getByTestId('auth-use-2fa');
      await expect(pinDisplay.or(useTwoFactor).first()).toBeVisible({ timeout: 15_000 });
      if (await useTwoFactor.isVisible()) {
        await useTwoFactor.click();
        await page.getByTestId('tfa-input').fill(generateTotp(process.env.OPENMATES_PERSONAL_TEST_ACOUNT_OTP_KEY, 0));
      }
      await expect(pinDisplay).toBeVisible({ timeout: 30_000 });
      const pin = ((await pinDisplay.textContent()) || '').replace(/\s/g, '');
      expect(pin).toMatch(/^[A-Z0-9]{6}$/);
      await waitFor(/Pairing PIN from the browser:/, 30_000);
      // The prompt reads in raw mode, where Enter is a carriage return.
      login.stdin.write(`${pin}\r`);
      const code = await Promise.race([exited, new Promise<number>((resolve) => setTimeout(() => resolve(-2), 90_000))]);
      // The tail holds prompts and typed errors only; the pair token and PIN are masked.
      const tail = output.slice(-500).replace(/#pair=[A-Za-z0-9]+/g, '#pair=<token>').replace(pin, '<pin>');
      expect(code, `native pair login exit code; output tail: ${tail}`).toBe(0);
    } finally { login.kill(); }
    signedIn = true;

    const baseline = new Set(await projectIds());

    const turn = await run(['chats', 'new', PROMPT, '--json'], 900_000);
    chatId = pickString(turn, ['chatId', 'chat_id']);
    expect(chatId).toMatch(/^[0-9a-f-]{36}$/);
    const creations: unknown[] = turn.projectCreations ?? turn.project_creations ?? [];
    const adoptions: Row[] = turn.projectEmbedAdoptions ?? turn.project_embed_adoptions ?? [];
    const cardIds = collect(creations, ['projectId', 'project_id']);
    created = [...new Set([...cardIds, ...(await projectIds()).filter((id) => !baseline.has(id))])];

    const showModels = collect(await run(['chats', 'show', chatId, '--json']), ['modelName', 'model_name']);
    const models = [turn.modelName, turn.model_name, ...showModels].filter(Boolean) as string[];
    const files = adoptions.filter((row) => row.kind === 'file');
    const applications = adoptions.filter((row) => row.kind === 'application');
    let listed: string[] = [];
    if (created.length) {
      listed = collect(await run(['projects', 'hosted', 'list', created[0], '--json']), ['path']);
    }
    Object.assign(evidence, { status: turn.status, models, creations: creations.length, projectIds: created.length,
      adoptions: adoptions.map(({ kind, path, status, code }) => ({ kind, path, status, code })), listed });
    expect.soft(turn.status).toBe('completed');
    expect.soft(models.length, 'a persisted assistant model name').toBeGreaterThan(0);
    for (const model of models) expect.soft(model).toMatch(/gemini.*3\.?8.*flash/i);
    expect.soft(creations.length, 'one Project creation card').toBeGreaterThanOrEqual(1);
    expect.soft(created.length, 'a Project created by this run').toBeGreaterThanOrEqual(1);
    for (const row of adoptions) expect.soft(row.status, JSON.stringify(row)).toBe('adopted');
    expect.soft(files.some((row) => String(row.path).startsWith('web-app/'))).toBe(true);
    expect.soft(listed.some((path) => path.startsWith('web-app/')), 'Project files under web-app/').toBe(true);
    expect.soft(applications).toHaveLength(1);
    for (const row of files) expect.soft(listed).toContain(row.path);

    // Reload first so the web client syncs the CLI-created chat, then open it.
    await page.goto(`${APP}/`);
    await page.reload();
    await page.goto(`${APP}/#chat-id=${chatId}`);
    const embed = page.locator('[data-testid="embed-preview"][data-app-id="code"]').first();
    await expect.soft(embed).toBeVisible({ timeout: 90_000 });
    await page.screenshot({ path: info.outputPath('chat-with-application-embed.png'), fullPage: true });

    if (created.length) {
      await page.goto(`${APP}/#project-id=${created[0]}`);
      await expect.soft(page.getByTestId('project-tabs')).toBeVisible({ timeout: 60_000 });
      await page.getByTestId('project-tab-folders').click();
      const folder = page.getByTestId('project-folder-card').filter({ hasText: 'web-app' }).first();
      await expect.soft(folder).toBeVisible({ timeout: 60_000 });
      await page.screenshot({ path: info.outputPath('project-with-files.png'), fullPage: true });
      if (await folder.isVisible()) {
        await folder.click();
        await expect.soft(page.getByTestId('project-item-card').first()).toBeVisible({ timeout: 60_000 });
        await page.screenshot({ path: info.outputPath('project-web-app-folder.png'), fullPage: true });
      }
    }
  } finally {
    const failures: string[] = [];
    const attempt = async (label: string, args: string[]) => {
      const r = await runRust(binary, env, args, 120_000).catch((error) => ({ code: -1, stdout: '', stderr: String(error) }));
      if (r.code !== 0) failures.push(`${label}: exit ${r.code} ${r.stderr.slice(0, 300)}`);
      return r;
    };
    if (chatId) await attempt('chat delete', ['chats', 'delete', chatId, '--yes', '--personal']);
    for (const id of created) await attempt('project delete', ['projects', 'delete', id, '--confirm', id, '--personal', '--json']);
    if (signedIn) {
      const drafts = await attempt('drafts list', ['drafts', 'list', '--refresh', '--json']);
      if (chatId && drafts.stdout.includes(chatId)) failures.push('a draft of this run remains');
    }
    Object.assign(evidence, { cleanupFailures: failures });
    fs.writeFileSync(info.outputPath('agentic-app-real.json'), JSON.stringify(evidence, null, 2), { mode: 0o600 });
    await info.attach('agentic-app-real.json', { path: info.outputPath('agentic-app-real.json'), contentType: 'application/json' });
    fs.rmSync(home, { recursive: true, force: true });
    await context.close();
    await browser.close();
    expect.soft(failures, 'cleanup').toEqual([]);
  }
});
