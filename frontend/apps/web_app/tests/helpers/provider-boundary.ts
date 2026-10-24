import { expect, test } from './cookie-audit';
import { arch, platform } from 'node:os';
import { splitApiKeyCredential } from '../../../../packages/openmates-cli/src/crypto';
import { waitForComponentPreview } from './component-preview';

export const unavailableSkills = [
  ['web', 'read'],
  ['shopping', 'search_products'], ['health', 'search_appointments'],
  ['fitness', 'search_locations'], ['fitness', 'search_classes'],
  ['electronics', 'search_components'], ['home', 'search'],
  ['hosting', 'search_domains'], ['business', 'search_trademarks'],
  ['travel', 'search_connections'], ['travel', 'search_stays'], ['models3d', 'search'],
] as const;

export function apiTarget() {
  const credential = process.env.OPENMATES_TEST_ACCOUNT_API_KEY;
  expect(credential, 'An isolated CI account credential is required').toBeTruthy();
  return {
    base: process.env.OPENMATES_E2E_API_URL || process.env.PLAYWRIGHT_TEST_API_URL || 'http://localhost:8000',
    headers: {
      Authorization: `Bearer ${splitApiKeyCredential(credential || '').bearer}`,
      'X-OpenMates-SDK': 'cli',
      'X-OpenMates-Device-Identity': `cli:${platform()}:${arch()}`,
    },
  };
}

export async function expectUnavailableSkill(request: import('@playwright/test').APIRequestContext, app: string, skill: string) {
  const { base, headers } = apiTarget();
  const response = await request.post(`${base}/v1/apps/${app}/skills/${skill}`, {
    headers, data: { requests: [{ query: 'synthetic fixture' }] },
  });
  expect(response.status()).toBe(404);
}

export async function expectHistoricalCard(page: import('@playwright/test').Page, preview: string) {
  await page.goto(`/dev/preview/embeds/${preview}?chrome=0&width=390`);
  await waitForComponentPreview(page);
  await expect(page.locator('[data-testid="embed-preview"], [data-testid="result-embed-content"]').first()).toBeVisible();
  expect((await page.locator('body').innerText()).trim().length).toBeGreaterThan(20);
}

export function registerUnavailableSkillCoverage(app: string, skill: string, preview?: string) {
  // contract-test: supporting surface=rest_api assertions=app-skills.providers.unavailable-no-network
  test(`${app}.${skill} rejects direct execution while no permitted source exists`, async ({ request }) => {
    await expectUnavailableSkill(request, app, skill);
  });
  if (preview) {
    // contract-test: direct surface=gui.web assertions=app-skills.history.renderable
    test(`${app}.${skill} historical card remains readable`, async ({ page }) => {
      await expectHistoricalCard(page, preview);
    });
  }
}
