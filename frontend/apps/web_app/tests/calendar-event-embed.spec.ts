/* eslint-disable @typescript-eslint/no-require-imports -- Shared E2E helpers expose CommonJS. */
export {};
import type { Page } from '@playwright/test';
const { test, expect } = require('./helpers/cookie-audit');
const { readFile, readdir } = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { createSignupLogger, getE2EDebugUrl } = require('./signup-flow-helpers');
const { startNewChat, sendMessage } = require('./helpers/chat-test-helpers');
const { CLI_DIST, deriveApiUrl } = require('./helpers/cli-test-helpers');
const { createWorkflowCliHome, removeWorkflowCliHome, loginWorkflowCliViaPair, runWorkflowCli, parseCliJson } = require('./helpers/workflow-cli-e2e-helpers');

async function eventDownload(page: Page, id: string): Promise<string> {
  const pending = page.waitForEvent('download');
  await page.getByTestId(id).click();
  const download = await pending;
  expect(download.suggestedFilename()).toMatch(/\.ics$/);
  return readFile(await download.path(), 'utf8');
}

function verifyEvent(file: string) {
  expect(file.split('\r\n').filter(line => line === 'BEGIN:VEVENT')).toHaveLength(1);
  expect(file).toContain('SUMMARY:FOSDEM 2027');
  expect(file).toContain('DTSTART;VALUE=DATE:20270130');
  expect(file).toContain('DTEND;VALUE=DATE:20270201');
  expect(file).not.toMatch(/Context only|ATTENDEE:|BEGIN:VALARM/);
}

// contract-test: direct surface=gui.web assertions=calendar-event.streaming.saved-lifecycle,calendar-event.preview.shared-week-layout,calendar-event.preview.context-highlight,calendar-event.fullscreen.details,calendar-event.export.primary-only,calendar-event.privacy.explicit-local-export
test('assistant calendar event survives reload and exports the same primary event through browser, CLI and SDK', async ({ page }: { page: Page }, info: import('@playwright/test').TestInfo) => {
  test.setTimeout(300_000);
  const log = createSignupLogger('CALENDAR_EVENT');
  const cliHome = createWorkflowCliHome('calendar-event');
  const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || 'http://localhost:5173');
  const cloudWrites: string[] = [];
  page.on('request', request => {
    if (/\/apps\/calendar\/(?:create-event|update-event|delete-event)|googleapis|graph\.microsoft|caldav/i.test(request.url())) cloudWrites.push(request.url());
  });
  try {
    await page.goto(getE2EDebugUrl('/'));
    await loginWorkflowCliViaPair(page, apiUrl, cliHome, 'CALENDAR_EVENT');
    await page.goto(getE2EDebugUrl('/'));
    await startNewChat(page, log);
    await sendMessage(page, 'When is FOSDEM 2027? <<<TEST_MOCK:calendar_event>>>', log);
    const card = page.getByTestId('message-assistant').last().getByTestId('embed-preview');
    await expect(card.getByTestId('calendar-event-preview')).toHaveAttribute('data-status', 'finished', { timeout: 60_000 });
    await expect(card.getByTestId('calendar-event-details')).toContainText('FOSDEM 2027');
    await expect(card.locator('[data-primary="true"]')).toHaveCount(2);
    await expect(card.locator('[data-context="true"]')).toHaveCount(1);
    const before = await eventDownload(page, 'calendar-event-add');
    verifyEvent(before);
    const chatUrl = page.url();
    const chatId = chatUrl.match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
    expect(chatId).toBeTruthy();
    const uid = before.match(/^UID:([^\r\n]+)/m)![1];

    await page.reload();
    await expect(card.getByTestId('calendar-event-add')).toBeEnabled({ timeout: 60_000 });
    const after = await eventDownload(page, 'calendar-event-add');
    verifyEvent(after);
    expect(after).toContain(`UID:${uid}\r\n`);
    await card.getByTestId('result-preview-more').click();
    await expect(page.getByRole('button', { name: 'View', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'View', exact: true }).click();
    await expect(page.getByTestId('calendar-event-fullscreen')).toBeVisible();
    await expect(page.getByTestId('calendar-event-description')).toContainText('open source developers');
    await expect(page.getByTestId('calendar-event-source')).toHaveAttribute('href', 'https://fosdem.org/2027/');
    const full = await eventDownload(page, 'calendar-event-fullscreen-add');
    verifyEvent(full);
    expect(full).toContain(`UID:${uid}\r\n`);
    await info.attach('saved-event-fullscreen', { body: await page.screenshot(), contentType: 'image/png' });
    await page.getByTestId('embed-fullscreen-overlay').getByRole('button', { name: 'Close', exact: true }).click();

    const result = await runWorkflowCli(apiUrl, cliHome, ['chats', 'download', chatId, '--output', path.join(cliHome, 'exports'), '--json'], 90_000,
      { OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'calendar-event-export' });
    const exported = parseCliJson(result, 'Calendar chat download');
    expect(exported.calendar_embeds).toBe(1);
    const calendarFiles = (await readdir(path.join(exported.output_dir, 'calendar'))).filter((name: string) => name.endsWith('.ics'));
    expect(calendarFiles).toHaveLength(1);
    const cliFile = await readFile(path.join(exported.output_dir, 'calendar', calendarFiles[0]), 'utf8');
    verifyEvent(cliFile);
    expect(cliFile).toContain(`UID:${uid}\r\n`);
    expect(result.recording).toBeTruthy();
    await info.attach('calendar-cli-export', { path: result.recording.videoPath, contentType: 'video/mp4' });
    await info.attach('calendar-cli-export-manifest', { path: result.recording.manifestPath, contentType: 'application/json' });

    const embedId = uid.replace(/@openmates$/, '');
    const saved = parseCliJson(await runWorkflowCli(apiUrl, cliHome, ['embeds', 'show', embedId, '--chat', chatId, '--json'], 60_000), 'Read saved event');
    const sdk = await import(pathToFileURL(path.join(path.dirname(CLI_DIST), 'index.js')).href);
    const sdkFile = sdk.buildCalendarEventFile(embedId, saved.content);
    verifyEvent(sdkFile);
    const eventProperties = (file: string) => file.split('\r\n').filter(line => !line.startsWith('DTSTAMP:'));
    expect(eventProperties(sdkFile)).toEqual(eventProperties(cliFile));
    expect(cloudWrites).toEqual([]);
    await page.goto(chatUrl);
    await expect(card.getByTestId('calendar-event-add')).toBeEnabled({ timeout: 30_000 });
  } finally { removeWorkflowCliHome(cliHome); }
});
