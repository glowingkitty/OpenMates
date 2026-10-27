import { spawn, type ChildProcess } from 'node:child_process';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { expect, test } from './cookie-audit';

const root = path.resolve(__dirname, '../../../../..');
export const website = 'http://127.0.0.1:5180';
export const app = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'http://127.0.0.1:5173').origin;
export const api = 'http://127.0.0.1:8000';
const environment = {
  ...process.env,
  PUBLIC_WEBSITE_URL: website,
  PUBLIC_WEBAPP_URL: app,
  PUBLIC_NEWSLETTER_API_BASE_URL: api
};

function terminateGroup(child: ChildProcess | null, signal: NodeJS.Signals = 'SIGTERM'): void {
  if (!child?.pid) return;
  try { process.kill(-child.pid, signal); } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ESRCH') throw error;
  }
}

async function command(args: string[], timeoutMs: number): Promise<string> {
  const child = spawn('corepack', ['pnpm', ...args], { cwd: root, env: environment, detached: true, stdio: ['ignore', 'pipe', 'pipe'] });
  let output = '';
  const append = (chunk: Buffer) => { output = (output + chunk.toString()).slice(-24_000); };
  child.stdout?.on('data', append);
  child.stderr?.on('data', append);
  const timer = setTimeout(() => terminateGroup(child, 'SIGKILL'), timeoutMs);
  try {
    const code = await new Promise<number>((resolve, reject) => {
      child.once('error', reject);
      child.once('exit', (status) => resolve(status ?? -1));
    });
    if (code !== 0) throw new Error(`pnpm ${args.join(' ')} exited ${code}:\n${output}`);
    return output;
  } finally {
    clearTimeout(timer);
  }
}

async function waitForWebsite(child: ChildProcess, output: () => string): Promise<void> {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null || child.signalCode !== null) throw new Error(`Website preview exited before becoming ready:\n${output()}`);
    try {
      const response = await fetch(website, { signal: AbortSignal.timeout(2_000) });
      if (response.ok) return;
    } catch { /* The preview socket is not ready yet. */ }
    await delay(250);
  }
  throw new Error(`Website preview did not become ready on port 5180 within 30 seconds:\n${output()}`);
}

export function watchPrivateStartup(page: import('@playwright/test').Page) {
  const privateRequests: string[] = [];
  const sockets: string[] = [];
  page.on('request', (request) => {
    const url = request.url();
    if (url.startsWith(app) || /\/v1\/(auth|users|chats|sync|workflows)(?:\/|\?|$)/.test(url)) privateRequests.push(url);
  });
  page.on('websocket', (socket) => sockets.push(socket.url()));
  return () => {
    expect(privateRequests, 'public routes must not start the app session or owner API').toEqual([]);
    expect(sockets, 'public routes must not open WebSockets').toEqual([]);
  };
}

export const site = (pathname: string) => `${website}${pathname}`;

// Register the standalone build and preview only inside isolated CI specs.
export function useWebsitePreview(): void {
  let preview: ChildProcess | null = null;

  test.beforeEach(async ({ page }) => {
    await page.route('**/api/server-status', route => route.fulfill({
      json: { anonymous_free_usage: { active: true, can_send_text: true } },
    }));
  });

  test.beforeAll(async () => {
    test.setTimeout(180_000);
    await command(['--filter', 'website...', 'install', '--frozen-lockfile', '--ignore-scripts'], 50_000);
    const build = await command(['--filter', 'website...', 'run', 'build'], 75_000);
    expect(build).toContain('[plugin public-bundle-boundary] Website client JS:');
    preview = spawn('corepack', ['pnpm', '--dir', 'frontend/apps/website', 'exec', 'vite', 'preview', '--host', '127.0.0.1', '--port', '5180', '--strictPort'], {
      cwd: root, env: environment, detached: true, stdio: ['ignore', 'pipe', 'pipe']
    });
    let previewOutput = '';
    const append = (chunk: Buffer) => { previewOutput = (previewOutput + chunk.toString()).slice(-4_000); };
    preview.stdout?.on('data', append);
    preview.stderr?.on('data', append);
    preview.once('error', (error) => { previewOutput += `\n${error.message}`; });
    try { await waitForWebsite(preview, () => previewOutput); } catch (error) { terminateGroup(preview, 'SIGKILL'); throw error; }
  });

  test.afterAll(async () => {
    const child = preview;
    preview = null;
    if (!child) return;
    terminateGroup(child);
    if (child.exitCode === null && child.signalCode === null) {
      await Promise.race([new Promise<void>((resolve) => child.once('exit', () => resolve())), delay(5_000)]);
    }
    if (child.exitCode === null) terminateGroup(child, 'SIGKILL');
  });

}

