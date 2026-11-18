/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * A follow-up sent from the same tab while the previous reply still streams is
 * admitted immediately: it shows as Queued and frees the composer, instead of
 * waiting for the running reply to be stored. Disposable GitHub CI stack only.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { ensureIsolatedRecoveryEpoch } = require('./helpers/recovery-epoch');
const { getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const {
  loginToTestAccount, waitForChatReady, sendMessage, waitForAssistantMessage, deleteActiveChat
} = require('./helpers/chat-test-helpers');
const { waitForContextSyncComplete } = require('./helpers/chat-hydration');

const { email, password, otpKey } = getTestAccount();

test.describe('Queued follow-up from the sending tab', () => {
  test.setTimeout(300_000);
  test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
    || process.env.CI_TEST_MODE !== 'e2e' || !process.env.E2E_USE_MOCKS,
  'Requires isolated GitHub product stack and deterministic mock inference');
  skipWithoutCredentials(test, email, password, otpKey);
  // Dev and production run recovery epoch one; a fresh isolated stack starts at zero.
  test.beforeAll(() => ensureIsolatedRecoveryEpoch('chat-queued-followups-same-tab.spec.ts'));

  // contract-test: direct surface=gui.web assertions=chat-queued-followups.admission.synced
  test('a follow-up during a streaming reply shows Queued at once and is answered once', async ({ page }: { page: any }, testInfo: any) => {
    // Record socket frames so a failure names the stage that stalled:
    // admission sent, server queue acknowledgement, or the Queued row.
    const frames: Array<{ direction: string; type: string; payload: any }> = [];
    page.on('websocket', (socket: any) => {
      if (!new URL(socket.url()).pathname.endsWith('/v1/ws')) return;
      for (const [event, direction] of [['framesent', 'sent'], ['framereceived', 'received']]) {
        socket.on(event, (frame: any) => {
          try {
            const data = JSON.parse(String(frame.payload));
            frames.push({ direction, type: data.type, payload: data.payload });
          } catch { /* Ignore control frames. */ }
        });
      }
    });
    const sentTypes = () => frames.filter((f) => f.direction === 'sent').map((f) => f.type);
    // Send-preparation phases (chatSyncService.recordSendPreparationPhase) name the
    // client stage a stalled follow-up is waiting in.
    await page.addInitScript(() => {
      try { window.sessionStorage.setItem('openmates:send-prep-timing', '1'); } catch { /* storage unavailable */ }
    });
    const stageReport = async () => JSON.stringify({
      sent: sentTypes().slice(-30),
      received: frames.filter((f) => f.direction === 'received').map((f) => f.type).slice(-40),
      browser: await page.evaluate(() => {
        const w = window as any;
        return { phases: (w.__openmatesSendPrepPhases ?? []).slice(-40).map((p: any) => `${p.phase}@${Math.round(p.ms)}`),
          preflight: w.__openmatesLastPreflightDebug ?? null };
      }).catch((error: Error) => ({ unavailable: error.message })),
    });
    const withStage = async (check: () => Promise<unknown>) => {
      try { await check(); } catch (error) {
        throw new Error(`${(error as Error).message}\nstage report: ${await stageReport()}`);
      }
    };
    await loginToTestAccount(page);
    await waitForChatReady(page);
    await waitForContextSyncComplete(page, testInfo);
    try {
      // The fixture waits 15 s before its first chunk and then streams slowly,
      // so the follow-up is guaranteed to land while this reply is running.
      await sendMessage(page, withMockMarker('Start a long explanation of the library of Alexandria.', 'chat_interrupt_followup', 'instant'));
      const stop = page.getByTestId('stop-processing-button');
      await expect(stop).toBeVisible({ timeout: 60_000 });

      await sendMessage(page, withMockMarker('What is the capital of Germany?', 'chat_flow_capital', 'instant'),
        undefined, undefined, 'follow-up', { waitUntil: 'visible' });
      const followUp = page.getByTestId('message-user').last();
      await expect(followUp).toContainText('What is the capital of Germany?');
      const followUpId = await followUp.getAttribute('data-message-id');
      await withStage(() => expect.poll(() => frames.filter((f) => f.direction === 'sent'
        && ['chat_message_added', 'chat_turn_admit'].includes(f.type)
        && (f.payload?.message?.message_id ?? f.payload?.message_id) === followUpId).length, {
        timeout: 10_000, message: 'follow-up admission not sent',
      }).toBe(1));
      await withStage(() => expect.poll(() => frames.some((f) => f.direction === 'received'
        && ['message_queued', 'queued_message_status'].includes(f.type)
        && f.payload?.user_message_id === followUpId), {
        timeout: 15_000, message: 'no server queue acknowledgement',
      }).toBe(true));
      // Admission must not wait for the running reply to be stored.
      await withStage(() => expect(followUp.getByTestId('queued-followup-status')).toHaveText('Queued', { timeout: 10_000 }));
      await expect(followUp.getByTestId('queued-followup-edit')).toBeVisible();
      await expect(followUp.getByTestId('queued-followup-steer')).toBeVisible();
      await expect(stop).toBeVisible();
      // The composer is free while the reply runs: a new draft shows an idle Send.
      const editor = page.getByTestId('message-editor').getByRole('textbox');
      await editor.click();
      await page.keyboard.type('Draft while the reply runs');
      const send = page.getByTestId('composer-send-button').filter({ visible: true });
      await expect(send).toBeVisible({ timeout: 10_000 });
      await expect(send).not.toHaveAttribute('aria-busy', 'true');
      await page.keyboard.press('ControlOrMeta+A');
      await page.keyboard.press('Backspace');

      // Stop ends only the running reply; the queued follow-up is answered once.
      await stop.click();
      await waitForAssistantMessage(page, { contains: 'Berlin', timeout: 120_000 });
      await expect(page.getByTestId('message-user')).toHaveCount(2);
      await expect(page.getByTestId('queued-followup-status')).toHaveCount(0, { timeout: 60_000 });
      await expect(page.getByTestId('message-assistant').filter({ hasText: 'Berlin' })).toHaveCount(1);
    } finally {
      await deleteActiveChat(page).catch(() => undefined);
    }
  });
});
