/* eslint-disable @typescript-eslint/no-require-imports */
export {};
const { test, expect } = require('./helpers/cookie-audit');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { parse } = require('yaml');
const { apiTarget, unavailableSkills, registerUnavailableSkillCoverage } = require('./helpers/provider-boundary');
const REPO_ROOT = resolve(__dirname, '../../../..');

const CREATOR_APPS = ['docs', 'mindmaps', 'diagrams', 'electronics'];
const HIDDEN_APPS = ['openmates', 'plans', 'projects', 'tasks', 'workflows', 'health', 'home', 'models3d', 'travel', 'events', 'fitness', 'hosting', 'shopping', 'tv', 'ideabucket'];

test.beforeAll(() => {
  expect(process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'An isolated API credential must be provisioned').toBeTruthy();
});

// contract-test: direct surface=rest_api assertions=app-skills.providers.permitted-only,apps.discovery.public-catalog
test('catalog omits every source-free skill and retains supported metadata', async ({ request }) => {
  const { base, headers } = apiTarget();
  const response = await request.get(`${base}/v1/apps?include_unavailable=true`, { headers });
  expect(response.status()).toBe(200);
  const { apps } = await response.json();
  for (const [appId, skillId] of unavailableSkills) {
    const app = apps.find((entry: any) => entry.id === appId);
    expect(app?.skills?.some((entry: any) => entry.id === skillId) ?? false, `${appId}.${skillId}`).toBe(false);
  }
  for (const appId of HIDDEN_APPS) {
    expect(apps.some((entry: any) => entry.id === appId), `${appId} has no executable public capability`).toBe(false);
  }
  for (const app of apps) {
    expect((app.skills?.length ?? 0) + (app.focus_modes?.length ?? 0) + (app.content_types?.length ?? 0), `${app.id} requires an available skill, focus or declared working content`).toBeGreaterThan(0);
  }
  for (const appId of CREATOR_APPS) {
    const app = apps.find((entry: any) => entry.id === appId);
    expect(app?.content_types?.length, `${appId} preserves its working creator`).toBeGreaterThan(0);
    for (const content of app.content_types) expect(content.source).toBe('self');
  }
  for (const [appId, skillId] of [['web', 'read'], ['weather', 'forecast'], ['jobs', 'search'], ['videos', 'get_transcript'], ['business', 'company_financials']]) {
    expect(apps.find((entry: any) => entry.id === appId)?.skills.some((entry: any) => entry.id === skillId), `${appId}.${skillId}`).toBe(true);
  }
  const metadataResponse = await request.get(`${base}/v1/apps/metadata?include_unavailable=true`, { headers });
  expect(metadataResponse.status()).toBe(200);
  const metadata = await metadataResponse.json();
  for (const appId of HIDDEN_APPS) expect(metadata.apps[appId], `${appId} is not public metadata`).toBeUndefined();
  for (const appId of CREATOR_APPS) expect(metadata.apps[appId]?.content_types?.length, `${appId} has public creator metadata`).toBeGreaterThan(0);
});

// contract-test: direct surface=gui.web assertions=app-skills.history.renderable,app-skills.providers.permitted-only
test('raw durable memory schemas survive discovery retirement while removed Health focuses stay absent', async () => {
  // Discovery metadata is a projection, not the durable schema registry.
  // Read the exact candidate's authored definitions without a production call.
  const health = parse(readFileSync(resolve(REPO_ROOT, 'backend/apps/health/app.yml'), 'utf8'));
  const home = parse(readFileSync(resolve(REPO_ROOT, 'backend/apps/home/app.yml'), 'utf8'));
  expect(health.focuses).toEqual([]);
  const savedListings = home.settings_and_memories.find((entry: any) => entry.id === 'saved_listings');
  expect(savedListings.schema.properties.embed_id.type).toBe('string');
  expect(savedListings.schema.properties.notes.type).toBe('string');
  expect(savedListings.schema.required).toContain('title');
});

