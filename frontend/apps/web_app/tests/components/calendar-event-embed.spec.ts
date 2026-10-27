import { readFile } from 'node:fs/promises';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Page } from '@playwright/test';

// playwright-account: not_required reason=isolated_component_preview
test.setTimeout(120_000);

async function open(page: Page, variant = '', theme = 'light', width = 1000) {
  const params = new URLSearchParams({ chrome: '0', theme, width: String(width), background: theme === 'dark' ? '#171717' : '#dbeafe' });
  if (variant) params.set('variant', variant);
  await page.goto(`/dev/preview/embeds/calendar/CalendarEventEmbedHarness?${params}`);
  await waitForComponentPreview(page);
  return page.getByTestId('embed-preview');
}

async function download(page: Page, testId: string) {
  const pending = page.waitForEvent('download');
  await page.getByTestId(testId).click();
  const result = await pending;
  expect(result.suggestedFilename()).toMatch(/\.ics$/);
  const file = await result.path();
  expect(file).toBeTruthy();
  return readFile(file!, 'utf8');
}

// contract-test: supporting surface=gui.web assertions=calendar-event.streaming.saved-lifecycle,calendar-event.preview.shared-week-layout,calendar-event.export.primary-only
test('a parsed assistant reference keeps the calendar content type instead of the event-search card', async ({ page }, info) => {
  await page.goto('/dev/preview/ReadOnlyMessage?chrome=0&theme=light&width=700&variant=calendarEventReply');
  await waitForComponentPreview(page);
  const card = page.getByTestId('embed-preview');
  await expect(card.getByTestId('calendar-event-preview')).toHaveAttribute('data-status', 'finished');
  await expect(card.getByTestId('calendar-event-details')).toContainText('FOSDEM 2027');
  await expect(card.locator('[data-primary="true"]')).toHaveCount(2);
  await expect(card.locator('[data-context="true"]')).toHaveCount(1);
  for (const day of await card.getByTestId('embeds-results-view-calendar-day').all()) {
    const column = (await day.boundingBox())!;
    for (const event of await day.getByTestId('embeds-results-view-calendar-date-only').all()) {
      const block = (await event.boundingBox())!;
      expect(block.x).toBeGreaterThanOrEqual(column.x);
      expect(block.x + block.width).toBeLessThanOrEqual(column.x + column.width + 1);
    }
  }
  const file = await download(page, 'calendar-event-add');
  expect(file).toContain('UID:904f0053-d60a-435d-a122-f1b7f6311bca@openmates');
  expect(file).not.toContain('Planning day');
  await info.attach('assistant-calendar-reference', { body: await card.screenshot(), contentType: 'image/png' });
});

for (const theme of ['light', 'dark']) {
  // contract-test: supporting surface=gui.web assertions=calendar-event.preview.shared-week-layout,calendar-event.preview.context-highlight,calendar-event.export.primary-only,calendar-event.privacy.explicit-local-export
  test(`calendar preview shares controls and highlights primary event in ${theme}`, async ({ page }, info) => {
    await page.setViewportSize({ width: 1120, height: 900 });
    const requests: string[] = [];
    page.on('request', request => { if (/googleapis|graph\.microsoft|caldav/i.test(request.url())) requests.push(request.url()); });
    for (const variant of ['overlap', 'largeOverlap']) {
      const card = await open(page, variant, theme);
      await expect(card).toBeVisible();
      const frame = (await card.boundingBox())!;
      expect(frame.width).toBeCloseTo(variant === 'overlap' ? 300 : 1000, 0);
      expect(frame.height).toBeCloseTo(variant === 'overlap' ? 200 : 400, 0);
      const details = (await card.getByTestId('calendar-event-details').boundingBox())!;
      const week = (await card.getByTestId('calendar-event-week').boundingBox())!;
      expect(week.width / details.width).toBeCloseTo(2, 1);
      expect(week.x).toBeGreaterThan(details.x + details.width);
      expect(week.x + week.width).toBeLessThanOrEqual(frame.x + frame.width);
      const date = (await card.getByTestId('calendar-event-date').boundingBox())!;
      expect(date.y + date.height).toBeLessThanOrEqual(details.y + details.height + 1);
      await expect(card.getByTestId('embeds-results-view-calendar-day')).toHaveCount(7);
      const primary = card.locator('[data-testid="embeds-results-view-calendar-item"]:not(.contextual)');
      const context = card.locator('[data-testid="embeds-results-view-calendar-item"].contextual');
      await expect(primary).toHaveCount(1);
      await expect(context).toHaveCount(1);
      await expect(primary).toHaveCSS('opacity', '1');
      await expect(context).toHaveCSS('opacity', '0.48');
      const primaryBox = (await primary.boundingBox())!;
      const contextBox = (await context.boundingBox())!;
      expect(primaryBox.x + primaryBox.width).toBeLessThanOrEqual(contextBox.x + 1);
      await card.hover();
      const tools = card.getByTestId('preview-tools');
      await expect(tools).toBeVisible();
      await expect(tools.getByTestId('result-preview-expand')).toBeVisible();
      await expect(tools.getByTestId('calendar-event-add')).toBeEnabled();
      await expect(tools.getByRole('button')).toHaveCount(3);
      for (const button of await tools.getByRole('button').all()) {
        expect(await button.locator('.clickable-icon').evaluate(element => getComputedStyle(element).maskImage)).not.toBe('none');
      }
      await tools.getByTestId('calendar-event-add').focus();
      const first = await download(page, 'calendar-event-add');
      expect(first.match(/BEGIN:VEVENT/g)).toHaveLength(1);
      expect(first).toContain('SUMMARY:Open Source Workshop');
      expect(first).toContain('DTSTART:20270315T090000Z');
      expect(first).not.toContain('Team meeting');
      expect(first).not.toMatch(/ATTENDEE|VALARM/);
      const second = await download(page, 'calendar-event-add');
      expect(first.match(/^UID:.*$/m)?.[0]).toBe(second.match(/^UID:.*$/m)?.[0]);
      await info.attach(`${variant}-${theme}`, { body: await card.screenshot(), contentType: 'image/png' });
    }
    expect(requests).toEqual([]);
  });
}

