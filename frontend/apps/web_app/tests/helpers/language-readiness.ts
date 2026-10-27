import { expect, type Page, type TestInfo } from '@playwright/test';
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';

/** Identify the built dictionary offline so interception cannot stall other modules. */
export async function germanDictionaryPath(testInfo: TestInfo): Promise<string> {
  const chunks = path.resolve(__dirname, '../../.svelte-kit/output/client/_app/immutable/chunks');
  const files = (await readdir(chunks)).filter(file => file.endsWith('.js'));
  const matches = (await Promise.all(files.map(async file => {
    const body = await readFile(path.join(chunks, file), 'utf8');
    return body.includes('Hallo!') && body.includes('Automatisch (Browsersprache)') ? file : null;
  }))).filter((file): file is string => file !== null);
  await testInfo.attach('german-dictionary-assets', {
    body: JSON.stringify({ chunks, matches }),
    contentType: 'application/json',
  });
  expect(matches, 'exactly one compiled German dictionary').toHaveLength(1);
  return `/_app/immutable/chunks/${matches[0]}`;
}

/** Wait for the real app shell while the selected dictionary response is held. */
export async function waitForNeutralLanguageStartup(page: Page, testInfo: TestInfo): Promise<void> {
  const shell = page.getByTestId('language-startup');
  const welcome = page.getByTestId('chat-welcome-heading');
  try {
    // Cold module loading has the same readiness budget as the first app text.
    await expect(shell).toBeVisible({ timeout: 30_000 });
    await expect(welcome).toHaveCount(0);
  } catch (error) {
    await testInfo.attach('language-startup-state', {
      body: JSON.stringify({ shellCount: await shell.count(), welcomeCount: await welcome.count(), language: await page.locator('html').getAttribute('lang') }),
      contentType: 'application/json',
    });
    throw error;
  }
}
