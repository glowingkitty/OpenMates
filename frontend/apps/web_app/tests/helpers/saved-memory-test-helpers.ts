/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Helpers for verifying saved result embeds from E2E specs.
 * Saving sets an encrypted flag on the embed itself; no memory entry exists,
 * so these helpers only drive and assert the Save / Saved CTA.
 */
export {};

const { expect } = require('@playwright/test');

const SAVED_SYNC_TIMEOUT_MS = 45_000;

// contract-test: supporting surface=gui.web assertions=app-memories.saved-items.not-memories
async function saveCurrentFullscreenEmbed(
  page: any,
  logCheckpoint: (message: string) => void,
  options: { expectReminder?: boolean } = {},
): Promise<string> {
  const headerTitle = page.getByTestId('embed-header-title').last();
  await expect(headerTitle).toBeVisible({ timeout: 10000 });
  const savedTitle = (await headerTitle.textContent())?.trim() || '';
  expect(savedTitle).toBeTruthy();

  const saveButton = page.getByTestId('save-embed-cta').last();
  await expect(saveButton).toBeVisible({ timeout: 10000 });
  // The icon-only CTA keeps its visible state in the accessible name.
  if ((await saveButton.getAttribute('aria-pressed')) === 'true') {
    await saveButton.click();
    await expect(saveButton).toHaveAccessibleName('Save', { timeout: 10000 });
  }
  await expect(saveButton).toHaveAccessibleName('Save');

  // Items with an actual date and time still schedule reminders when saved.
  const reminderResponse = options.expectReminder
    ? page.waitForResponse(
      (resp: any) => resp.url().includes('/v1/apps/reminder/skills/set-reminder') && resp.request().method() === 'POST',
      { timeout: SAVED_SYNC_TIMEOUT_MS },
    )
    : null;
  const changed = page.evaluate(() => new Promise((resolve) => {
    window.addEventListener('savedEmbedChanged', (event) => resolve((event as CustomEvent).detail), { once: true });
  }));
  await saveButton.click();
  await expect(saveButton).toHaveAccessibleName('Saved', { timeout: SAVED_SYNC_TIMEOUT_MS });
  await expect(page.getByText(/to memor/i)).toHaveCount(0);
  const detail = await Promise.race([changed, page.waitForTimeout(SAVED_SYNC_TIMEOUT_MS).then(() => null)]);
  expect(detail, 'savedEmbedChanged event').toMatchObject({ saved: true });
  if (reminderResponse) {
    const response = await reminderResponse;
    const request = response.request().postDataJSON();
    expect(request.target_type).toBe('embed');
    expect(request.notification_context).toMatchObject({ version: 1, app_id: request.target_embed_app_id });
    expect(request.notification_context).not.toHaveProperty('content');
    expect(request.notification_context).not.toHaveProperty('messages');
    expect(response.ok()).toBe(true);
    logCheckpoint(`Reminder scheduled for "${savedTitle}".`);
  }
  logCheckpoint(`Saved "${savedTitle}".`);
  return savedTitle;
}

// contract-test: supporting surface=gui.web assertions=app-memories.saved-items.not-memories
async function expectEmbedStillSaved(page: any, logCheckpoint: (message: string) => void): Promise<void> {
  const saveButton = page.getByTestId('save-embed-cta').last();
  await expect(saveButton).toBeVisible({ timeout: 10000 });
  await expect(saveButton).toHaveAccessibleName('Saved', { timeout: 10000 });
  logCheckpoint('Embed still shows Saved after reopening.');
}

module.exports = {
  saveCurrentFullscreenEmbed,
  expectEmbedStillSaved,
};
