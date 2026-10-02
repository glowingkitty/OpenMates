/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/** Browser contracts for public Apps navigation, schema forms, and guest admission. */
export {};
import { assertGuestHeaderControlsSeparated } from './helpers/header-layout';
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount, submitPasswordAndHandleOtp } = require('./helpers/chat-test-helpers');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

type SkillFixture = {
  app_id: string;
  skill_id: string;
  name: string;
  primary_fields: string[];
  anonymous_allowed: boolean;
  requestEnvelope?: boolean;
};

async function fixtureSkillDetails(page: any, fixture: SkillFixture): Promise<void> {
  const { app_id, skill_id, name, primary_fields, anonymous_allowed, requestEnvelope } = fixture;
  await page.route(`**/v1/apps/${app_id}/skills/${skill_id}/details`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        app_id,
        skill_id,
        slug: skill_id.replaceAll('_', '-'),
        name,
        name_translation_key: `${app_id}.${skill_id}.name`,
        description: `${name} fixture description`,
        description_translation_key: `${app_id}.${skill_id}.description`,
        icon_image: null,
        input_schema: requestEnvelope ? {
          type: 'object', required: ['requests'], properties: { requests: {
            type: 'array', minItems: 1, 'x-ui': { basic: true }, items: {
              type: 'object', required: ['query'], properties: {
                query: { type: 'string', title: 'Query', minLength: 1, 'x-ui': { basic: true } },
                count: { type: 'integer', title: 'Count', default: 10, minimum: 1, maximum: 20, 'x-ui': { basic: true } },
              },
            },
          } },
        } : {
          type: 'object',
          properties: {
            query: { type: 'string', title: 'Query', minLength: 1 },
            location: { type: 'string', title: 'Location' },
            limit: { type: 'integer', title: 'Limit', minimum: 1, maximum: 10 },
          },
          required: ['query'],
        },
        primary_fields: requestEnvelope ? ['requests[].query', 'requests[].count'] : primary_fields,
        defaults: requestEnvelope ? { requests: [{ count: 10 }] } : { location: 'Berlin', limit: 5 },
        pricing: null,
        providers: [],
        models: [],
        anonymous_allowed,
        execution_available: true,
        unavailable_reason: null,
        execution_mode: 'sync',
      }),
    });
  });
}

function appHash(page: any): string {
  return new URL(page.url()).hash.split('&', 1)[0];
}

function expectPersonalPageQuery(params: URLSearchParams | undefined, appId: string, offset: number): void {
  expect(params?.get('app_id')).toBe(appId);
  expect(params?.get('offset')).toBe(String(offset));
  expect(params?.get('limit')).toBe('20');
  expect(params?.has('team_id')).toBe(false);
}

async function assertProfileInHeader(page: any): Promise<void> {
  const profile = page.getByTestId('profile-container');
  await expect(profile).toBeVisible();
  await profile.evaluate(async (element: Element) => {
    const wrapper = element.closest('.profile-container-wrapper');
    if (wrapper) await Promise.all(wrapper.getAnimations().map(animation => animation.finished.catch(() => {})));
  });
  const header = await page.locator('header').first().boundingBox();
  const account = await profile.boundingBox();
  expect(account.y).toBeGreaterThanOrEqual(header.y);
  expect(account.y + account.height).toBeLessThanOrEqual(header.y + header.height + 4);
}

