/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * A client that resends a user message whose turn is already answered (a stale
 * outbox replay after reconnect or restart) gets a quiet confirmation: no error
 * frame or notification, no second inference, no second answer, and one server
 * WARNING line per resend so the stale-resend cause stays visible in the logs.
 * Covers the exact admission replay and a protocol-less legacy resend.
 */
export {};
const { test, expect } = require('./helpers/cookie-audit');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const { createSignupLogger, createStepScreenshotter, archiveExistingScreenshots,
  getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage } = require('./helpers/chat-test-helpers');
const { ensureIsolatedRecoveryEpoch } = require('./helpers/recovery-epoch');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const root = path.resolve(__dirname, '../../../..');
const compose = path.join(root, 'test-results/ci-private/compose.json');
const RESEND_LOG = 'Resend of a finished turn acknowledged without processing';
const ADMISSION_TYPES = ['chat_turn_admit', 'chat_turn_preflight', 'chat_message_added'];
// Frames that would mean the server started (or billed) the turn again.
const PROCESSING_TYPES = ['ai_task_initiated', 'ai_message_chunk', 'recovery_jobs_available'];

/** The api logger redacts chat and message ids, so count the fixed text. A
 * Playwright retry shares the stack, so callers compare against a baseline. */
function resendLogLines(): string[] {
  const logs = execFileSync('docker', ['compose', '-f', compose, 'logs', '--no-color', 'api'], {
    cwd: root, encoding: 'utf8', timeout: 60_000, maxBuffer: 64 * 1024 * 1024,
  });
  return logs.split('\n').filter((line: string) => line.includes(RESEND_LOG) && line.includes('turn_state='));
}

const L = ['web-laptop'];
const RESEND_PROOF = defineVideoProof({
  id: 'chat-finished-turn-resend',
  title: 'A resent answered message is confirmed quietly',
  surface: 'web',
  devices: L,
  domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'answered', text: 'The chat shows the question and its single answer.', checkpoint: 'answered-before-resend', devices: L },
    { id: 'resent', text: 'The same message is resent twice; the chat shows no error and no second answer.', checkpoint: 'quiet-after-resends', devices: L },
    { id: 'reloaded', text: 'After a reload the chat still has one question and one answer.', checkpoint: 'single-answer-after-reload', devices: L },
  ],
  assertions: [
    { id: 'resend.no_error', checkpoint: 'quiet-after-resends', visual: 'No error notification is visible and the chat has one answer.', devices: L },
    { id: 'resend.single_answer', checkpoint: 'single-answer-after-reload', visual: 'The reloaded chat shows exactly one user message and one answer.', devices: L },
  ],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

test.beforeAll(() => ensureIsolatedRecoveryEpoch('chat-finished-turn-resend.spec.ts'));

