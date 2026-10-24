import { test, expect } from './helpers/cookie-audit';
import { appsMetadata } from '../../../packages/ui/src/data/appsMetadata';
import { apiTarget, unavailableSkills, registerUnavailableSkillCoverage } from './helpers/provider-boundary';

test.beforeAll(() => {
  expect(process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'An isolated API credential must be provisioned').toBeTruthy();
});

// contract-test: direct surface=rest_api assertions=app-skills.providers.permitted-only
test('catalog omits every source-free skill and retains supported metadata', async ({ request }) => {
  const { base, headers } = apiTarget();
  const response = await request.get(`${base}/v1/apps?include_unavailable=true`, { headers });
  expect(response.status()).toBe(200);
  const { apps } = await response.json();
  for (const [appId, skillId] of unavailableSkills) {
    const app = apps.find((entry: any) => entry.id === appId);
    expect(app?.skills?.some((entry: any) => entry.id === skillId) ?? false, `${appId}.${skillId}`).toBe(false);
  }
  for (const [appId, skillId] of [['web', 'read'], ['events', 'search'], ['jobs', 'search'], ['videos', 'search'], ['business', 'company_financials']]) {
    expect(apps.find((entry: any) => entry.id === appId)?.skills.some((entry: any) => entry.id === skillId), `${appId}.${skillId}`).toBe(true);
  }
  const events = apps.find((entry: any) => entry.id === 'events').skills.find((entry: any) => entry.id === 'search');
  expect(events.providers.length).toBeGreaterThan(0);
  for (const provider of events.providers) expect(['gpn24', '39c3', '38c3', '37c3', 'skill']).toContain(provider.provider);
});

// contract-test: direct surface=gui.web assertions=app-skills.history.renderable,app-skills.providers.permitted-only
test('local memories and focus modes survive source retirement in the static app catalog', async () => {
  expect(appsMetadata.health.focus_modes.map(entry => entry.id)).toContain('prepare_doctor_appointment');
  expect(appsMetadata.health.skills).toEqual([]);
  expect(appsMetadata.home.settings_and_memories.some(entry => entry.id === 'saved_listings')).toBe(true);
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
