/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Real web-to-device Task sync and disconnected replay on isolated GitHub CI.
 * Pairing authorizes the candidate CLI; its foreground command owns one socket.
 * Browser title edits must reach disk promptly, with all twelve Tasks retained.
 * The same process fixture verifies restart updates and deletion replay.
 * Unit fixtures cannot satisfy these encrypted API/WebSocket/database assertions.
 */
export {};
const { spawn, execFileSync } = require('node:child_process');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { test, expect } = require('./helpers/cookie-audit');
const { createWorkflowCliHome, removeWorkflowCliHome, loginWorkflowCliViaPair, workflowCliEnv } = require('./helpers/workflow-cli-e2e-helpers');
const ROOT = resolve(__dirname, '../../../..');

function events(child) {
  const received = [];
  const pending = new Map();
  let buffer = '';
  let failure;
  child.stdout.on('data', data => {
    buffer += data.toString();
    while (buffer.includes('\n')) {
      const end = buffer.indexOf('\n'), line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
      try {
        const event = JSON.parse(line); received.push(event);
        if (event.event === 'failure') {
          failure = new Error(`Task sync fixture failed at ${event.stage}: ${event.error} (HTTP ${event.status ?? 'n/a'}, exit ${event.exit_code ?? 'n/a'})${event.check ? ': ' + event.check : ''}`);
          for (const wait of pending.values()) wait.reject(failure);
        } else pending.get(event.event)?.resolve(event);
      } catch { /* Only complete JSON protocol events are actionable. */ }
    }
  });
  child.once('error', error => { failure = error; for (const wait of pending.values()) wait.reject(error); });
  child.once('exit', code => {
    failure ??= new Error(`Task sync fixture exited (${code})`);
    for (const wait of pending.values()) wait.reject(failure);
  });
  return name => {
    const previous = received.find(event => event.event === name);
    if (previous) return Promise.resolve(previous);
    if (failure) return Promise.reject(failure);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(name); reject(new Error(`Task sync fixture timed out waiting for ${name}`)); }, 120_000);
      pending.set(name, { resolve: event => { clearTimeout(timer); pending.delete(name); resolve(event); }, reject: error => { clearTimeout(timer); pending.delete(name); reject(error); } });
    });
  };
}

test('web edits reach every cached Task and disconnected updates replay', async ({ page }, testInfo) => {
  test.setTimeout(300_000);
  expect(process.env.CI).toBe('true');
  expect(process.env.PLAYWRIGHT_TEST_BASE_URL).toBe('http://localhost:5173');
  // The runner already installs browser/FFmpeg dependencies. Add the small
  // graphical terminal needed by the repository's real PTY capture helper.
  execFileSync('sudo',['apt-get','install','-y','zutty','fonts-dejavu-core','x11-xserver-utils'],
    {cwd:ROOT,timeout:120_000,stdio:'pipe'});
  const home = createWorkflowCliHome('task-sync');
  let child;
  try {
    await loginWorkflowCliViaPair(page, 'http://localhost:8000', home, 'TASK_SYNC');
    child = spawn('node', ['--experimental-strip-types', '--loader', './frontend/packages/openmates-cli/tests/loader.mjs', 'scripts/project_task_sync_live.mjs'], {
      cwd: ROOT, env: {...workflowCliEnv('http://localhost:8000', home),
        OPENMATES_TASK_SYNC_CLI_PROOF:testInfo.outputPath('cli')}, stdio: ['pipe', 'pipe', 'pipe'],
    });
    // Error class/exit is reported by the protocol; no private CLI payload dump.
    child.stderr.resume();
    const event = events(child);
    const ready = await event('ready');
    await page.goto('/tasks', {waitUntil: 'domcontentloaded'});
    const card = page.locator(`[data-testid="task-card"][data-task-id="${ready.task_id}"]`);
    await expect(card).toBeVisible({timeout: 30_000});
    await card.getByTestId('task-card-open').click();
    const detail = page.getByTestId('task-detail-fullscreen');
    await detail.getByTestId('task-detail-title').click();
    await detail.getByTestId('workspace-detail-title-input').fill('Web edit reached the dev-device cache');
    const response = page.waitForResponse(response => response.request().method() === 'PATCH' && new URL(response.url()).pathname === `/v1/user-tasks/${ready.task_id}`);
    await detail.getByTestId('workspace-detail-title-save').click();
    expect((await response).status()).toBe(200);
    // A bounded correctness deadline, not a scalability benchmark or claimed latency SLA.
    await expect.poll(() => {
      const snapshot = JSON.parse(readFileSync(ready.snapshot, 'utf8'));
      return {count: snapshot.tasks.length, title: snapshot.tasks.find(task => task.task_id === ready.task_id)?.title};
    }, {timeout: 10_000}).toEqual({count: 12, title: 'Web edit reached the dev-device cache'});
    const verified = event('verified');
    child.stdin.write('verify-replay\n');
    expect((await verified).checks).toEqual(['twelve_tasks', 'single_owner', 'dependency_todo', 'lost_ack_reconciled', 'reconnect_update', 'reconnect_deletion', 'native_chat_task_plan_unlink', 'confirmed_codex_unlink']);
    await event('finished');
    const code = await new Promise(resolve => child.exitCode !== null ? resolve(child.exitCode) : child.once('exit', resolve));
    expect(code).toBe(0);
  } finally {
    if (child && child.exitCode === null) {
      const stopped = new Promise(resolve => child.once('exit', resolve));
      child.kill('SIGTERM');
      const timer = setTimeout(() => child.kill('SIGKILL'), 5_000);
      try { await stopped; } finally { clearTimeout(timer); }
    }
    removeWorkflowCliHome(home);
  }
});