// contract-test: direct surface=gui.web assertions=chats.message.identity-idempotent
test('a resend of an already answered message is confirmed quietly and never answered or charged again', async ({ page }: { page: any }, testInfo: any) => {
  test.setTimeout(240000);
  test.skip(!TEST_EMAIL || !TEST_PASSWORD || !TEST_OTP_KEY, 'Test account credentials are required.');
  const events: Array<Record<string, any>> = [];
  let original: { type: string; raw: string; payload: Record<string, any> } | null = null;
  let server: any = null;
  await page.routeWebSocket(/\/v1\/ws(?:\?|$)/, (socket: any) => {
    const upstream = socket.connectToServer();
    server = upstream;
    const capture = (direction: string, raw: unknown) => {
      try {
        const frame = JSON.parse(String(raw)), body = frame.payload ?? {};
        events.push({ direction, type: frame.type, chatId: body.chat_id, state: body.state, code: body.code,
          messageId: body.message_id, userMessageId: body.user_message_id,
          alreadyCompleted: body.turn_already_completed, assistantId: body.assistant_message_id });
        if (direction === 'sent' && !original && ADMISSION_TYPES.includes(frame.type)
          && typeof body.message_id === 'string') {
          original = { type: frame.type, raw: String(raw), payload: body };
        }
      } catch { /* Ignore non-JSON control frames. */ }
    };
    socket.onMessage((raw: unknown) => { capture('sent', raw); upstream.send(raw); });
    upstream.onMessage((raw: unknown) => { capture('received', raw); socket.send(raw); });
  });
  const logCheckpoint = createSignupLogger('FINISHED_TURN_RESEND');
  const takeStepScreenshot = createStepScreenshotter(logCheckpoint);
  const proof = createVideoProofRuntime(RESEND_PROOF, {
    device: 'web-laptop', attach: testInfo.attach.bind(testInfo),
    captureFrame: () => page.screenshot({ type: 'png' }),
  });
  try {
    await archiveExistingScreenshots(logCheckpoint);
    await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
    await startNewChat(page, logCheckpoint);
    await sendMessage(page, withMockMarker('What is the capital?', 'chat_flow_capital'), logCheckpoint);
    await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
    const chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)![1];
    await expect(page.getByTestId('message-assistant')).toHaveCount(1, { timeout: 90000 });
    await expect.poll(() => events.some(event => event.direction === 'received'
      && event.type === 'recovery_job_persisted' && event.state === 'TERMINAL'), { timeout: 90000 }).toBe(true);
    expect(original, 'The first send must have been captured').toBeTruthy();
    const sent = original!;
    const messageId = sent.payload.message_id as string;
    const assistantId = await page.getByTestId('message-assistant').first().getAttribute('data-message-id');
    const order = async () => page.locator('[data-testid="message-user"], [data-testid="message-assistant"]')
      .evaluateAll((nodes: Element[]) => nodes.map(node => node.getAttribute('data-message-id')));
    const answeredOrder = await order();
    await proof.checkpoint('answered-before-resend');

    const legacyPayload = { ...(sent.payload.inference_request ?? sent.payload) };
    delete legacyPayload.protocol_version;
    delete legacyPayload.preflight_id;
    const baseline = resendLogLines().length;
    const resends = [
      { name: 'exact admission replay', raw: sent.raw },
      { name: 'protocol-less legacy resend', raw: JSON.stringify({ type: 'chat_message_added', payload: legacyPayload }) },
    ];
    for (const [index, resend] of resends.entries()) {
      const start = events.length;
      logCheckpoint(`Resending the answered message: ${resend.name}`);
      server.send(resend.raw);
      await expect.poll(() => events.slice(start).some(event => event.direction === 'received'
        && event.type === 'chat_message_confirmed' && event.messageId === messageId && event.alreadyCompleted === true),
        { timeout: 30000, message: `${resend.name}: quiet confirmation` }).toBe(true);
      // Leave the server time to (wrongly) start a turn before judging silence.
      await page.waitForTimeout(8000);
      const after = events.slice(start).filter(event => event.direction === 'received');
      expect(after.filter(event => event.type === 'error'), `${resend.name}: no error frame`).toEqual([]);
      expect(after.filter(event => PROCESSING_TYPES.includes(event.type)
        || (event.type === 'ai_message_update' && event.userMessageId === messageId)),
        `${resend.name}: no second inference`).toEqual([]);
      expect(resendLogLines().slice(baseline), `${resend.name}: one WARNING line per resend`).toHaveLength(index + 1);
      await expect(page.getByTestId('message-assistant')).toHaveCount(1);
      await expect(page.getByTestId('notification')).toHaveCount(0);
    }
    const lines = resendLogLines().slice(baseline);
    expect(lines.every((line: string) => line.includes('WARNING'))).toBe(true);
    // The protocol-less resend (the stale Apple history reply) is labelled by its path.
    expect(lines[1]).toContain('path=missing_preflight');
    await proof.assert('resend.no_error', async () => {
      await expect(page.getByTestId('notification')).toHaveCount(0);
      await expect(page.getByTestId('message-assistant')).toHaveCount(1);
    });
    await proof.checkpoint('quiet-after-resends');

    await page.reload({ waitUntil: 'domcontentloaded' });
    await proof.assert('resend.single_answer', async () => {
      await expect(page.getByTestId('message-assistant')).toHaveCount(1, { timeout: 30000 });
      await expect(page.getByTestId('message-user')).toHaveCount(1);
    });
    expect(await order()).toEqual(answeredOrder);
    expect(answeredOrder).toContain(assistantId);
    // The original send starts at most one inference for this chat; the resends start none.
    expect(events.filter(event => event.direction === 'received' && event.type === 'ai_task_initiated'
      && event.chatId === chatId).length).toBeLessThanOrEqual(1);
    await proof.checkpoint('single-answer-after-reload');
    await proof.attach();
  } finally {
    await testInfo.attach('finished-turn-resend-protocol', { body: JSON.stringify(events.slice(-200)), contentType: 'application/json' });
  }
});
