/* eslint-disable @typescript-eslint/no-require-imports */
// ci-profile: fresh_account
/** Actual first-party WS/Directus recovery with runner-only synthetic sealed jobs. */
export {};
const { test, expect } = require('@playwright/test');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const path = require('node:path');

// contract-test: direct surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent,chats.sync.key-gated-recovery
test('owner reconnect recovers encrypted metadata once and preserves a newer title edit', async () => {
  test.setTimeout(180000);
  const root = path.resolve(__dirname, '../../../..');
  const result = await promisify(execFile)(process.execPath,
    ['--experimental-strip-types', path.join(root, 'scripts/ci_chat_metadata_recovery.mjs'), root],
    { cwd: root, env: process.env, timeout: 150000, maxBuffer: 128 * 1024 });
  expect(JSON.parse(result.stdout)).toEqual({ discovery_after_disconnect: true, encrypted_commit: true,
    repeated_replay_idempotent: true, owner_edit_preserved: true, sealed_payload_removed: true,
    older_client_capability_guard: true, inference_calls: 0 });
});

const { spawn } = require('node:child_process');
const { createInterface } = require('node:readline');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { openChatAfterContextSync } = require('./helpers/chat-hydration');
const { scrollChatHistoryToStart } = require('./helpers/chat-scroll');

/** The loaded chat scrolls to its latest message; expose its header as a user does. */
async function showHeaderForProof(page: any, testInfo: any): Promise<void> {
  await expect(page.getByTestId('chat-history-container')).toHaveAttribute('data-scroll-state', 'ready');
  const scrollToTop = page.getByRole('button', { name: 'Scroll to top', exact: true });
  if (await scrollToTop.isVisible()) await scrollToTop.click();
  await scrollChatHistoryToStart(page, testInfo);
  // DOM visibility alone also passes when the header is clipped above the chat
  // scroller. Both texts must be entirely in view in the recording/checkpoint.
  await expect(page.getByTestId('chat-header-title')).toBeInViewport({ ratio: 1 });
  await expect(page.getByTestId('chat-header-summary')).toBeInViewport({ ratio: 1 });
}

/** A runner-private child owns real backend fixture rows and cleans them on stdin EOF. */
function startUiFixture(root: string) {
  const child = spawn(process.execPath,
    ['--experimental-strip-types', path.join(root, 'scripts/ci_chat_metadata_recovery.mjs'), root, '--ui-fixture'],
    { cwd: root, env: process.env, stdio: ['pipe', 'pipe', 'pipe'] });
  const lines = createInterface({ input: child.stdout });
  const buffered = new Map<string, any>();
  const waiters = new Map<string, { resolve: (frame: any) => void; reject: (error: Error) => void }>();
  let exited = false;
  let stderr = '';
  child.stderr.on('data', (bytes: Buffer) => { stderr = (stderr + bytes.toString()).slice(-6000); });
  lines.on('line', (line: string) => {
    let frame;
    try { frame = JSON.parse(line); } catch { return; }
    if (typeof frame?.event !== 'string') return;
    const waiter = waiters.get(frame.event);
    if (waiter) { waiters.delete(frame.event); waiter.resolve(frame); }
    else buffered.set(frame.event, frame);
  });
  const exit = new Promise<void>((resolve, reject) => {
    child.once('error', reject);
    child.once('exit', (code: number | null) => {
      exited = true;
      const error = new Error(`Metadata fixture exited (${code}): ${stderr}`);
      for (const waiter of waiters.values()) waiter.reject(error);
      waiters.clear();
      if (code === 0) resolve(); else reject(error);
    });
  });
  void exit.catch(() => {});
  const wait = (event: string) => {
    if (buffered.has(event)) { const frame = buffered.get(event); buffered.delete(event); return Promise.resolve(frame); }
    if (exited) return Promise.reject(new Error('Metadata fixture already exited'));
    return new Promise<any>((resolve, reject) => {
      const timer = setTimeout(() => { waiters.delete(event); reject(new Error(`Metadata fixture timed out: ${event}`)); }, 45000);
      waiters.set(event, { resolve: frame => { clearTimeout(timer); resolve(frame); },
        reject: error => { clearTimeout(timer); reject(error); } });
    });
  };
  const command = (name: string) => { const response = wait(name); child.stdin.write(`${name}\n`); return response; };
  return { ready: () => wait('ready'), command, async stop() {
    if (!exited) { child.stdin.end(); await exit; }
    lines.close();
  } };
}

// contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery,chats.completion.independent-metadata
test('browser renders recovered initial title and summary before any assistant completion, then refines both after reconnect',
  async ({ page }: { page: any }, testInfo: any) => {
    test.setTimeout(180000);
    const root = path.resolve(__dirname, '../../../..');
    const fixture = startUiFixture(root);
    const frames: Array<{ type: string; jobId?: string; state?: string }> = [];
    // Observe actual frames only. The test never dispatches synthetic browser
    // events, supplies cleartext metadata to stores, or intercepts the adapter.
    page.on('websocket', (socket: any) => {
      socket.on('framereceived', ({ payload }: { payload: string | Buffer }) => {
        try {
          const frame = JSON.parse(String(payload));
          if (frame.type === 'metadata_jobs_available') for (const job of frame.payload?.jobs ?? [])
            frames.push({ type: frame.type, jobId: job.job_id });
          if (frame.type === 'metadata_job_persisted') frames.push({ type: frame.type,
            jobId: frame.payload?.job_id, state: frame.payload?.state });
        } catch { /* Other transport frames are irrelevant to this assertion. */ }
      });
    });
    try {
      const initial = await fixture.ready();
      await loginToTestAccount(page);
      await openChatAfterContextSync(page, initial.chatId, testInfo);
      const sidebar = page.getByTestId('activity-history-wrapper');
      if (await sidebar.isVisible()) await sidebar.getByRole('button', { name: /close/i }).click();
      await expect(sidebar).not.toBeVisible();
      await expect(page.getByTestId('message-user')).toContainText('Synthetic user question');
      await expect(page.getByTestId('message-assistant')).toHaveCount(0);
      await expect(page.getByTestId('chat-header-title')).toHaveText('Early research outline', { timeout: 30000 });
      await expect(page.getByTestId('chat-header-summary')).toBeVisible({ timeout: 30000 });
      await expect(page.getByTestId('chat-header-summary')).toContainText(
        'A first outline is ready while the answer is still being prepared.', { timeout: 30000 });
      expect(frames.some(frame => frame.type === 'metadata_jobs_available' && frame.jobId === initial.jobId)).toBe(true);
      await expect.poll(() => frames.some(frame => frame.type === 'metadata_job_persisted'
        && frame.jobId === initial.jobId && frame.state === 'TERMINAL'), { timeout: 30000 }).toBe(true);
      const earlyReceipt = await fixture.command('inspect');
      expect(earlyReceipt).toMatchObject({ title: 'Early research outline',
        summary: 'A first outline is ready while the answer is still being prepared.',
        initialState: 'TERMINAL', sealedInitialRemoved: true, assistantCompleted: false, inferenceCalls: 0 });
      await showHeaderForProof(page, testInfo);
      await testInfo.attach('initial-header-before-assistant', { body: await page.screenshot(), contentType: 'image/png' });

      const final = await fixture.command('final');
      // Reconnect exercises real durable discovery, including jobs created while
      // the browser's previous transport had no notification to consume.
      await page.reload({ waitUntil: 'domcontentloaded' });
      await openChatAfterContextSync(page, final.chatId, testInfo);
      await expect(page.getByTestId('chat-header-title')).toHaveText('Completed research findings', { timeout: 30000 });
      await expect(page.getByTestId('chat-header-summary')).toBeVisible({ timeout: 30000 });
      await expect(page.getByTestId('chat-header-summary')).toContainText(
        'The completed answer refines the outline with verified findings.', { timeout: 30000 });
      await expect(page.getByTestId('message-assistant')).toContainText('Synthetic completed assistant answer');
      await expect.poll(() => frames.some(frame => frame.type === 'metadata_job_persisted'
        && frame.jobId === final.jobId && frame.state === 'TERMINAL'), { timeout: 30000 }).toBe(true);
      expect(await fixture.command('inspect')).toMatchObject({ title: 'Completed research findings',
        summary: 'The completed answer refines the outline with verified findings.',
        finalState: 'TERMINAL', sealedFinalRemoved: true, assistantCompleted: true, inferenceCalls: 0 });
      await showHeaderForProof(page, testInfo);
      await testInfo.attach('refined-header-after-reconnect', { body: await page.screenshot(), contentType: 'image/png' });
    } finally {
      await fixture.stop();
    }
  });
