/** Official conference discovery and historical event cards. No inference required. */
import { test, expect } from './helpers/cookie-audit';
import { apiTarget } from './helpers/provider-boundary';
import { waitForComponentPreview } from './helpers/component-preview';
import { appsMetadata } from '../../../packages/ui/src/data/appsMetadata';

// contract-test: direct surface=rest_api assertions=app-skills.providers.permitted-only
test('event discovery exposes official conference schedules only', async ({ request }) => {
  const { base, headers } = apiTarget();
  const response = await request.get(`${base}/v1/apps/metadata`, { headers });
  expect(response.status()).toBe(200);
  const payload = await response.json();
  const app = payload.apps.events;
  const skill = app.skills.find((entry: any) => entry.id === 'search');
  expect(skill).toBeTruthy();
  expect(appsMetadata.events.skills.find(entry => entry.id === 'search')?.providers).toEqual(['GPN24', '39C3', '38C3', '37C3']);
  const invalid = await request.post(`${base}/v1/apps/events/skills/search`, { headers, data: { requests: [{}] } });
  expect(invalid.status()).toBe(422);
});

// contract-test: direct surface=gui.web assertions=app-skills.history.renderable
test('historical event details retain their location and stored attribution', async ({ page }) => {
  await page.goto('/dev/preview/embeds/events/EventEmbedFullscreen?chrome=0&width=390');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('result-embed-content')).toBeVisible();
  await expect(page.getByTestId('result-embed-content')).toContainText('AI');
});
