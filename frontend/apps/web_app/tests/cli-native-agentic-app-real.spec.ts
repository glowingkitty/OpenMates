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
// eslint-disable-next-line @typescript-eslint/no-require-imports -- shared CommonJS helpers
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const proofContract = defineVideoProof({
  id: 'cli-native-agentic-app-real',
  title: 'A recipe app request builds a hosted Project, records a browser test and commits',
  surface: 'web',
  devices: ['web-laptop'],
  domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'app-built', text: 'The chat shows the recipe app built by the assistant in a new Project.', checkpoint: 'agentic-app-embed-visible', devices: ['web-laptop'] },
    { id: 'test-recorded', text: 'The recorded browser test opens with its video beside the step timeline.', checkpoint: 'agentic-test-result-visible', devices: ['web-laptop'] },
    { id: 'preview-running', text: 'The app runs in the live preview.', checkpoint: 'agentic-preview-running', devices: ['web-laptop'] },
    { id: 'project-files', text: 'The Project folder web-app holds the application card and its files.', checkpoint: 'agentic-project-files', devices: ['web-laptop'] },
  ],
  assertions: [
    { id: 'agentic_app.embed_visible', checkpoint: 'agentic-app-embed-visible', visual: 'An application card from the code app is visible in the chat.', devices: ['web-laptop'] },
    { id: 'agentic_app.test_result', checkpoint: 'agentic-test-result-visible', visual: 'The test result fullscreen shows a video and a step timeline.', devices: ['web-laptop'] },
    { id: 'agentic_app.preview', checkpoint: 'agentic-preview-running', visual: 'The preview frame shows the recipe app, not a blank page.', devices: ['web-laptop'] },
    { id: 'agentic_app.project_files', checkpoint: 'agentic-project-files', visual: 'The web-app folder lists the application card and files.', devices: ['web-laptop'] },
  ],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

// playwright-account: required reason=real_ai_personal_dev_only
const enabled = process.env.AGENTIC_APP_REAL_AI_DEV === '1';
const APP = 'https://app.dev.openmates.org';
const API = 'https://api.dev.openmates.org';
const PROMPT =
  '@Gemini-3.8-Flash Build me a simple recipe web app where I can add recipes with ingredients and steps and see them in a list. Keep it small.';
const TEST_PROMPT =
  'Add a browser test that adds one recipe and checks it appears in the list, run it, and commit when it passes.';
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

/** Every number under `keys` anywhere in a decoded JSON value. */
function numbersUnder(value: unknown, keys: string[], out: number[] = []): number[] {
  if (Array.isArray(value)) value.forEach((entry) => numbersUnder(entry, keys, out));
  else if (value && typeof value === 'object') {
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
      if (keys.includes(key) && typeof entry === 'number') out.push(entry);
      else numbersUnder(entry, keys, out);
    }
  }
  return out;
}

