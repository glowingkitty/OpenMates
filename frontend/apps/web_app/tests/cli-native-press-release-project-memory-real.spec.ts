/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: required reason=real_inference_dev_only (native CLI saves a press style to Project Memories, a new chat reuses it)
// playwright-account: required reason=real_ai_personal_dev_only
/**
 * Real-inference, dev-only: the native Rust CLI saves a press style into a Project's Memories and a NEW
 * chat started with `chats new --project <uuid>` reuses it in its first turn. Run through
 * scripts/press_release_project_memory_cli_real_test.py; never in CI, no mocks.
 * "3,000" appears only in the saved style, never in the news prompt.
 */
import { test, expect, chromium, type Page, type TestInfo } from '@playwright/test';
import fs from 'node:fs';
import { spawn } from 'node:child_process';

const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { generateTotp, getTestAccount } = require('./signup-flow-helpers');
const { createRustHome, runRust, rustEnv } = require('./helpers/rust-cli-terminal');
const { parseJson, pickString } = require('./helpers/cli-native-fixtures');
const { naturalProjectName } = require('./helpers/project-names');

const APP = 'https://app.dev.openmates.org';
const API = 'https://api.dev.openmates.org';
const STYLE = "Our press style: always write 'Example Solar' (never 'ExampleSolar'), product name 'SunShare' in camel case, plain and friendly tone, no superlatives, English with AP style, end with ###. About paragraph: Example Solar GmbH, based in Leipzig, makes plug-in balcony solar kits for renters. Founded in 2021, the company has equipped more than 3,000 apartments in Germany.";
const NEWS = "All synthetic test data. Company: Example Solar GmbH, Leipzig, founded 2021, 24 employees, makes balcony solar kits for renters. News: on 18 November 2026 we launch SunShare, an app that lets neighbours in one building pool their balcony solar power. Pilot: 120 households in Leipzig saved on average 11 percent on electricity over six months (our own pilot data, May to October 2026). Available from 18 November in Germany, free for Example Solar customers, 2 EUR a month otherwise, at example.org/sunshare. Quote from Mara Example, CEO: she wants renters to share energy like they share a stairwell. Media contact: Jonas Example, press officer, press@example.org, +49 341 0000000. Release for immediate publication.";
const SAVE_PROMPT = `@Gemini-3.8-Flash Set up our press style for press releases and save it to this project's Memories so that you ask me before using it (load mode ask first). ${STYLE} Media contact: Jonas Example, press officer, press@example.org. Mara Example, CEO, is usually quoted.`;
const CONFIRM_PROMPT = "@Gemini-3.8-Flash Thanks. If the press style is not saved to this project's Memories yet, save it now; otherwise just confirm.";
const REUSE_PROMPT = `@Gemini-3.8-Flash Write a press release as a Word document about our app launch. ${NEWS} Skip all questions and the fact check, use your recommended headline and write it now. In your chat reply, also quote the release's About paragraph word for word.`;

test.describe.configure({ mode: 'serial', retries: 0, timeout: 2_400_000 });

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

/** Embed ids referenced as {"type":"document","embed_id":"..."} inside any string of the value. */
function documentEmbedIds(value: unknown): string[] {
  const ids = new Set<string>();
  const text = JSON.stringify(value);
  for (const m of text.matchAll(/\\?"type\\?"\s*:\s*\\?"document\\?"\s*,\s*\\?"embed_id\\?"\s*:\s*\\?"([^"\\]+)\\?"/g)) ids.add(m[1]);
  return [...ids];
}

