// contract-test-file: infrastructure
import type { Page } from '@playwright/test';
import { expect, test } from './cookie-audit';

const catalogIds = (page: Page) => page.getByTestId('apps-all-items-grid').locator('[data-app-id]')
  .evaluateAll(elements => elements.map(element => element.getAttribute('data-app-id')!).sort());

async function attachCatalogDiagnostics(page: Page, label: string, expected: string[], responseStatus: number | 'cached' | null) {
  const actual = await catalogIds(page).catch(() => []);
  await test.info().attach(`apps-catalog-readiness-${label}`, {
    body: JSON.stringify({ responseStatus, expected, actual,
      missing: expected.filter(id => !actual.includes(id)),
      extra: actual.filter(id => !expected.includes(id)) }, null, 2),
    contentType: 'application/json',
  });
}

/** Warm hash navigation reuses the already validated runtime response. */
export async function expectRuntimeAppsCatalogIds(page: Page, label: string, expected: string[]) {
  try {
    expect(expected.length, `${label}: validated runtime catalog is nonempty`).toBeGreaterThan(0);
    await expect(page.getByTestId('apps-all-items-grid')).toBeVisible();
    await expect.poll(() => catalogIds(page), { message: `${label}: cards match the validated runtime metadata` }).toEqual(expected);
  } catch (error) {
    await attachCatalogDiagnostics(page, label, expected, 'cached');
    throw error;
  }
}

/** Settle the public runtime projection before comparing catalog navigation. */
export async function enterRuntimeAppsCatalog(page: Page, label: string, navigate: () => Promise<unknown>) {
  const metadataResponse = page.waitForResponse(response =>
    response.request().method() === 'GET'
    && new URL(response.url()).pathname === '/v1/apps/metadata');
  let expected: string[] = [];
  let responseStatus: number | null = null;
  try {
    const [, response] = await Promise.all([navigate(), metadataResponse]);
    responseStatus = response.status();
    expect(responseStatus, `${label}: runtime metadata request succeeds`).toBe(200);
    const metadata = await response.json();
    expect(metadata.apps, `${label}: successful runtime metadata includes apps`).toBeTruthy();
    // AI has its own Settings surface; Apps deliberately excludes its card.
    expected = Object.keys(metadata.apps).filter(id => id !== 'ai').sort();
    expect(expected.length, `${label}: runtime catalog is nonempty`).toBeGreaterThan(0);
  } catch (error) {
    await attachCatalogDiagnostics(page, label, expected, responseStatus);
    throw error;
  }
  await expectRuntimeAppsCatalogIds(page, label, expected);
  return expected;
}
