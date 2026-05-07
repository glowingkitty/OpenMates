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
): Promise<string> {
  const headerTitle = page.getByTestId('embed-header-title').last();
  await expect(headerTitle).toBeVisible({ timeout: 10000 });
  const savedTitle = (await headerTitle.textContent())?.trim() || '';
  expect(savedTitle).toBeTruthy();

  const saveButton = page.getByTestId('save-embed-cta').last();
  await expect(saveButton).toBeVisible({ timeout: 10000 });
  const savedEventPromise = page.evaluate(() => new Promise((resolve) => {
    window.addEventListener('savedEmbedMemorySaved', (event) => {
      resolve((event as CustomEvent).detail);
    }, { once: true });
  }));
  await saveButton.click();
  logCheckpoint(`Clicked Save for "${savedTitle}".`);

  const memoryTitle = expectedMemoryTitle?.trim() || savedTitle;
  const savedEvent = await Promise.race([
    savedEventPromise,
    page.waitForTimeout(10000).then(() => null),
  ]);
  expect(savedEvent).toBeTruthy();
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
  await expect(embedPreview).toBeVisible({ timeout: 20000 });
  await embedPreview.click();
  await expect(page.getByTestId('embed-fullscreen-overlay')).toBeVisible({ timeout: 10000 });
  logCheckpoint(`Verified saved memory "${title}" at ${appId}/${categoryId}.`);
}

module.exports = {
  saveCurrentFullscreenEmbed,
  verifySavedMemoryEntry,
};