test.describe('Apps workspace', () => {
  // contract-test: direct surface=gui.web assertions=apps.discovery.public-catalog,apps.navigation.hash-and-forwarding,apps.presentation.shared-detail-and-recency,workspace-shell.start.shared-affordances
  test('Show all replaces the home with the shared searchable grid and restores it after app close', async ({ page }: { page: any }) => {
    test.setTimeout(90000);
    for (const width of [1180, 390]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(getE2EDebugUrl('/#apps/all'), { waitUntil: 'domcontentloaded' });
      const grid = page.getByTestId('apps-all-items-grid');
      await expect(grid).toBeVisible({ timeout: 30000 });
      await expect(page.getByTestId('apps-all-items-toolbar')).toBeVisible();
      await page.getByTestId('apps-back-to-recent').click();
      await expect.poll(() => appHash(page)).toBe('#apps');
      await expect(page.getByTestId('apps-daily-inspiration-area')).toBeVisible();
      const homeCard = page.getByTestId('apps-app-card').getByTestId('app-store-card').filter({ hasText: /Web/i }).first();
      await expect(homeCard).toBeVisible();
      if (width === 1180) await expect(homeCard).toHaveCSS('height', '129px');
      else await expect(homeCard).toHaveCSS('height', '44px');

      await page.getByTestId('apps-show-all').click();
      await expect.poll(() => appHash(page)).toBe('#apps/all');
      await expect(grid).toBeVisible();
      await expect(grid).toHaveCSS('display', 'grid');
      await expect(page.getByTestId('apps-daily-inspiration-area')).toHaveCount(0);
      await expect(page.getByTestId('apps-home-apps')).toHaveCount(0);
      await expect(page.getByRole('heading', { name: 'What app do you want to use?' })).toHaveCount(0);
      await expect(page.locator('.workspace-composer-slot, .ProseMirror, textarea')).toHaveCount(0);
      await expect(page.getByTestId('apps-search')).toHaveText('Search');
      await page.getByTestId('apps-search').click();
      const controls = page.getByTestId('apps-catalog-controls');
      const search = controls.getByRole('textbox');
      await expect(search).toBeFocused();
      await search.fill('Brave');
      const web = grid.locator('[data-app-id="web"]');
      await expect(web).toBeVisible();
      await expect(web).toHaveClass(/app-store-card/);
      await expect(web.getByTestId('app-card-name')).toHaveCSS('text-align', 'left');
      await expect(grid.locator('[data-app-id="health"]')).toHaveCount(0);
      await search.fill('no-app-matches-this-query-7295');
      await expect(grid.getByTestId('apps-all-item')).toHaveCount(0);
      await expect(page.getByTestId('apps-all-items-empty')).toHaveText(/No apps found/i);
      await search.fill('');
      await controls.getByRole('combobox', { name: 'Sort', exact: true }).selectOption('name_asc');
      const names = await grid.getByTestId('app-card-name').allTextContents();
      expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b)));
      await expect(grid.locator('[data-app-id="weather"]')).toHaveCount(1);
      await controls.getByRole('combobox', { name: 'Filter', exact: true }).selectOption('focus_modes');
      await expect(web).toBeVisible();
      await expect(grid.locator('[data-app-id="health"]')).toHaveCount(1);
      await expect(grid.locator('[data-app-id="weather"]')).toHaveCount(0);
      await web.click();
      await expect.poll(() => appHash(page)).toBe('#apps/web');
      await expect(page.getByTestId('apps-detail-fullscreen')).toBeVisible();
      await page.getByTestId('apps-detail-close').click();
      await expect.poll(() => appHash(page)).toBe('#apps/all');
      await expect(grid).toBeVisible();
      await expect(controls.getByRole('combobox', { name: 'Filter', exact: true })).toHaveValue('focus_modes');
      await page.getByTestId('apps-back-to-recent').click();
      await expect.poll(() => appHash(page)).toBe('#apps');
      await expect(homeCard).toBeVisible();
      await page.goBack();
      await expect.poll(() => appHash(page)).toBe('#apps/all');
      await expect(grid).toBeVisible();
      await page.goForward();
      await expect.poll(() => appHash(page)).toBe('#apps');
      await expect(page.getByTestId('apps-home-apps')).toBeVisible();
    }
  });

  // contract-test: direct surface=gui.web assertions=apps.discovery.public-catalog,apps.navigation.hash-and-forwarding
  test('guest browses the app and compact skill URL, then Back, Forward, and close restore the parent', async ({ page }: { page: any }) => {
    test.setTimeout(90000);
    await fixtureSkillDetails(page, {
      app_id: 'health', skill_id: 'search_appointments', name: 'Search appointments',
      primary_fields: ['query', 'location'], anonymous_allowed: false,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(getE2EDebugUrl('/#apps'), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('apps-workspace-home')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('apps-workspace-home').locator('.workspace-eyebrow')).toHaveCount(0);
    await expect(page.getByTestId('apps-workspace-background-icon')).toBeVisible();
    await expect(page.locator('.workspace-composer-slot')).toHaveCount(0);
    await expect(page.getByTestId('apps-quick-use-affordance')).toHaveCount(0);
    await expect(page.locator('.ProseMirror, textarea')).toHaveCount(0);
    await expect(page.getByTestId('workspace-mobile-select')).toBeVisible();
    await expect(page.getByTestId('workspace-mobile-select')).toHaveValue('/#apps');
    await page.getByTestId('apps-app-card').filter({ hasText: /Health/i }).first().click();
    await expect(page.getByTestId('apps-detail-fullscreen')).toBeVisible();
    expect(appHash(page)).toBe('#apps/health');

    await page.getByTestId('settings-skill-cards-scroll').getByText(/Search appointments/i).first().click();
    await expect(page.getByTestId('apps-skill-form')).toBeVisible({ timeout: 30000 });
    expect(appHash(page)).toBe('#apps/health/search-appointments');
    await page.goBack();
    expect(appHash(page)).toBe('#apps/health');
    await page.goForward();
    await expect(page.getByTestId('apps-skill-form')).toBeVisible();
    await page.getByTestId('apps-detail-close').click();
    await expect.poll(() => appHash(page)).toBe('#apps/health');

    await page.goto(getE2EDebugUrl('/apps/health/search-appointments'), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('apps-skill-form')).toBeVisible({ timeout: 30000 });
    expect(appHash(page)).toBe('#apps/health/search-appointments');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('apps-skill-form')).toBeVisible({ timeout: 30000 });
  });

  // contract-test: direct surface=gui.web assertions=apps.discovery.public-catalog,apps.forms.metadata-driven,apps.navigation.hash-and-forwarding
  test('real public skill schema loads after cold boot and leaving Apps cannot reopen the detail', async ({ page }: { page: any }) => {
    test.setTimeout(90000);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(getE2EDebugUrl('/#apps'), { waitUntil: 'domcontentloaded' });
    await page.evaluate(async () => {
      localStorage.clear();
      for (const database of await indexedDB.databases()) {
        if (database.name) indexedDB.deleteDatabase(database.name);
      }
    });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('apps-workspace-home')).toBeVisible({ timeout: 30000 });
    const card = page.getByTestId('apps-app-card').filter({ hasText: /Web/i }).first();
    await expect(card.getByTestId('app-store-card')).toBeVisible();
    await assertProfileInHeader(page);
    await page.getByTestId('profile-container').click();
    await expect(page.getByTestId('settings-menu')).toBeVisible();
    await page.getByTestId('icon-button-close').click();
    await expect(page.getByTestId('settings-menu')).not.toBeVisible();

    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      const selector = page.getByTestId('workspace-mobile-select');
      const login = page.getByTestId('header-login-signup-btn');
      await expect(login).toBeVisible();
      await expect(login).toContainText(/Login|Sign\s*up/i);
      await expect(selector).toBeVisible();
      await assertGuestHeaderControlsSeparated(page, true);
      const appsUrl = page.url();
      await login.click();
      const signupLayer = page.locator('.apps-auth-layer');
      await expect(signupLayer).toBeVisible();
      // The signup icon artwork must not intercept the phone close control.
      await signupLayer.getByRole('button', { name: 'Close', exact: true }).click();
      await expect(signupLayer).toHaveCount(0);
      expect(page.url()).toBe(appsUrl);
    }
    await page.setViewportSize({ width: 1440, height: 1000 });

    // Keep this endpoint real: fixtures cannot prove deployed CORS admission.
    const details = page.waitForResponse((response: any) => response.url().includes('/v1/apps/web/skills/search/details') && response.request().method() === 'GET');
    await page.getByTestId('apps-nav-link').click();
    await page.goto(getE2EDebugUrl('/#apps/web/search'), { waitUntil: 'domcontentloaded' });
    expect((await details).status()).toBe(200);
    await expect(page.getByTestId('apps-skill-form')).toBeVisible({ timeout: 30000 });
    await assertProfileInHeader(page);
    await expect(page.getByText('The skill details could not be loaded.', { exact: true })).toHaveCount(0);
    await expect(page.getByTestId('apps-skill-context-details')).toHaveCount(0);
    await page.getByTestId('apps-skill-context-toggle').click();
    await expect(page.getByTestId('apps-skill-context-details')).toBeVisible();
    await page.getByTestId('apps-skill-context-toggle').click();
    await expect(page.getByTestId('apps-skill-context-details')).toHaveCount(0);
    const hero = page.getByTestId('apps-hero-icon');
    await expect(hero).toHaveAttribute('aria-hidden', 'true');
    await expect(hero).toHaveCSS('pointer-events', 'none');
    const iconBounds = await hero.boundingBox();
    await page.mouse.click(iconBounds.x + iconBounds.width / 2, iconBounds.y + iconBounds.height / 2);
    expect(appHash(page)).toBe('#apps/web/search');
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('globalChatSelected', { detail: { chat_id: 'background-restoration' } })));
    expect(appHash(page)).toBe('#apps/web/search');
    await page.getByTestId('chats-nav-link').click();
    await expect(page.getByTestId('apps-workspace')).toHaveCount(0);
    expect(appHash(page)).not.toMatch(/^#apps/);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('chats-nav-link')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('apps-workspace')).toHaveCount(0);
    expect(appHash(page)).not.toMatch(/^#apps/);
  });

  // contract-test: direct surface=gui.web assertions=apps.navigation.hash-and-forwarding,apps.forms.metadata-driven,apps.execution.direct-shared-contract,apps.results.web-retained-graph,workspace-shell.nav.released-surfaces-visible
  test('login from a skill preserves its route and input, then Chats exits Apps on desktop and mobile', async ({ page }: { page: any }) => {
    test.setTimeout(180000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    const credentials = getTestAccount();
    await fixtureSkillDetails(page, {
      app_id: 'web', skill_id: 'search', name: 'Search web',
      primary_fields: ['query'], anonymous_allowed: false,
    });
    await page.goto(getE2EDebugUrl('/#apps/web/search&tab=overview'), { waitUntil: 'domcontentloaded' });
    const initialUrl = page.url();
    const query = page.getByTestId('apps-skill-form').getByRole('textbox', { name: 'Query' });
    await expect(query).toBeVisible({ timeout: 30000 });
    await query.fill('gpt 6 astra');
    await page.evaluate(() => { (window as Window & { appsLoginDocument?: string }).appsLoginDocument = 'same-document'; });
    await page.getByTestId('apps-skill-signup').click();
    await expect(page.locator('.apps-auth-layer')).toBeVisible();
    await page.getByTestId('tab-login').click();
    await page.getByTestId('login-email-input').fill(credentials.email);
    if (!await page.locator('#stayLoggedIn').isChecked()) {
      await page.locator('label.toggle[for="stayLoggedIn"], label.toggle:has(#stayLoggedIn)').click();
    }
    await expect(page.getByTestId('login-continue-button')).toBeEnabled();
    await page.getByTestId('login-continue-button').click();
    await expect(page.getByTestId('login-password-input')).toBeVisible({ timeout: 15000 });
    await page.getByTestId('login-password-input').fill(credentials.password);
    await submitPasswordAndHandleOtp(page, credentials.otpKey);
    await expect(page.locator('.apps-route')).toHaveAttribute('data-authenticated', 'true');
    await expect(page.locator('.apps-auth-layer')).toHaveCount(0);
    await expect(page.getByTestId('header-login-signup-btn')).toBeHidden();
    expect(page.url()).toBe(initialUrl);
    expect(await page.evaluate(() => (window as Window & { appsLoginDocument?: string }).appsLoginDocument)).toBe('same-document');
    await expect(query).toHaveValue('gpt 6 astra');
    await expect(page.getByTestId('apps-skill-submit')).toBeVisible();
    // Exercise the retained request immediately after login, before visiting
    // another route or reloading to fill in any missing session state.
    let skillPosts = 0;
    await page.route('**/v1/apps/web/skills/search', (request: any) => {
      skillPosts += 1;
      expect(request.request().postDataJSON().query).toBe('gpt 6 astra');
      return request.fulfill({ json: { success: true, data: { results: [{ id: 'request-1', results: [{
        type: 'search_result', title: 'Saved search after login', url: 'https://example.test/apps/login-return',
        description: 'Safe result fixture after authentication.',
      }] }] } } });
    });
    await page.getByTestId('apps-skill-submit').click();
    await expect(page.getByTestId('apps-inline-results-grid')).toContainText('Saved search after login', { timeout: 30000 });
    await expect(page.getByTestId('apps-result-fullscreen')).toHaveCount(0);
    expect(page.url()).toBe(initialUrl);
    await expect(query).toHaveValue('gpt 6 astra');
    const geometry = await page.evaluate(() => ({ button: document.querySelector('[data-testid=apps-skill-submit]')!.getBoundingClientRect().bottom, results: document.querySelector('[data-testid=apps-inline-results]')!.getBoundingClientRect().top }));
    expect(geometry.results).toBeGreaterThan(geometry.button);
    await page.getByTestId('apps-inline-results-grid').getByTestId('embed-preview').click();
    await expect(page.getByTestId('apps-result-fullscreen')).toContainText('Saved search after login');
    const childUrl = page.url();
    expect(childUrl).toMatch(/&embed-id=[0-9a-f-]{36}&root-id=[0-9a-f-]{36}/i);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('apps-result-fullscreen')).toContainText('Saved search after login', { timeout: 30000 });
    await expect(page.getByTestId('apps-result-fullscreen').getByTestId('search-template-grid')).toHaveCount(0);
    expect(page.url()).toBe(childUrl);
    expect(skillPosts).toBe(1);
    await expect(page.getByText('The request could not finish. You can try again.', { exact: true })).toHaveCount(0);
    await page.getByTestId('apps-result-fullscreen').getByTestId('embed-minimize').click();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      if (width === 1440) await page.getByTestId('apps-nav-link').click();
      else await page.getByTestId('workspace-mobile-select').selectOption('/#apps');
      await expect(page.getByTestId('apps-workspace-home')).toBeVisible({ timeout: 30000 });
      await assertProfileInHeader(page);
      if (width === 1440) {
        expect(await page.locator('.icon-tab-bar').getByRole('link').evaluateAll((links: Element[]) => links.map(link => link.getAttribute('data-testid')))).toEqual([
          'chats-nav-link', 'apps-nav-link', 'projects-nav-link', 'tasks-nav-link', 'workflows-nav-link',
        ]);
      } else {
        expect(await page.getByTestId('workspace-mobile-select').locator('option').evaluateAll((options: HTMLOptionElement[]) => options.map(option => option.value))).toEqual([
          '/', '/#apps', '/#projects', '/#tasks', '/#workflows',
        ]);
      }
      await page.getByTestId('apps-app-card').getByTestId('app-store-card').filter({ hasText: /Web/i }).first().click();
      await page.getByTestId('settings-skill-cards-scroll').getByText('Search', { exact: true }).first().click();
      await expect(page.getByTestId('apps-skill-form')).toBeVisible({ timeout: 30000 });
      await assertProfileInHeader(page);
      if (width === 1440) await page.getByTestId('chats-nav-link').click();
      else await page.getByTestId('workspace-mobile-select').selectOption('/');
      await expect(page.getByTestId('apps-workspace')).toHaveCount(0);
      await expect(page.locator('[data-authenticated="true"]')).toBeVisible({ timeout: 30000 });
      await expect(page.locator('.ProseMirror')).toBeVisible({ timeout: 30000 });
      expect(appHash(page)).not.toMatch(/^#apps/);
      await page.goBack();
      await expect(page.getByTestId('apps-skill-form')).toBeVisible({ timeout: 30000 });
      await page.goForward();
      await expect(page.getByTestId('apps-workspace')).toHaveCount(0);
      expect(appHash(page)).not.toMatch(/^#apps/);
    }
  });

  // contract-test: direct surface=gui.web assertions=apps.navigation.hash-and-forwarding,apps.presentation.shared-detail-and-recency,workspace-shell.start.chat-visual-parity
  test('Apps keeps shared gutters and safely exits to Chats while Settings closes', async ({ page }: { page: any }) => {
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto(getE2EDebugUrl('/#apps/web/search'), { waitUntil: 'domcontentloaded' });
      const fullscreen = page.getByTestId('apps-detail-fullscreen');
      await expect(fullscreen).toBeVisible({ timeout: 30000 });
      const main = page.locator('.apps-route-body > main');
      const header = await page.getByTestId('global-header').boundingBox();
      const bounds = await main.boundingBox();
      const geometry = await main.evaluate((element: Element) => ({
        scrollX: window.scrollX,
        viewportWidth: window.innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        ancestors: [element, element.parentElement, element.closest('.apps-route'), document.body].map(node => {
          const box = node.getBoundingClientRect();
          const style = getComputedStyle(node);
          return { className: node.className, x: box.x, width: box.width, position: style.position, transform: style.transform,
            scrollLeft: node.scrollLeft, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth, overflowX: style.overflowX };
        }),
      }));
      await test.info().attach(`apps-layout-${width}`, { body: JSON.stringify(geometry), contentType: 'application/json' });
      expect(bounds.x).toBeCloseTo(10, 0);
      expect(bounds.y).toBeCloseTo(header.y + header.height + 10, 0);
      expect(width - bounds.x - bounds.width).toBeCloseTo(width === 1440 ? 20 : 10, 0);
      expect(1000 - bounds.y - bounds.height).toBeCloseTo(10, 0);
      await page.getByTestId('embed-report-issue-button').click();
      const settings = page.getByTestId('settings-menu');
      await expect(settings).toBeVisible();
      await expect(settings).toHaveCSS('width', '323px');
      await settings.evaluate(async (element: Element) => {
        await Promise.all(element.getAnimations().map(animation => animation.finished.catch(() => {})));
      });
      const panel = await settings.boundingBox();
      expect(width - panel.x - panel.width).toBeCloseTo(width === 1440 ? 20 : 10, 0);
      if (width === 1440) {
        const narrowed = await main.boundingBox();
        expect(panel.x - narrowed.x - narrowed.width).toBeCloseTo(20, 0);
        expect(panel.y).toBeCloseTo(narrowed.y, 0);
        expect(narrowed.x).toBeCloseTo(10, 0);
      }
      const screenshot = test.info().outputPath(`apps-settings-gutters-${width}.png`);
      await page.screenshot({ path: screenshot, animations: 'disabled' });
      await test.info().attach(`apps-settings-gutters-${width}`, { path: screenshot, contentType: 'image/png' });
      // Observe the actual close callbacks so the assertion cannot finish
      // before a delayed write runs after Apps has unmounted. Timer delays
      // and production callbacks are unchanged.
      await page.evaluate(() => {
        const browser = window as Window & {
          appsSettingsCloseTimers?: { scheduled: number; settled: number };
          appsSettingsRestoreTimers?: () => void;
        };
        const stats = { scheduled: 0, settled: 0 };
        browser.appsSettingsCloseTimers = stats;
        const original = window.setTimeout;
        window.setTimeout = ((handler: TimerHandler, delay?: number, ...args: unknown[]) => {
          if (delay !== 300 || typeof handler !== 'function') {
            return original.call(window, handler, delay, ...args);
          }
          stats.scheduled += 1;
          return original.call(window, () => {
            try { handler(...args); }
            finally { stats.settled += 1; }
          }, delay);
        }) as typeof window.setTimeout;
        browser.appsSettingsRestoreTimers = () => { window.setTimeout = original; };
      });
      const navigationErrors: string[] = [];
      const recordError = (error: Error) => navigationErrors.push(error.message);
      page.on('pageerror', recordError);
      await page.getByTestId('icon-button-close').click();
      if (width === 1440) await page.getByTestId('chats-nav-link').click();
      else await page.getByTestId('workspace-mobile-select').selectOption('/');
      await expect(page.getByTestId('apps-workspace')).toHaveCount(0);
      await page.evaluate(() => {
        (window as Window & { appsSettingsRestoreTimers?: () => void }).appsSettingsRestoreTimers?.();
      });
      await expect.poll(() => page.evaluate(() => {
        const stats = (window as Window & { appsSettingsCloseTimers?: { scheduled: number; settled: number } }).appsSettingsCloseTimers;
        return stats && stats.scheduled > 0 && stats.scheduled === stats.settled;
      })).toBe(true);
      expect(navigationErrors).toEqual([]);
      page.off('pageerror', recordError);
      await expect(page.locator('.ProseMirror').first()).toBeVisible({ timeout: 30000 });
      expect(appHash(page)).not.toMatch(/^#apps/);
    }
  });

  // contract-test: direct surface=gui.web assertions=apps.forms.metadata-driven
  test('declared primary fields and defaults stay in the form when settings expand', async ({ page }: { page: any }) => {
    await fixtureSkillDetails(page, {
      app_id: 'web', skill_id: 'search', name: 'Search web',
      primary_fields: ['query'], anonymous_allowed: false,
    });
    await page.goto(getE2EDebugUrl('/#apps/web/search'), { waitUntil: 'domcontentloaded' });
    const form = page.getByTestId('apps-skill-form');
    await expect(form).toBeVisible({ timeout: 30000 });
    const primary = form.getByTestId('apps-skill-primary-fields');
    expect(await primary.locator('input, textarea, select').count()).toBeLessThanOrEqual(2);
    await expect(form.getByTestId('apps-skill-settings')).toHaveCount(0);
    await form.getByTestId('apps-skill-settings-toggle').click();
    const settings = form.getByTestId('apps-skill-settings');
    await expect(settings).toBeVisible();
    await expect(settings.getByRole('textbox', { name: 'Location' })).toHaveValue('Berlin');
    await expect(settings.getByRole('spinbutton', { name: 'Limit' })).toHaveValue('5');
  });

  // contract-test: direct surface=gui.web assertions=apps.navigation.hash-and-forwarding,apps.discovery.public-catalog
  test('legacy Settings links forward and public focus and memory details remain reachable', async ({ page }: { page: any }) => {
    await fixtureSkillDetails(page, {
      app_id: 'health', skill_id: 'search_appointments', name: 'Search appointments',
      primary_fields: ['query', 'location'], anonymous_allowed: false,
    });
    await page.goto(getE2EDebugUrl('/#settings/apps/health/skill/search_appointments'), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('apps-skill-form')).toBeVisible({ timeout: 30000 });
    expect(appHash(page)).toBe('#apps/health/search-appointments');

    await page.goto(getE2EDebugUrl('/#apps/health/focus/prepare_doctor_appointment'), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('focus-mode-details')).toBeVisible({ timeout: 30000 });
    await page.goto(getE2EDebugUrl('/#apps/health/memory/medical_history'), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('app-settings-memories-category')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('app-settings-memories-category')).toHaveAttribute('data-category-id', 'medical_history');
  });

  // contract-test: supporting surface=gui.web assertions=apps.anonymous.cli-equivalent-gate
  test('guest sees Signup before an ineligible skill can dispatch', async ({ page }: { page: any }) => {
    await fixtureSkillDetails(page, {
      app_id: 'web', skill_id: 'search', name: 'Search web',
      primary_fields: ['query'], anonymous_allowed: false,
    });
    const dispatched: string[] = [];
    page.on('request', (request: any) => {
      if (request.method() === 'POST' && /\/v1\/(apps|skills)\//.test(request.url())) dispatched.push(request.url());
    });
    await page.goto(getE2EDebugUrl('/#apps/web/search'), { waitUntil: 'domcontentloaded' });
    const form = page.getByTestId('apps-skill-form');
    await expect(form.getByTestId('apps-skill-signup')).toBeVisible({ timeout: 30000 });
    await expect(form.getByTestId('apps-skill-submit')).toHaveCount(0);
    expect(dispatched).toEqual([]);
    await form.getByTestId('apps-skill-signup').click();
    const signup = page.getByRole('dialog', { name: /sign.?up/i });
    await expect(signup).toBeVisible();
    await signup.getByRole('button', { name: /^close$/i }).click();
    await expect(signup).toHaveCount(0);
  });

  // contract-test: supporting surface=gui.web assertions=apps.anonymous.cli-equivalent-gate
  test('eligible quick skill shows Signup after its request quote denies the available budget', async ({ page }: { page: any }) => {
    await fixtureSkillDetails(page, {
      app_id: 'web', skill_id: 'search', name: 'Search web',
      primary_fields: ['query'], anonymous_allowed: true,
    });
    await page.route('**/v1/anonymous/free-usage/status?*', (route: any) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ active: true, can_send_text: true }),
    }));
    await page.route('**/v1/anonymous/apps/web/skills/search/availability', (route: any) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ allowed: false, reason: 'daily_limit_reached' }),
    }));
    const dispatched: string[] = [];
    page.on('request', (request: any) => {
      if (request.method() === 'POST' && /\/v1\/anonymous\/apps\/web\/skills\/search(?:\?|$)/.test(request.url())) dispatched.push(request.url());
    });
    await page.goto(getE2EDebugUrl('/#apps/web/search'), { waitUntil: 'domcontentloaded' });
    const form = page.getByTestId('apps-skill-form');
    await expect(form).toBeVisible({ timeout: 30000 });
    const deniedQuote = page.waitForResponse((response: any) =>
      response.url().endsWith('/v1/anonymous/apps/web/skills/search/availability')
      && response.request().method() === 'POST');
    await form.getByRole('textbox', { name: 'Query' }).fill('accessible museums in Berlin');
    const quote = await deniedQuote;
    expect(quote.request().postDataJSON().query).toBe('accessible museums in Berlin');
    await expect(form.getByTestId('apps-skill-signup')).toBeVisible();
    await form.getByRole('textbox', { name: 'Query' }).press('Enter');
    await expect(form.getByTestId('apps-skill-submit')).toHaveCount(0);
    expect(dispatched).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=apps.library.embeds-account-paginated,apps.library.workflows-account-related
  test('Personal app libraries request bounded pages and reset when the app changes', async ({ page }: { page: any }) => {
    test.setTimeout(120000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, () => {}, async () => {});

    const resultQueries: URLSearchParams[] = [];
    const workflowQueries: URLSearchParams[] = [];
    await page.route('**/v1/apps/workspace/results?*', (route: any) => {
      const params = new URL(route.request().url()).searchParams;
      resultQueries.push(params);
      const appId = params.get('app_id');
      const offset = Number(params.get('offset'));
      const items = appId === 'web' ? [{
        embed_id: `web-result-${offset}`, app_id: 'web', skill_id: 'search',
        created_at: 1, status: 'finished',
      }] : [];
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        items, has_more: appId === 'web' && offset === 0, offset, limit: 20,
      }) });
    });
    await page.route('**/v1/workflows?*', (route: any) => {
      const params = new URL(route.request().url()).searchParams;
      if (!params.has('app_id')) return route.continue();
      workflowQueries.push(params);
      const offset = Number(params.get('offset'));
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        workflows: [{ id: `web-workflow-${offset}`, title: `Web workflow ${offset}` }],
        has_more: offset === 0, offset, limit: 20,
      }) });
    });

    await page.goto(getE2EDebugUrl('/#apps/web&tab=embeds'), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('apps-result-open-web-result-0')).toBeVisible({ timeout: 30000 });
    expectPersonalPageQuery(resultQueries.at(-1), 'web', 0);
    await page.getByTestId('apps-next-page').click();
    await expect(page.getByTestId('apps-result-open-web-result-20')).toBeVisible();
    await expect(page.getByTestId('apps-result-open-web-result-0')).toHaveCount(0);
    expectPersonalPageQuery(resultQueries.at(-1), 'web', 20);
    await page.getByTestId('apps-previous-page').click();
    await expect(page.getByTestId('apps-result-open-web-result-0')).toBeVisible();
    expectPersonalPageQuery(resultQueries.at(-1), 'web', 0);

    await page.getByTestId('apps-tab-workflows').click();
    await expect(page.getByTestId('apps-workflows-list').getByText('Web workflow 0')).toBeVisible();
    expectPersonalPageQuery(workflowQueries.at(-1), 'web', 0);
    await page.getByTestId('apps-next-page').click();
    await expect(page.getByTestId('apps-workflows-list').getByText('Web workflow 20')).toBeVisible();
    expectPersonalPageQuery(workflowQueries.at(-1), 'web', 20);

    await page.goto(getE2EDebugUrl('/#apps/health&tab=embeds'), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('apps-results-list')).toBeVisible();
    await expect(page.getByTestId('apps-result-open-web-result-20')).toHaveCount(0);
    await expect(page.getByTestId('apps-next-page')).toBeDisabled();
    expectPersonalPageQuery(resultQueries.at(-1), 'health', 0);
  });

  // contract-test: direct surface=gui.web assertions=apps.library.embeds-account-paginated
  test('an open app library indexes an older chat root after background sync and refreshes without reload', async ({ page }: { page: any }) => {
    test.setTimeout(120000);
    expect(getTestAccount().email, 'CI must provide an authenticated test account').toBeTruthy();
    let clientSocket: any;
    await page.routeWebSocket(/\/v1\/ws(?:\?|$)/, (socket: any) => {
      clientSocket = socket;
      socket.connectToServer();
    });
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, () => {}, async () => {});
    const chatId = '9f41750a-b728-4c7d-8ce9-f83cc32b1cc3';
    const embedId = 'd6515197-f14a-4dce-bb89-a9353a4eb9df';
    let indexed = false;
    let batchBody: any;
    await page.route('**/v1/apps/workspace/results/index/batch', async (route: any) => {
      batchBody = route.request().postDataJSON();
      indexed = true;
      await route.fulfill({ json: { indexed: 1, received: batchBody.items.length } });
    });
    await page.route('**/v1/apps/workspace/results?*', (route: any) => route.fulfill({ json: {
      items: indexed ? [{ embed_id: embedId, app_id: 'web', skill_id: 'search', created_at: 1, status: 'finished' }] : [],
      has_more: false, offset: 0, limit: 20,
    } }));
    await page.goto(getE2EDebugUrl('/#apps/web&tab=embeds'), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('apps-results-list')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId(`apps-result-open-${embedId}`)).toHaveCount(0);
    const chatHash = await page.evaluate(async ({ chatId, embedId }: { chatId: string; embedId: string }) => {
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(chatId))))
        .map(value => value.toString(16).padStart(2, '0')).join('');
      const db = await new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open('chats_db');
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      try {
        await new Promise<void>((resolve, reject) => {
          const transaction = db.transaction(['chats', 'embeds'], 'readwrite');
          transaction.objectStore('chats').put({ chat_id: chatId, team_id: null, encrypted_title: null,
            messages_v: 0, title_v: 0, created_at: 1, updated_at: 1 });
          transaction.objectStore('embeds').put({ contentRef: `embed:${embedId}`, embed_id: embedId,
            type: 'app-skill-use', app_id: 'web', skill_id: 'search', hashed_chat_id: hash,
            encrypted_content: 'opaque-legacy-ciphertext-fixture', status: 'finished', createdAt: 1, updatedAt: 1 });
          transaction.oncomplete = () => resolve();
          transaction.onerror = () => reject(transaction.error);
          transaction.onabort = () => reject(transaction.error);
        });
      } finally { db.close(); }
      return hash;
    }, { chatId, embedId });
    await expect.poll(() => Boolean(clientSocket)).toBe(true);
    // Exercise the real bulk-sync notification after an empty library scan.
    // The second opaque row makes the normal sync handler commit a batch;
    // classification finds the older app root already present in local storage.
    clientSocket.send(JSON.stringify({ type: 'background_message_sync', payload: {
      batch_number: 1, is_last_batch: true, chats: [], team_id: null, embed_keys: [],
      embeds: [{ embed_id: '3938dc8a-f2cd-4d4c-8ca5-f8fe0d6ad4bc',
        encrypted_type: 'Zml4dHVyZQ==', encrypted_content: 'Zml4dHVyZQ==',
        hashed_chat_id: chatHash, status: 'finished', created_at: 1, updated_at: 1 }],
    } }));
    await expect(page.getByTestId(`apps-result-open-${embedId}`)).toBeVisible({ timeout: 30000 });
    expect(batchBody.expected_user_id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(batchBody.team_id).toBeNull();
    expect(batchBody.items.length).toBeLessThanOrEqual(50);
    expect(batchBody.items).toContainEqual({ embed_id: embedId, chat_id: chatId, app_id: 'web', skill_id: 'search' });
    await expect(page.getByTestId('apps-next-page')).toBeDisabled();
  });

  // contract-test: direct surface=gui.web assertions=apps.execution.direct-shared-contract,apps.results.web-retained-graph
  // contract-test: direct surface=rest_api assertions=apps.results.web-retained-graph,apps.library.embeds-account-paginated
  test('one Web search retains all 25 children after leaving its form and reopens after reload', async ({ page }: { page: any }) => {
    test.setTimeout(120000);
    expect(getTestAccount().email, 'CI must provide its existing authenticated test account').toBeTruthy();
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, () => {}, async () => {});
    await fixtureSkillDetails(page, {
      app_id: 'web', skill_id: 'search', name: 'Search web',
      primary_fields: ['query'], anonymous_allowed: false, requestEnvelope: true,
    });

    const marker = `apps-retention-${Date.now()}`;
    const query = `Accessible museums ${marker}`;
    const results = Array.from({ length: 25 }, (_, index) => ({
      type: 'search_result',
      title: `Fixture page ${index + 1} ${marker}`,
      url: `https://example.test/apps/${marker}/${index + 1}`,
      description: `Safe fixture result ${index + 1} for ${marker}`,
    }));
    let skillPosts = 0;
    const chatPosts: string[] = [];
    const savedBodies: Array<Record<string, any>> = [];
    page.on('request', (request: any) => {
      if (request.method() !== 'POST') return;
      const path = new URL(request.url()).pathname;
      if (path === '/v1/apps/web/skills/search') skillPosts += 1;
      if (/^\/v1\/(?:chats|ai)(?:\/|$)/.test(path)) chatPosts.push(path);
      if (path === '/v1/apps/workspace/results') savedBodies.push(request.postDataJSON());
    });
    let releaseSkill!: () => void;
    const skillGate = new Promise<void>(resolve => { releaseSkill = resolve; });
    await page.route('**/v1/apps/web/skills/search', async (route: any) => {
      expect(route.request().method()).toBe('POST');
      expect(route.request().postDataJSON().requests[0].query).toBe(query);
      await skillGate;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        success: true, data: {
          provider: 'Fixture Search',
          results: [{ id: 'request-1', results }],
        },
      }) });
    });

    await page.goto(getE2EDebugUrl('/#apps/web/search'), { waitUntil: 'domcontentloaded' });
    const form = page.getByTestId('apps-skill-form');
    await expect(form).toBeVisible({ timeout: 30000 });
    await form.getByRole('textbox', { name: 'Query' }).fill(query);
    const finalSave = page.waitForResponse((response: any) => {
      if (response.request().method() !== 'POST' || new URL(response.url()).pathname !== '/v1/apps/workspace/results') return false;
      return response.request().postDataJSON()?.embeds?.length === 26;
    });
    const skillRequest = page.waitForRequest((request: any) => request.method() === 'POST'
      && new URL(request.url()).pathname === '/v1/apps/web/skills/search');
    await form.getByTestId('apps-skill-submit').click();
    await skillRequest;
    await page.getByTestId('apps-detail-close').click();
    await expect.poll(() => appHash(page)).toBe('#apps/web');
    releaseSkill();
    const saved = await finalSave;
    expect(saved.ok(), 'the finished encrypted parent and children must be durable').toBe(true);
    const body = saved.request().postDataJSON();
    const rootId = body.root_embed_id;
    expect(rootId).toMatch(/^[0-9a-f-]{36}$/i);
    expect(skillPosts).toBe(1);
    expect(chatPosts).toEqual([]);
    expect(savedBodies).toHaveLength(2); // Processing parent, then finished parent plus children.
    expect(savedBodies[0].embeds).toHaveLength(1);
    expect(body.embeds).toHaveLength(26);
    const root = body.embeds.find((row: any) => row.embed_id === rootId);
    expect(root?.embed_ids).toHaveLength(25);
    expect(new Set(root?.embed_ids).size).toBe(25);
    // The final child reaches IDB after the complete graph is hydrated. A
    // completed request must preserve the user's newer app-level navigation.
    await page.waitForFunction(async (childId: string) => {
      const db = await new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open('chats_db');
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      try {
        return await new Promise<boolean>((resolve, reject) => {
          const request = db.transaction('embeds').objectStore('embeds').get(`embed:${childId}`);
          request.onsuccess = () => resolve(request.result?.status === 'finished');
          request.onerror = () => reject(request.error);
        });
      } finally { db.close(); }
    }, root.embed_ids.at(-1));
    expect(appHash(page)).toBe('#apps/web');
    expect(body.embeds.filter((row: any) => row.parent_embed_id === rootId)).toHaveLength(25);
    expect(typeof body.encrypted_embed_key).toBe('string');
    expect(body.encrypted_embed_key.length).toBeGreaterThan(40);
    for (const write of savedBodies) {
      const serialized = JSON.stringify(write);
      expect(serialized).not.toContain(query);
      expect(serialized).not.toContain(marker);
      for (const row of write.embeds) {
        expect(row.encrypted_content).toMatch(/^[A-Za-z0-9+/]+=*$/);
        expect(row.encrypted_type).toMatch(/^[A-Za-z0-9+/]+=*$/);
      }
    }

    const api = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
    const detail = await page.request.get(`${api}/v1/apps/workspace/results/${rootId}`);
    expect(detail.ok()).toBe(true);
    const persisted = await detail.json();
    expect(persisted.root.embed_id).toBe(rootId);
    expect(persisted.root.embed_ids).toHaveLength(25);
    expect(persisted.children).toHaveLength(25);
    expect(JSON.stringify(persisted)).not.toContain(marker);
    const library = await page.request.get(`${api}/v1/apps/workspace/results?app_id=web&offset=0&limit=50`);
    expect(library.ok()).toBe(true);
    const listed = await library.json();
    expect(listed.items.some((item: any) => item.embed_id === rootId && item.app_id === 'web')).toBe(true);

    await page.goto(getE2EDebugUrl('/#apps/web&tab=embeds'), { waitUntil: 'domcontentloaded' });
    await page.reload({ waitUntil: 'domcontentloaded' });
    const card = page.getByTestId(`apps-result-open-${rootId}`);
    await expect(card).toBeVisible({ timeout: 30000 });
    await expect(card).toContainText(query);
    for (const childId of root.embed_ids) await expect(page.getByTestId(`apps-result-open-${childId}`)).toHaveCount(0);
    await card.getByTestId('embed-preview').click();
    await expect(page.getByTestId('apps-result-fullscreen')).toBeVisible();
    const grid = page.getByTestId('apps-result-fullscreen').getByTestId('search-template-grid');
    await expect(grid.getByTestId('embed-preview')).toHaveCount(25, { timeout: 30000 });
    await expect(grid).toContainText(`Fixture page 25 ${marker}`);
  });
});