// contract-test: direct surface=cli assertions=app-memories.conversation.explicit-approval,projects.memories.active-access,projects.focus.default-owned
// eslint-disable-next-line no-empty-pattern -- Playwright requires an object pattern; this test launches its own browser
test('native CLI saves a press style in Project Memories and a new chat reuses it', async ({}, info: TestInfo) => {
  if (process.env.CI || process.env.GITHUB_ACTIONS || process.env.OPENMATES_CI_ISOLATED === '1') {
    throw new Error('Real-inference proof is dev-only and must never run in CI.');
  }
  if (process.env.E2E_USE_MOCKS || process.env.E2E_USE_LIVE_MOCKS) {
    throw new Error('This proof requires real inference; mock replay must be disabled.');
  }
  const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || APP;
  if (!new URL(baseUrl).hostname.includes('.dev.')) throw new Error('This proof may target only the dev web host.');
  const account = getTestAccount();
  test.skip(!account.email, 'Test account credentials required.');
  const binary = process.env.OPENMATES_NATIVE_CLI || '';
  expect(binary && fs.existsSync(binary), 'OPENMATES_NATIVE_CLI must name the native CLI binary').toBeTruthy();
  for (const key of ['email', 'password', 'otpKey'] as const) expect(account[key], `test account ${key}`).toBeTruthy();

  const browser = await chromium.launch({ headless: true, executablePath: process.env.PW_CHROMIUM || undefined });
  const context = await browser.newContext({ baseURL: APP, viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2,
    recordVideo: { dir: info.outputPath('video'), size: { width: 1440, height: 1000 } } });
  // Never let this run touch a non-dev API host.
  await context.route('**/v1/**', (route) => {
    const host = new URL(route.request().url()).hostname;
    return host.startsWith('api.') && host.endsWith('.openmates.org') && host !== 'api.dev.openmates.org'
      ? route.abort('blockedbyclient') : route.continue();
  });
  const page: Page = await context.newPage();
  const home = createRustHome('press-memory-cli-real');
  // Opt-in refusal-site label (no ids, keys or content) so a turn_recovery_required run names its source.
  const env = { ...rustEnv(home, API, APP), OPENMATES_TEST_SEND_PHASE_DIAGNOSTIC: '1' };
  const evidence: Record<string, unknown> = { target: APP };
  let projectId = '';
  const chatIds: string[] = [];
  let signedIn = false;
  let lastStderr = '';
  const run = async (args: string[], timeoutMs = 120_000) => {
    const r = await runRust(binary, env, args, timeoutMs);
    lastStderr = String(r.stderr);
    // Never print stdout wholesale: client metadata can contain key material.
    expect(r.code, `${args.slice(0, 3).join(' ')} exit ${r.code}\nstderr: ${r.stderr}\nstdout tail: ${String(r.stdout).slice(-600)}`).toBe(0);
    return parseJson(r);
  };
  const shot = async (name: string) => {
    const path = info.outputPath(name);
    await page.screenshot({ path });
    await info.attach(name, { path, contentType: 'image/png' });
  };
  try {
    await loginToTestAccount(page, () => {}, async () => {}, { credentials: account });

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
      const useTwoFactor = page.getByTestId('auth-use-2fa');
      await expect(pinDisplay.or(useTwoFactor).first()).toBeVisible({ timeout: 15_000 });
      if (await useTwoFactor.isVisible()) {
        await useTwoFactor.click();
        await page.getByTestId('tfa-input').fill(generateTotp(account.otpKey, 0));
      }
      await expect(pinDisplay).toBeVisible({ timeout: 30_000 });
      const pin = ((await pinDisplay.textContent()) || '').replace(/\s/g, '');
      expect(pin).toMatch(/^[A-Z0-9]{6}$/);
      await waitFor(/Pairing PIN from the browser:/, 30_000);
      login.stdin.write(`${pin}\r`);
      const code = await Promise.race([exited, new Promise<number>((resolve) => setTimeout(() => resolve(-2), 90_000))]);
      const tail = output.slice(-500).replace(/#pair=[A-Za-z0-9]+/g, '#pair=<token>').replace(pin, '<pin>');
      expect(code, `native pair login exit code; output tail: ${tail}`).toBe(0);
    } finally { login.kill(); }
    signedIn = true;

    const created = await run(['projects', 'create', naturalProjectName('Press office'), '--write-policy', 'apply_and_show', '--personal', '--json']);
    projectId = collect(created, ['project_id', 'projectId', 'id'])[0] || '';
    expect(projectId).toMatch(/^[0-9a-f-]{36}$/i);
    fs.writeFileSync(info.outputPath('run-ids.private.json'), JSON.stringify({ projectId }), { mode: 0o600 });
    await run(['projects', 'settings', projectId, '--focus-activation', 'immediate', '--json']);

    // Chat 1: save the press style into the Project's Memories.
    const turn1 = await run(['chats', 'new', SAVE_PROMPT, '--project', projectId, '--personal', '--auto-approve', '--response-timeout-seconds', '420', '--json'], 600_000);
    const saveChat = pickString(turn1, ['chatId', 'chat_id']);
    expect(saveChat).toMatch(/^[0-9a-f-]{36}$/);
    chatIds.push(saveChat);
    const turn1b = await run(['chats', 'send', '--chat', saveChat, CONFIRM_PROMPT, '--personal', '--auto-approve', '--response-timeout-seconds', '420', '--json'], 600_000);
    Object.assign(evidence, { saveStatus: turn1.status, confirmStatus: turn1b.status });

    // Memories folder: soft-checked because the listing shape may differ.
    const listing = await runRust(binary, env, ['projects', 'items', 'list', projectId, '--personal', '--json'], 120_000);
    const listingText = `${listing.stdout}`;
    const memoryFiles = collect(parseJson(listing), ['path', 'name']).filter((p) => /\.md$/.test(p));
    const hasMemory = memoryFiles.length > 0 || (/memories\//.test(listingText) && /\.md/.test(listingText));
    Object.assign(evidence, { listExit: listing.code, memoryFiles });
    expect.soft(hasMemory, 'at least one .md file under .openmates/memories').toBe(true);

    // Chat 2: new chat of the same Project reuses the saved style.
    // The Ask first Project Memory is requested by id; --auto-approve-memories approves it.
    const turn2 = await run(['chats', 'new', REUSE_PROMPT, '--project', projectId, '--personal', '--auto-approve', '--auto-approve-memories', '--response-timeout-seconds', '420', '--json'], 600_000);
    evidence.memoryApproved = /Approved the requested memory categories/.test(lastStderr);
    expect.soft(evidence.memoryApproved, 'Ask first Project Memory approved on the reuse turn').toBe(true);
    const reuseChat = pickString(turn2, ['chatId', 'chat_id']);
    expect(reuseChat).toMatch(/^[0-9a-f-]{36}$/);
    chatIds.push(reuseChat);
    // Native read-back is recorded softly; the document assertion runs in the web app below.
    const showRun = await runRust(binary, env, ['chats', 'show', reuseChat, '--personal', '--json'], 120_000);
    const shown = showRun.code === 0 ? parseJson(showRun) : {};
    const embedTexts: string[] = [];
    const embedReads: Record<string, unknown>[] = [];
    for (const embedId of documentEmbedIds(shown)) {
      // The native CLI reads a document's text as its current version.
      const listRun = await runRust(binary, env, ['embeds', 'versions', 'list', embedId, '--json'], 120_000);
      const current = listRun.code === 0 ? Number(parseJson(listRun).current_version) : NaN;
      const read: Record<string, unknown> = { listExit: listRun.code, current };
      if (Number.isInteger(current) && current > 0) {
        const versionRun = await runRust(binary, env, ['embeds', 'versions', 'show', embedId, '--version', String(current), '--json'], 120_000);
        read.showExit = versionRun.code;
        if (versionRun.code === 0) embedTexts.push(collect(parseJson(versionRun), ['content']).join('\n'));
        else read.showError = String(versionRun.stderr).slice(0, 300);
      } else read.listError = String(listRun.stderr).slice(0, 300);
      embedReads.push(read);
    }
    const combined = `${JSON.stringify(shown)}\n${embedTexts.join('\n')}`;
    const models = [turn2.modelName, turn2.model_name, ...collect(shown, ['modelName', 'model_name'])].filter(Boolean);
    Object.assign(evidence, { reuseStatus: turn2.status, models, cliShowExit: showRun.code,
      cliShowError: showRun.code === 0 ? '' : String(showRun.stderr).slice(0, 300),
      documentEmbeds: embedTexts.length, embedReads, cliHas3000: /3,000/.test(combined) });
    expect.soft(showRun.code, 'native chats show of the reuse chat').toBe(0);
    expect(models.length, 'persisted assistant model of the reuse turn').toBeGreaterThan(0);
    for (const model of models) expect(String(model)).toMatch(/gemini.*3\.?8.*flash/i);
    expect(turn2.status, 'reuse turn status').toBe('completed');
    // "3,000" exists only in the saved Project Memory, so the reply proves the Memory reached this turn.
    const replyHas3000 = /3,000/.test(JSON.stringify(turn2));
    evidence.cliReplyHas3000 = replyHas3000;
    expect(replyHas3000, 'saved style fact "3,000" in the native CLI reply of the reuse turn').toBe(true);

    // Web proof frames of the CLI-created chat.
    await page.goto(`${APP}/`);
    await page.reload();
    await page.goto(`${APP}/#chat-id=${reuseChat}`);
    const reply = page.locator('[data-testid="message-assistant"]').last();
    await expect(reply, 'saved style fact "3,000" in the reuse reply shown on the web').toContainText('3,000', { timeout: 120_000 });
    await reply.getByText('3,000').first().scrollIntoViewIfNeeded();
    await shot('01-reuse-chat.png');
    // Document view: recorded softly (pages are images; the text check above is authoritative).
    const embed = page.locator('[data-testid="embed-preview"][data-app-id="docs"][data-status="finished"]').last();
    await expect.soft(embed, 'finished document embed in the CLI-created reuse chat').toBeVisible({ timeout: 60_000 });
    if (await embed.isVisible()) {
      await embed.getByTestId('result-preview-expand').click();
      const pages = page.getByTestId('doc-artifact-pages');
      await expect.soft(pages, 'document view opens').toBeVisible({ timeout: 60_000 });
      if (await pages.isVisible()) {
        await page.waitForTimeout(2_000);
        await shot('02-document.png');
        await pages.locator('.doc-canvas-scroll').evaluate((el) => el.scrollTo({ top: el.scrollHeight }));
        await page.waitForTimeout(1_500);
        await shot('03-document-end.png');
      }
    }
  } finally {
    const failures: string[] = [];
    const attempt = async (label: string, args: string[]) => {
      const r = await runRust(binary, env, args, 120_000).catch((error: unknown) => ({ code: -1, stdout: '', stderr: String(error) }));
      if (r.code !== 0) failures.push(`${label}: exit ${r.code} ${String(r.stderr).slice(0, 300)}`);
    };
    if (signedIn) {
      for (const id of chatIds) await attempt('chat delete', ['chats', 'delete', id, '--yes', '--personal']);
      if (projectId) await attempt('project delete', ['projects', 'delete', projectId, '--confirm', projectId, '--json']);
    }
    Object.assign(evidence, { cleanupFailures: failures });
    fs.writeFileSync(info.outputPath('press-memory-cli-real.json'), JSON.stringify(evidence, null, 2), { mode: 0o600 });
    await info.attach('press-memory-cli-real.json', { path: info.outputPath('press-memory-cli-real.json'), contentType: 'application/json' });
    fs.rmSync(home, { recursive: true, force: true });
    await context.close();
    await browser.close();
  }
});
