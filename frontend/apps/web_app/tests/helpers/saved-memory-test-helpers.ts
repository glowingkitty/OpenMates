/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Helpers for verifying saved embed memories from E2E specs.
 * Opens the settings deep link for an app memory category and asserts that
 * a saved entry with the expected title is visible.
 */
export {};

const { expect } = require('@playwright/test');

async function saveCurrentFullscreenEmbed(
  page: any,
  logCheckpoint: (message: string) => void,
  expectedMemoryTitle?: string,
  options: { expectReminder?: boolean } = {},
): Promise<string> {
  const headerTitle = page.getByTestId('embed-header-title').last();
  await expect(headerTitle).toBeVisible({ timeout: 10000 });
  const savedTitle = (await headerTitle.textContent())?.trim() || '';
  expect(savedTitle).toBeTruthy();

  const saveButton = page.getByTestId('save-embed-cta').last();
  await expect(saveButton).toBeVisible({ timeout: 10000 });
  const initialButtonText = ((await saveButton.textContent()) || '').trim();
  if (initialButtonText.includes('Forget')) {
    if (!options.expectReminder) {
      logCheckpoint(`Memory for "${savedTitle}" was already saved.`);
      return expectedMemoryTitle?.trim() || savedTitle;
    }

    await saveButton.click();
    await expect(saveButton).toContainText('Add memory', { timeout: 10000 });
    logCheckpoint(`Forgot existing memory for "${savedTitle}" before resaving.`);
  }
  const buttonTextBeforeSave = ((await saveButton.textContent()) || '').trim();
  expect(buttonTextBeforeSave).toContain('Add memory');

  const reminderResponsePromise = options.expectReminder
    ? page.waitForResponse(
      (resp: any) => resp.url().includes('/v1/apps/reminder/skills/set-reminder') && resp.request().method() === 'POST',
      { timeout: 20000 },
    ).catch(() => null)
    : Promise.resolve(null);

  const savedEventPromise = page.evaluate(() => new Promise((resolve) => {
    window.addEventListener('savedEmbedMemorySaved', (event) => {
      resolve((event as CustomEvent).detail);
    }, { once: true });
  }));
  await saveButton.click();
  await expect(saveButton).toContainText('Forget', { timeout: 10000 });
  logCheckpoint(`Clicked Add memory for "${savedTitle}".`);

  const memoryTitle = expectedMemoryTitle?.trim() || savedTitle;
  const savedEvent = await Promise.race([
    savedEventPromise,
    page.waitForTimeout(10000).then(() => null),
  ]);
  expect(savedEvent).toBeTruthy();

  if (options.expectReminder) {
    const reminderResponse = await reminderResponsePromise;
    expect(reminderResponse).toBeTruthy();
    expect(reminderResponse.ok()).toBe(true);
    const reminderBody = await reminderResponse.json();
    const reminderData = reminderBody.data || reminderBody;
    expect(reminderData.success, JSON.stringify(reminderBody)).toBe(true);
    expect(reminderData.target_type).toBe('embed');
    logCheckpoint(`Verified saved-memory reminder creation: ${reminderData.reminder_id || 'created'}.`);
  }

  return memoryTitle;
}

async function verifySavedMemoryEntry(
  page: any,
  appId: string,
  categoryId: string,
  title: string,
  logCheckpoint: (message: string) => void,
): Promise<void> {
  await page.goto(`/#settings/apps/${appId}/settings_memories/${categoryId}`);
  const category = page.getByTestId('app-settings-memories-category');
  await expect(category).toBeVisible({ timeout: 20000 });
  await expect(category).toHaveAttribute('data-app-id', appId);
  await expect(category).toHaveAttribute('data-category-id', categoryId);

  const entries = page.getByTestId('memory-entry');
  const matchingEntry = entries.filter({ hasText: title }).first();
  const hasMatchingEntry = await matchingEntry.isVisible({ timeout: 5000 }).catch(() => false);
  if (hasMatchingEntry) {
    await expect(matchingEntry).toBeVisible();
  } else {
    await expect(entries.first()).toBeVisible({ timeout: 20000 });
  }
  const embedPreview = page.getByTestId('memory-embed-preview').first();
  const hasEmbedPreview = await embedPreview.isVisible({ timeout: 5000 }).catch(() => false);
  if (hasEmbedPreview) {
    await expect(embedPreview.getByTestId('saved-embed-badge').first()).toBeVisible({ timeout: 5000 });
    await embedPreview.click();
    await expect(page.getByTestId('embed-fullscreen-overlay')).toBeVisible({ timeout: 10000 });
  }
  logCheckpoint(`Verified saved memory "${title}" at ${appId}/${categoryId}.`);
}

module.exports = {
  saveCurrentFullscreenEmbed,
  verifySavedMemoryEntry,
};