// contract-test: supporting surface=gui.web assertions=calendar-event.fullscreen.details,calendar-event.export.primary-only,calendar-event.preview.shared-week-layout
test('calendar event expands with description and exports the inclusive two-day event', async ({ page }, info) => {
  await page.setViewportSize({ width: 1120, height: 900 });
  const card = await open(page);
  await expect(card.getByTestId('calendar-event-date')).toContainText('Jan 30');
  await card.hover();
  await card.getByTestId('result-preview-expand').focus();
  await card.getByTestId('result-preview-expand').press('Enter');
  const fullscreen = page.getByTestId('calendar-event-fullscreen');
  await expect(fullscreen).toBeVisible();
  const shell = page.getByTestId('embed-fullscreen-overlay');
  expect((await shell.boundingBox())!.height).toBeGreaterThan(800);
  await expect(fullscreen.getByTestId('calendar-event-description')).toContainText('open source developers');
  await expect(fullscreen.getByTestId('calendar-event-description')).toBeInViewport();
  await expect(fullscreen.getByTestId('calendar-event-source')).toHaveAttribute('href', 'https://fosdem.org/2027/');
  const ics = await download(page, 'calendar-event-fullscreen-add');
  expect(ics).toContain('DTSTART;VALUE=DATE:20270130');
  expect(ics).toContain('DTEND;VALUE=DATE:20270201');
  expect(ics.match(/BEGIN:VEVENT/g)).toHaveLength(1);
  await info.attach('fullscreen-details', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=calendar-event.preview.shared-week-layout,calendar-event.fullscreen.details,calendar-event.content.validated
test('phone preview, minimal fields and unfinished states remain usable', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const mobile = await open(page, 'mobile', 'light', 358);
  await expect(mobile.getByTestId('calendar-event-details')).toBeVisible();
  await expect(mobile.getByTestId('calendar-event-week')).toBeVisible();
  const calendarBounds = (await mobile.getByTestId('calendar-event-week').boundingBox())!;
  for (const header of await mobile.locator('.calendar-day-header').all()) {
    const bounds = (await header.boundingBox())!;
    expect(bounds.x).toBeGreaterThanOrEqual(calendarBounds.x);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(calendarBounds.x + calendarBounds.width + 1);
  }
  await expect(mobile.getByTestId('calendar-event-add')).toBeEnabled();
  expect((await mobile.boundingBox())!.width).toBeCloseTo(300, 0);
  expect((await mobile.getByTestId('preview-tools').boundingBox())!.x).toBeGreaterThan((await mobile.boundingBox())!.x + 44);
  expect((await mobile.boundingBox())!.width).toBeLessThanOrEqual(358);
  await info.attach('phone-calendar-event', { body: await page.screenshot(), contentType: 'image/png' });
  const minimal = await open(page, 'minimal', 'light', 358);
  await minimal.hover();
  await minimal.getByTestId('result-preview-expand').click();
  await expect(page.getByTestId('calendar-event-fullscreen')).toBeVisible();
  expect((await page.getByTestId('calendar-event-fullscreen').boundingBox())!.width).toBeGreaterThan(250);
  expect((await page.getByTestId('embed-fullscreen-overlay').boundingBox())!.height).toBeGreaterThan(800);
  await expect(page.getByTestId('calendar-event-description')).toHaveCount(0);
  await expect(page.getByTestId('calendar-event-source')).toHaveCount(0);
  for (const variant of ['invalid', 'processing', 'cancelled']) {
    const card = await open(page, variant, 'light', 358);
    await expect(card.getByTestId('calendar-event-add')).toBeDisabled();
    await expect(card.getByTestId('calendar-event-unavailable')).toBeVisible();
    await expect(card.getByTestId('embeds-results-view-calendar-item')).toHaveCount(0);
  }
});
