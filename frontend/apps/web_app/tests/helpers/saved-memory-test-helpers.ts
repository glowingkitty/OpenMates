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
  const headerTitle = page.getByTestId('embed-header-title').first();
  await expect(headerTitle).toBeVisible({ timeout: 10000 });
  const savedTitle = (await headerTitle.textContent())?.trim() || '';
  expect(savedTitle).toBeTruthy();

  const saveButton = page.getByTestId('save-embed-cta').first();
  await expect(saveButton).toBeVisible({ timeout: 10000 });
  await saveButton.click();
  logCheckpoint(`Clicked Save for "${savedTitle}".`);

  const memoryTitle = expectedMemoryTitle?.trim() || savedTitle;
  await expect(page.getByText(new RegExp(`Saved.*${escapeRegExp(memoryTitle)}`, 'i'))).toBeVisible({ timeout: 20000 });
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
  await expect(entries.filter({ hasText: title }).first()).toBeVisible({ timeout: 20000 });
  const embedPreview = page.getByTestId('memory-embed-preview').first();
  await expect(embedPreview).toBeVisible({ timeout: 20000 });
  await embedPreview.click();
  await expect(page.getByTestId('embed-fullscreen-overlay')).toBeVisible({ timeout: 10000 });
  logCheckpoint(`Verified saved memory "${title}" at ${appId}/${categoryId}.`);
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

module.exports = {
  saveCurrentFullscreenEmbed,
  verifySavedMemoryEntry,
};