for (const [app, skill] of unavailableSkills) registerUnavailableSkillCoverage(app, skill);
for (const [app, preview] of [
  ['health', 'health/HealthAppointmentEmbedPreview'],
  ['home', 'home/HomeListingEmbedFullscreen'],
  ['shopping', 'shopping/ShoppingResultEmbedFullscreen'],
  ['hosting', 'hosting/HostingDomainEmbedFullscreen'],
  ['events', 'events/EventEmbedFullscreen'],
] as const) {
  // Only register the saved-card case here; request checks above own execution.
  // contract-test: direct surface=gui.web assertions=app-skills.history.renderable
  test(`${app} historical result preserves its generic display`, async ({ page }) => {
    const { waitForComponentPreview } = await import('./helpers/component-preview');
    await page.goto(`/dev/preview/embeds/${preview}?chrome=0&width=390`);
    await waitForComponentPreview(page);
    await expect(page.locator('[data-testid="embed-preview"], [data-testid="result-embed-content"]').first()).toBeVisible();
    switch (app) {
      case 'health':
        await expect(page.getByTestId('health-appointment-title')).toHaveText('Dr. Sophie Müller');
        await expect(page.getByTestId('health-appointment-calendar')).toBeVisible();
        await expect(page.getByTestId('embed-preview')).toContainText('Ophthalmologist');
        await expect(page.getByTestId('embed-preview')).toContainText('120 EUR');
        break;
      case 'home':
        await expect(page.locator('.header-title')).toHaveText('Canal apartment with balcony');
        await expect(page.getByTestId('home-price-info')).toContainText(/1[,. ]?250/);
        await expect(page.getByTestId('home-size-info')).toContainText('65 m²');
        break;
      case 'shopping':
        await expect(page.locator('.header-title')).toHaveText('Bio Vollmilch-Joghurt Naturell');
        await expect(page.getByTestId('result-facts')).toContainText(/1[,.]39/);
        await expect(page.getByTestId('shopping-product-gallery').getByRole('button')).toHaveCount(3);
        break;
      case 'hosting':
        await expect(page.getByTestId('hosting-domain-ascii')).toHaveText('cedarcomet.com');
        await expect(page.getByTestId('hosting-domain-registration')).toContainText(/13[,.]09/);
        await expect(page.getByTestId('hosting-domain-renewal')).toContainText(/38[,.]06/);
        break;
      case 'events':
        await expect(page.locator('.header-title')).toHaveText('AI & Machine Learning Berlin Gathering – Spring Edition');
        await expect(page.getByTestId('event-venue-card')).toContainText('Factory Berlin');
        await expect(page.getByTestId('event-description')).toContainText('LLMs in Production');
        break;
    }
  });
}

// contract-test: direct surface=gui.web assertions=app-skills.providers.permitted-only,daily-inspiration.guest-isolated,daily-inspiration.public-defaults
test('guest offline inspiration fallback does not promote paused Events', async ({ page }) => {
  let fallbackRequests = 0;
  await page.route('**/v1/default-inspirations?*', route => {
    fallbackRequests += 1;
    return route.fulfill({ status: 503, json: { detail: 'Isolated fallback fixture' } });
  });
  await page.goto('/?lang=en#chat-id=example-gigantic-airplanes', { waitUntil: 'domcontentloaded' });
  const skip = page.getByTestId('guest-interest-skip');
  if (await skip.isVisible({ timeout: 5000 }).catch(() => false)) await skip.click();
  const newChat = page.locator('[data-testid="new-chat-cta-fullwidth"], [data-testid="new-chat-button"]').first();
  await expect(newChat).toBeVisible({ timeout: 15000 });
  await newChat.click();
  await expect(page.getByTestId('message-editor')).toBeVisible();
  const banner = page.getByTestId('daily-inspiration-banner').first();
  await expect(banner).toBeVisible();
  await expect.poll(() => fallbackRequests).toBeGreaterThan(0);
  await expect(banner).toHaveAttribute('data-inspiration-source', 'guest-onboarding');
  const ids = (await banner.getAttribute('data-visible-inspiration-ids') ?? '').split(',');
  expect(ids).toContain('authenticated-fallback-dreams');
  expect(ids).toContain('authenticated-fallback-antikythera');
  expect(ids).not.toContain('guest-fallback-events');
  expect(ids).not.toContain('authenticated-fallback-export');
  await expect(banner).not.toContainText(/Find local events|Events search/i);
  await expect(page.locator('a[href*="apps/events/skill/search"]')).toHaveCount(0);
});
