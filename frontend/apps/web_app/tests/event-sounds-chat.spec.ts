/* eslint-disable @typescript-eslint/no-require-imports -- the shared chat helpers are CommonJS modules */
export {};
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount, startNewChat, sendMessage, waitForChatReady } = require('./helpers/chat-test-helpers');
const { getE2EDebugUrl, withMockMarker } = require('./signup-flow-helpers');

type CueRecord = { cue: string; outcome: string };

async function cues(page: any): Promise<CueRecord[]> {
  return page.evaluate(() => (window as Window & { __eventCues?: CueRecord[] }).__eventCues ?? []);
}

// contract-test: direct surface=gui.web assertions=notifications.sounds.important-events,notifications.sounds.quiet-window,notifications.sounds.first-cue-opt-out,notifications.sounds.silent-mode
test('a sent message plays one accepted sound, offers a one-click opt-out and stays silent afterwards', async ({ page }: { page: any }) => {
  test.setTimeout(240_000);
  expect(process.env.E2E_USE_MOCKS, 'This flow requires committed inference fixtures').toBeTruthy();
  await page.addInitScript(() => {
    const target = window as Window & { __eventCues?: CueRecord[] };
    target.__eventCues = [];
    window.addEventListener('openmates:event-cue', (event) => {
      target.__eventCues!.push((event as CustomEvent<CueRecord>).detail);
    });
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
  await loginToTestAccount(page, () => {}, async () => {}, { waitForEditor: true });
  await startNewChat(page);

  await sendMessage(page, withMockMarker('Capital of Germany?', 'chat_flow_capital', 'instant'));
  await expect.poll(async () => (await cues(page)).filter((entry) => entry.cue === 'accepted'), {
    message: 'the server admission of the sent message should play the accepted sound once',
    timeout: 60_000,
  }).toEqual([{ cue: 'accepted', outcome: 'played' }]);

  const notice = page.getByTestId('notification').filter({ hasText: 'Sounds are on' });
  await expect(notice).toBeVisible();
  await expect(notice.getByTestId('notification-action')).toHaveText('Turn off sounds');
  await test.info().attach('first-sound-notice', { body: await page.screenshot(), contentType: 'image/png' });

  await expect(page.getByTestId('message-assistant').last()).toContainText('Berlin', { timeout: 60_000 });
  await waitForChatReady(page);

  await notice.getByTestId('notification-action').click();
  await expect(notice).toBeHidden();
  expect(await page.evaluate(() => localStorage.getItem('openmates_silent_mode'))).toBe('true');

  await sendMessage(page, withMockMarker('Capital of Germany?', 'chat_flow_capital', 'instant'));
  await expect.poll(async () => (await cues(page)).filter((entry) => entry.cue === 'accepted').at(-1), {
    message: 'in silent mode the accepted sound is requested but not played',
    timeout: 60_000,
  }).toEqual({ cue: 'accepted', outcome: 'silent_mode' });
  expect((await cues(page)).filter((entry) => entry.outcome === 'played')).toHaveLength(1);
  await test.info().attach('after-turn-off', { body: await page.screenshot(), contentType: 'image/png' });
});
