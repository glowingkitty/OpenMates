/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// playwright-account: required reason=real_ai_personal_dev_only
/**
 * Dev-only real proof, no mocks: the native Rust CLI runs a "recipe scaler" Python project with
 * `openmates apps code run --dir <project> --entry main.py` on the dev stack and prints the real
 * E2B output. No AI inference is involved (the personal account lease is used for its login and
 * consent state only). Run through scripts/cli_code_run_real_test.py; never in CI.
 */
import { test, expect, chromium, type Page, type TestInfo } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';

const { loginToTestAccount, allowE2bUpload } = require('./helpers/chat-test-helpers');
const { generateTotp, getTestAccount } = require('./signup-flow-helpers');
const { createRustHome, rustEnv } = require('./helpers/rust-cli-terminal');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const PROFILE = 'cli-terminal';
const proofContract = defineVideoProof({
  id: 'cli-native-code-run-real', title: 'Native CLI runs a recipe scaler project on E2B', surface: 'cli', devices: [PROFILE],
  transcript: [
    { id: 'run', text: 'openmates apps code run uploads the two project files and starts the run on E2B.', checkpoint: 'run-started', devices: [PROFILE] },
    { id: 'output', text: 'The terminal prints the scaled recipe that main.py computed in the sandbox.', checkpoint: 'run-output', devices: [PROFILE] },
  ],
  assertions: [
    { id: 'code-run.request.validated', checkpoint: 'run-started', visual: 'The terminal shows Starting Code Run for main.py (2 files).', devices: [PROFILE] },
    { id: 'code-run.e2b.upload-consent', checkpoint: 'run-output', visual: 'With upload allowed, the run finishes and prints Lemon pancakes for 6 with flour_g 600 and stock_ml 1200.', devices: [PROFILE] },
  ],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

const APP = 'https://app.dev.openmates.org';
const API = 'https://api.dev.openmates.org';

test.describe.configure({ mode: 'serial', retries: 0, timeout: 900_000 });

// contract-test: direct surface=cli assertions=code-run.e2b.upload-consent,code-run.request.validated,cli.runtime.native-rust
// eslint-disable-next-line no-empty-pattern -- Playwright requires an object pattern; this test launches its own browser
test('native CLI runs a recipe scaler project on E2B and prints its output', async ({}, info: TestInfo) => {
  if (process.env.CI || process.env.GITHUB_ACTIONS || process.env.OPENMATES_CI_ISOLATED === '1') {
    throw new Error('Real E2B proof is dev-only and must never run in CI.');
  }
  const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || APP;
  if (!new URL(baseUrl).hostname.includes('.dev.')) throw new Error('This proof may target only the dev web host.');
  const account = getTestAccount();
  test.skip(!account.email, 'Test account credentials required.');
  const binary = process.env.OPENMATES_NATIVE_CLI || '';
  expect(binary && fs.existsSync(binary), 'OPENMATES_NATIVE_CLI must name the native CLI binary').toBeTruthy();

  const browser = await chromium.launch({ headless: true, executablePath: process.env.PW_CHROMIUM || undefined });
  const context = await browser.newContext({ baseURL: APP, viewport: { width: 1440, height: 1000 } });
  await context.route('**/v1/**', (route) => {
    const host = new URL(route.request().url()).hostname;
    return host.startsWith('api.') && host.endsWith('.openmates.org') && host !== 'api.dev.openmates.org'
      ? route.abort('blockedbyclient') : route.continue();
  });
  const page: Page = await context.newPage();
  const home = createRustHome('code-run-real');
  const env = rustEnv(home, API, APP);
  const project = fs.mkdtempSync(path.join(os.tmpdir(), 'recipe-scaler-'));
  try {
    await loginToTestAccount(page, () => {}, async () => {}, { credentials: account });
    await allowE2bUpload(page);

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
      // The tail shows why (e.g. an exec error of a foreign-architecture binary); pair tokens are masked.
      const tail = output.slice(-400).replace(/#pair=[A-Za-z0-9]+/g, '#pair=<token>');
      throw new Error(`native login did not print ${pattern}; output tail: ${tail}`);
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
      expect(code, 'native pair login exit code').toBe(0);
    } finally { login.kill(); }

    fs.writeFileSync(path.join(project, 'recipes.json'), JSON.stringify({
      'Lemon pancakes': { serves: 2, flour_g: 200, milk_ml: 300, lemons: 1 },
      'Tomato soup': { serves: 4, tomatoes: 8, stock_ml: 800 },
    }, null, 2));
    fs.writeFileSync(path.join(project, 'main.py'), [
      'import json', '', 'TARGET_SERVINGS = 6', '',
      'with open("recipes.json") as handle:', '    recipes = json.load(handle)', '',
      'for name, recipe in recipes.items():',
      '    factor = TARGET_SERVINGS / recipe["serves"]',
      '    print(f"{name} for {TARGET_SERVINGS}:")',
      '    for ingredient, amount in recipe.items():',
      '        if ingredient != "serves":', '            print(f"  {ingredient}: {amount * factor:g}")', '',
    ].join('\n'));

    // Real terminal recording of the command; consent is already allowed, so the run starts at once.
    const outputDir = info.outputPath('cli-terminal-code-run');
    const result = spawnSync('python3', [
      path.resolve(__dirname, '../../../../scripts/cli_video_capture.py'),
      '--output-dir', outputDir, '--target-environment', API, '--display-number', '232',
      '--timeout-seconds', '240', '--no-response-media', '--',
      binary, 'apps', 'code', 'run', '--dir', project, '--entry', 'main.py',
    ], { env: env as NodeJS.ProcessEnv, encoding: 'utf8', timeout: 300_000 });
    expect(result.status, `terminal capture failed: ${String(result.stdout).slice(-300)} ${String(result.stderr).slice(-300)}`).toBe(0);
    const transcript = fs.readFileSync(path.join(outputDir, 'transcript.txt'), 'utf8');
    const proof = createVideoProofRuntime(proofContract, { device: PROFILE, attach: info.attach.bind(info) });
    await proof.assert('code-run.request.validated', async () => {
      expect(transcript).toContain('Starting Code Run for main.py (2 files)');
    });
    await proof.checkpoint('run-started');
    await proof.assert('code-run.e2b.upload-consent', async () => {
      expect(transcript).toContain('Lemon pancakes for 6:');
      expect(transcript).toContain('flour_g: 600');
      expect(transcript).toContain('stock_ml: 1200');
    });
    await proof.checkpoint('run-output');
    await proof.attach();
    await info.attach('openmates-cli-real-terminal-code-run-video', { path: path.join(outputDir, 'raw-terminal.mp4'), contentType: 'video/mp4' });
    await info.attach('openmates-cli-real-terminal-code-run-transcript', { path: path.join(outputDir, 'transcript.txt'), contentType: 'text/plain' });
  } finally {
    fs.rmSync(project, { recursive: true, force: true });
    fs.rmSync(home, { recursive: true, force: true });
    await browser.close();
  }
});