/** Ids of embeds whose type field equals `type`, anywhere in a decoded JSON value. */
function embedIdsOfType(value: unknown, type: string, out: string[] = []): string[] {
  if (Array.isArray(value)) value.forEach((entry) => embedIdsOfType(entry, type, out));
  else if (value && typeof value === 'object') {
    const row = value as Record<string, unknown>;
    const kind = row.type ?? row.embed_type ?? row.embedType ?? row.skill_id ?? row.skillId;
    const id = row.embed_id ?? row.embedId;
    if (kind === type && typeof id === 'string' && !out.includes(id)) out.push(id);
    Object.values(row).forEach((entry) => embedIdsOfType(entry, type, out));
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
  // Records the web part (chat, test result fullscreen, preview, Project folder) as the result video.
  const context = await browser.newContext({ baseURL: APP, viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2,
    recordVideo: { dir: info.outputPath('video'), size: { width: 1440, height: 1000 } } });
  // Never let this run touch a non-dev API host.
  await context.route('**/v1/**', (route) => {
    const host = new URL(route.request().url()).hostname;
    return host.startsWith('api.') && host.endsWith('.openmates.org') && host !== 'api.dev.openmates.org'
      ? route.abort('blockedbyclient') : route.continue();
  });
  const page: Page = await context.newPage();
  const proof = createVideoProofRuntime(proofContract, {
    device: 'web-laptop', attach: info.attach.bind(info), captureFrame: () => page.screenshot({ type: 'png' }),
  });
  // Soft-asserted flows may skip a checkpoint; a missing one shows in the proof, not as a crash.
  const checkpoint = (id: string) => proof.checkpoint(id).catch((error: unknown) => {
    Object.assign(evidence, { [`checkpoint_${id}`]: String(error).slice(0, 200) });
  });
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
    // Recorded early so a leftover chat can be removed if the run is cut short.
    fs.writeFileSync(info.outputPath('run-ids.private.json'), JSON.stringify({ chatId }), { mode: 0o600 });
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
    // Card status and error code only (no names): explains a creation that failed.
    const creationOutcomes = (creations as Array<Record<string, unknown>>).map((card) => ({
      status: card.status, errorCode: card.errorCode ?? card.error_code, location: card.location,
    }));
    Object.assign(evidence, { creationOutcomes });
    Object.assign(evidence, { status: turn.status, models, creations: creations.length, projectIds: created.length,
      adoptions: adoptions.map(({ kind, path, status, code }) => ({ kind, path, status, code })), listed });
    const focusPersisted = collect(creations, []).length === 0
      ? (creations as Array<Record<string, unknown>>).map((card) => card.focusPersisted ?? card.focus_persisted) : [];
    Object.assign(evidence, { focusPersisted });
    expect.soft(focusPersisted.every((value) => value === true), 'Project focus stored as the chat active focus').toBe(true);
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
    // A runnable app needs a script entry; keep the raw turn privately when one is missing.
    const hasScript = listed.some((path) => /\.(jsx?|tsx?|svelte|vue)$/.test(path) && !/vite\.config\./.test(path));
    expect.soft(hasScript, `a script source among Project files: ${listed.join(', ')}`).toBe(true);
    if (!hasScript) {
      fs.writeFileSync(info.outputPath('turn-without-script.private.json'),
        JSON.stringify(await run(['chats', 'show', chatId, '--json'])), { mode: 0o600 });
    }

    // Second turn: the assistant writes a browser test, runs it in E2B with a
    // recording, and commits the Project once it is green.
    let testResultId = '';
    if (created.length) {
      const commitsBefore = collect(await run(['projects', 'commits', 'list', created[0], '--json']), ['commit_id', 'commitId']);
      const testTurn = await run(['chats', 'send', '--chat', chatId, TEST_PROMPT, '--json'], 900_000);
      const shown = await run(['chats', 'show', chatId, '--json']);
      const testResults = embedIdsOfType(shown, 'test_result');
      testResultId = testResults[testResults.length - 1] || '';
      let result: Record<string, unknown> = {};
      if (testResultId) {
        const numbers = numbersUnder(await run(['embeds', 'versions', 'list', testResultId, '--json']), ['version_number', 'versionNumber']);
        const latest = String(numbers.length ? Math.max(...numbers) : 1);
        result = await run(['embeds', 'test-result', testResultId, '--version', latest, '--json']);
      }
      const typed = (result.test_result ?? {}) as Record<string, unknown>;
      const assets = collect(typed, ['asset_id', 'assetId', 'path']);
      const commitsAfter = collect(await run(['projects', 'commits', 'list', created[0], '--json']), ['commit_id', 'commitId']);
      const listedAfter = collect(await run(['projects', 'hosted', 'list', created[0], '--json']), ['path']);
      Object.assign(evidence, { testTurn: { status: testTurn.status, testResults: testResults.length,
        kind: typed.kind, outcome: typed.status ?? typed.run_status ?? typed.outcome,
        videoEvidence: assets.some((value) => /\.webm$/i.test(value)) || JSON.stringify(typed).includes('video'),
        steps: Array.isArray(typed.steps) ? typed.steps.length : 0,
        commitsBefore: commitsBefore.length, commitsAfter: commitsAfter.length,
        testFiles: listedAfter.filter((path) => /tests?\//.test(path)) } });
      expect.soft(testTurn.status).toBe('completed');
      expect.soft(testResultId, 'a test_result embed in the chat').not.toBe('');
      expect.soft(typed.kind, 'browser test').toBe('browser');
      expect.soft(JSON.stringify(typed), 'recorded video evidence').toMatch(/webm|video/i);
      expect.soft(listedAfter.some((path) => /^web-app\/.*tests?\//.test(path)), 'test file stored as a Project file').toBe(true);
      expect.soft(commitsAfter.length, 'a Project commit after green tests').toBeGreaterThan(commitsBefore.length);
    }

    // Reload first so the web client syncs the CLI-created chat, then open it.
    await page.goto(`${APP}/`);
    await page.reload();
    await page.goto(`${APP}/#chat-id=${chatId}`);
    const embed = page.locator('[data-testid="embed-preview"][data-app-id="code"]').first();
    await expect.soft(embed).toBeVisible({ timeout: 90_000 });
    // Collapsed activity row names the creation; the focus pill shows the active Project focus.
    const toggle = page.getByTestId('assistant-activity-toggle').first();
    await expect.soft(toggle).toHaveAttribute('title', /Created project/, { timeout: 30_000 });
    await page.screenshot({ path: info.outputPath('chat-with-application-embed.png'), fullPage: true });
    await checkpoint('agentic-app-embed-visible');
    await toggle.click();
    await expect.soft(page.getByTestId('project-created-card').first()).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: info.outputPath('chat-activity-expanded.png'), fullPage: true });

    // Start the live preview from the chat's application card and wait for the running app.
    if (await embed.isVisible()) {
      await toggle.click();
      // In chat the card body is not a click target; the expand control opens the fullscreen.
      await embed.getByTestId('result-preview-expand').click();
      const start = page.getByTestId('application-start-preview');
      const frame = page.getByTestId('application-preview-iframe');
      await expect.soft(start.or(frame).first(), 'application fullscreen').toBeVisible({ timeout: 30_000 });
      if (await start.isVisible() && await start.isEnabled()) await start.click();
      // Bounded well below the test timeout so cleanup always runs.
      if (await start.or(frame).first().isVisible()) {
        await expect.soft(frame, 'running application preview').toBeVisible({ timeout: 240_000 });
      }
      if (await frame.isVisible()) {
        // The app renders inside the frame; a blank body means it did not boot.
        const body = page.frameLocator('[data-testid="application-preview-iframe"]').locator('body');
        await expect.soft(body).not.toBeEmpty({ timeout: 60_000 });
        Object.assign(evidence, { previewText: ((await body.innerText().catch(() => '')) || '').slice(0, 300) });
      } else {
        Object.assign(evidence, {
          previewStatus: await page.getByTestId('application-preview-status').innerText().catch(() => ''),
          previewLogs: (await page.getByTestId('application-preview-logs').innerText().catch(() => '')).slice(-1500),
        });
      }
      await page.screenshot({ path: info.outputPath('application-preview-running.png'), fullPage: true });
      await checkpoint('agentic-preview-running');
      const stop = page.getByTestId('application-stop-preview');
      if (await stop.isVisible() && await stop.isEnabled()) await stop.click();
    }

    // The recorded browser test in the web chat: fullscreen with video and step timeline.
    if (testResultId) {
      await page.goto(`${APP}/#chat-id=${chatId}`);
      const card = page.locator('[data-testid="embed-preview"][data-skill-id="test_result"]').last();
      await expect.soft(card, 'test result card in chat').toBeVisible({ timeout: 90_000 });
      if (await card.isVisible()) {
        await card.scrollIntoViewIfNeeded();
        await page.screenshot({ path: info.outputPath('chat-test-result-card.png') });
        await card.getByTestId('result-preview-expand').click();
        const body = page.getByTestId('test-result-fullscreen-body');
        await expect.soft(body).toBeVisible({ timeout: 30_000 });
        await expect.soft(page.getByTestId('test-result-video'), 'recorded test video').toBeVisible({ timeout: 60_000 });
        await expect.soft(page.getByTestId('test-result-timeline')).toBeVisible();
        const video = page.getByTestId('test-result-video');
        if (await video.isVisible()) {
          await video.evaluate((el: HTMLVideoElement) => { el.muted = true; return el.play(); }).catch(() => undefined);
          await page.waitForTimeout(4_000);
        }
        await page.screenshot({ path: info.outputPath('test-result-fullscreen.png') });
        await checkpoint('agentic-test-result-visible');
        await page.keyboard.press('Escape');
      }
    }

    if (created.length) {
      await page.goto(`${APP}/#project-id=${created[0]}`);
      await expect.soft(page.getByTestId('project-tabs')).toBeVisible({ timeout: 60_000 });
      await page.getByTestId('project-tab-folders').click();
      const folder = page.getByTestId('project-virtual-folder-card').filter({ hasText: 'web-app' }).first();
      await expect.soft(folder).toBeVisible({ timeout: 60_000 });
      await page.screenshot({ path: info.outputPath('project-with-files.png'), fullPage: true });
      if (await folder.isVisible()) {
        await folder.click();
        await expect.soft(page.getByTestId('project-item-card').first()).toBeVisible({ timeout: 60_000 });
        await expect.soft(page.getByText('Code snippet')).toHaveCount(0);
        // The application card must resolve to its real preview, not stay on the loading tile.
        await expect.soft(page.getByTestId('project-item-card').first(), 'application card in folder').toContainText(/files/, { timeout: 60_000 });
        await page.screenshot({ path: info.outputPath('project-web-app-folder.png'), fullPage: true });
        await checkpoint('agentic-project-files');
      }
    }
  } finally {
    const failures: string[] = [];
    const attempt = async (label: string, args: string[]) => {
      const r = await runRust(binary, env, args, 120_000).catch((error: unknown) => ({ code: -1, stdout: '', stderr: String(error) }));
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
