// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

import type { Locator, Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { waitForComponentPreview } from '../helpers/component-preview';

const { expect, test } = require('../helpers/cookie-audit');

const preview = (component: 'Header' | 'apps/AppsWorkspace' | 'apps/AppsResultFullscreen', width: number, variant?: string) =>
  `/dev/preview/${component}?${new URLSearchParams({
    theme: 'light', background: '#dbeafe', width: String(width), chrome: '0',
    ...(variant ? { variant } : {}),
  })}`;

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const width = await page.getByTestId('component-preview-viewport').evaluate(element => ({
    scroll: element.scrollWidth, client: element.clientWidth,
  }));
  expect(width.scroll).toBeLessThanOrEqual(width.client + 2);
}

async function expectContainedInPreview(page: Page, locator: Locator): Promise<void> {
  const viewport = await page.getByTestId('component-preview-viewport').boundingBox();
  const element = await locator.boundingBox();
  expect(viewport).not.toBeNull();
  expect(element).not.toBeNull();
  expect(element!.x).toBeGreaterThanOrEqual(viewport!.x - 1);
  expect(element!.x + element!.width).toBeLessThanOrEqual(viewport!.x + viewport!.width + 1);
}

async function fixturePublicApps(page: Page): Promise<void> {
  await page.route('**/v1/features/availability', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ disabled: [] }),
  }));
  await page.route('**/v1/apps/web/skills/search/details', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      app_id: 'web', skill_id: 'search', slug: 'search', name: 'Search the web',
      name_translation_key: 'web.search', description: 'Find public web pages.',
      description_translation_key: 'web.search.description', icon_image: 'search.svg',
      input_schema: { type: 'object', properties: {
        query: { type: 'string', title: 'Search query', minLength: 1, 'x-ui': { basic: true } },
        count: { type: 'integer', title: 'Results', minimum: 1, maximum: 20, default: 10 },
      }, required: ['query'] },
      primary_fields: ['query'], defaults: { count: 10 }, pricing: { fixed: 1 },
      providers: [], models: [], anonymous_allowed: false, execution_available: true,
      unavailable_reason: null, execution_mode: 'sync',
    }),
  }));
}

async function expectLoadedAppGlyph(card: Locator, svgName: string): Promise<void> {
  const glyph = card.getByTestId('apps-card-glyph');
  await expect(glyph).toBeVisible();
  await expect.poll(() => glyph.evaluate(image => {
    const img = image as HTMLImageElement;
    return img.complete && img.naturalWidth > 0 && img.naturalHeight > 0;
  })).toBe(true);
  const expectedSvg = readFileSync(resolve(__dirname, `../../../../packages/ui/static/icons/${svgName}.svg`), 'utf8');
  const expectedPath = expectedSvg.match(/<path d="([^"]+)"/)?.[1];
  expect(expectedPath).toBeTruthy();
  const actualPath = await glyph.evaluate(async image => {
    const img = image as HTMLImageElement;
    const svg = await (await fetch(img.currentSrc)).text();
    return new DOMParser().parseFromString(svg, 'image/svg+xml').querySelector('path')?.getAttribute('d');
  });
  expect(actualPath).toBe(expectedPath);
}

async function expectLoadedMaskGlyph(glyph: Locator, svgName: string): Promise<void> {
  await expect(glyph).toBeVisible();
  const expectedSvg = readFileSync(resolve(__dirname, `../../../../packages/ui/static/icons/${svgName}.svg`), 'utf8');
  const expectedPath = expectedSvg.match(/<path d="([^"]+)"/)?.[1];
  expect(expectedPath).toBeTruthy();
  const actualPath = await glyph.evaluate(async element => {
    const mask = getComputedStyle(element).maskImage;
    // Vite inlines this SVG as a data URL whose clip-path contains `url(...)`.
    // Match the outer CSS url wrapper, including the embedded closing parenthesis.
    const url = mask.match(/^url\((['"])(.*)\1\)$/)?.[2];
    if (!url) return null;
    const svg = await (await fetch(url)).text();
    return new DOMParser().parseFromString(svg, 'image/svg+xml').querySelector('path')?.getAttribute('d');
  });
  expect(actualPath).toBe(expectedPath);
}

async function expectLoadedSkillHeroGlyph(page: Page, svgName: string): Promise<void> {
  await expectLoadedMaskGlyph(page.getByTestId('apps-hero-icon').locator(`[data-skill-icon="${svgName}"]`), svgName);
}

async function attachWorkspaceScreenshot(page: Page, name: string): Promise<void> {
  const path = test.info().outputPath(name);
  await page.screenshot({ path, animations: 'disabled' });
  await test.info().attach(name, { path, contentType: 'image/png' });
}

test.describe('Apps bare component previews', () => {
  // contract-test: supporting surface=gui.web assertions=apps.results.web-retained-graph,apps.presentation.shared-detail-and-recency
  test('keeps an unavailable result closeable when its renderer is missing', async ({ page }: { page: Page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(preview('apps/AppsResultFullscreen', 390, 'missingRegistry'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await expect(page.getByRole('status')).toContainText('This result could not be opened.');
    const closed = page.evaluate(() => new Promise<void>(resolve => window.addEventListener('apps-result-preview-close', () => resolve(), { once: true })));
    await page.getByTestId('embed-minimize').click();
    await closed;
  });

  // contract-test: supporting surface=gui.web assertions=apps.results.web-retained-graph,apps.presentation.shared-detail-and-recency
  test('keeps an unavailable result closeable when its component loader returns null', async ({ page }: { page: Page }) => {
    await page.route('**/WebSearchEmbedFullscreen.svelte*', route => route.fulfill({ contentType: 'application/javascript', body: 'export default null;' }));
    await page.setViewportSize({ width: 1180, height: 844 });
    await page.goto(preview('apps/AppsResultFullscreen', 1100), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await expect(page.getByText('This result could not be opened.', { exact: true }).first()).toBeVisible();
    const closed = page.evaluate(() => new Promise<void>(resolve => window.addEventListener('apps-result-preview-close', () => resolve(), { once: true })));
    await page.getByTestId('embed-minimize').click();
    await closed;
  });
  // contract-test: direct surface=gui.web assertions=apps.discovery.public-catalog,workspace-shell.nav.released-surfaces-visible
  test('shows the fifth Apps tab for signed-in desktop and a public Apps choice on phone', async ({ page }: { page: Page }) => {
    await fixturePublicApps(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(preview('Header', 1280, 'signedIn'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    const nav = page.locator('.icon-tab-bar');
    const apps = page.getByTestId('apps-nav-link');
    await expect(nav.getByRole('link')).toHaveCount(5);
    await expect(apps).toBeVisible();
    await expect(apps).toHaveAttribute('href', '/#apps');
    // Compare the SVG path itself because Vite may inline its asset URL.
    const expectedIcon = readFileSync(resolve(__dirname, '../../../../packages/ui/static/icons/app.svg'), 'utf8');
    const actualIconPath = await apps.locator('.app-icon').evaluate(async element => {
      const mask = getComputedStyle(element).maskImage;
      const url = mask.match(/^url\(["']?(.*?)["']?\)$/)?.[1];
      if (!url) return null;
      const svg = await (await fetch(url)).text();
      return new DOMParser().parseFromString(svg, 'image/svg+xml').querySelector('path')?.getAttribute('d');
    });
    expect(actualIconPath).toBe(expectedIcon.match(/<path d="([^"]+)"/)?.[1]);
    await apps.focus();
    await expect(apps).toBeFocused();
    await apps.hover();
    await expect(page.locator('.icon-tab-hover-pill.visible')).toBeVisible();
    await expectNoHorizontalOverflow(page);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(preview('Header', 390), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    const mobileSelect = page.getByTestId('workspace-mobile-select');
    await expect(mobileSelect).toBeVisible();
    await expect(mobileSelect.locator('option')).toHaveCount(2);
    await expect(mobileSelect.locator('option[value="/#apps"]')).toHaveText(/Apps/i);
    await expectNoHorizontalOverflow(page);
  });

  // contract-test: direct surface=gui.web assertions=apps.discovery.public-catalog,apps.presentation.shared-detail-and-recency
  test('renders a public home card and forwards its navigation at laptop and phone widths', async ({ page }: { page: Page }) => {
    await fixturePublicApps(page);
    for (const width of [1180, 390]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(preview('apps/AppsWorkspace', width), { waitUntil: 'domcontentloaded' });
      await waitForComponentPreview(page);
      await expect(page.getByTestId('apps-workspace')).toBeVisible();
      await expect(page.getByTestId('apps-daily-inspiration-area').getByTestId('daily-inspiration-phrase')).toBeVisible();
      await expect(page.getByTestId('daily-inspiration-cta-text')).toHaveText(/^(Click|Tap) to use app skill$/);
      await expect(page.getByTestId('report-issue-button')).toBeVisible();
      await expect(page.getByRole('heading', { name: 'What app do you want to use?' })).toBeVisible();
      const banner = await page.getByTestId('apps-daily-inspiration-area').boundingBox();
      const greeting = await page.getByTestId('apps-workspace-home').locator('.workspace-eyebrow').boundingBox();
      const heading = await page.getByRole('heading', { name: 'What app do you want to use?' }).boundingBox();
      expect(greeting!.y).toBeGreaterThanOrEqual(banner!.y + banner!.height);
      expect(heading!.y).toBeGreaterThanOrEqual(banner!.y + banner!.height);
      await expect(page.getByTestId('apps-quick-use-affordance')).toBeVisible();
      const chooser = await page.getByTestId('apps-quick-use-affordance').boundingBox();
      for (const link of [page.getByTestId('apps-show-all'), page.getByTestId('apps-search')]) {
        await expect(link).toBeVisible();
        await expectContainedInPreview(page, link);
        const bounds = await link.boundingBox();
        expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(chooser!.y - 1);
        expect(await link.evaluate(element => {
          const rect = element.getBoundingClientRect();
          const top = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
          return top === element || element.contains(top);
        })).toBe(true);
      }
      await expect(page.getByTestId('apps-app-card').first()).toBeVisible();
      await expectLoadedAppGlyph(page.locator('[data-testid="apps-app-card"][data-app-id="web"]'), 'web');
      await expectLoadedAppGlyph(page.locator('[data-testid="apps-app-card"][data-app-id="health"]'), 'heart');
      await attachWorkspaceScreenshot(page, `apps-home-${width}.png`);
      const inspiredSkill = page.evaluate(() => new Promise<string>(resolve =>
        window.addEventListener('apps-preview-navigate', event => resolve((event as CustomEvent<string>).detail), { once: true })));
      await page.getByTestId('daily-inspiration-phrase').click();
      expect(await inspiredSkill).toMatch(/^#apps\/(web\/search|weather\/forecast)$/);
      const chooseSkill = page.evaluate(() => new Promise<string>(resolve =>
        window.addEventListener('apps-preview-navigate', event => resolve((event as CustomEvent<string>).detail), { once: true })));
      await page.getByTestId('apps-quick-use-affordance').click();
      expect(await chooseSkill).toBe('#apps/all&filter=skills');
      const navigated = page.evaluate(() => new Promise<string>(resolve =>
        window.addEventListener('apps-preview-navigate', event => resolve((event as CustomEvent<string>).detail), { once: true })));
      await page.getByTestId('apps-app-card').first().click();
      expect(await navigated).toMatch(/^#apps\/[a-z0-9-]+$/);
      await expectNoHorizontalOverflow(page);
    }
  });

  // contract-test: direct surface=gui.web assertions=apps.presentation.shared-detail-and-recency,apps.navigation.hash-and-forwarding
  test('shows app fullscreen tabs, icon and parent close route at laptop and phone widths', async ({ page }: { page: Page }) => {
    await fixturePublicApps(page);
    for (const width of [1180, 390]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(preview('apps/AppsWorkspace', width === 1180 ? 1100 : width, 'app'), { waitUntil: 'domcontentloaded' });
      await waitForComponentPreview(page);
      const fullscreen = page.getByTestId('apps-detail-fullscreen');
      await expect(fullscreen).toBeVisible();
      await expect(page.getByTestId('apps-hero-category')).toHaveText('App');
      await expect(page.getByTestId('apps-hero-icon')).toBeVisible();
      await expect(page.getByTestId('apps-hero-stats')).toContainText(/\d+ skills/);
      await expect(page.getByTestId('apps-tab-overview')).toBeVisible();
      await expect(page.getByTestId('apps-tab-embeds')).toBeVisible();
      await expect(page.getByTestId('apps-tab-workflows')).toBeVisible();
      await expect(page.getByTestId('apps-tab-focus_modes')).toBeVisible();
      await expect(page.getByTestId('apps-tab-settings_memories')).toBeVisible();
      await expect(page.getByTestId('apps-detail-tabs').getByRole('tab')).toHaveCount(5);
      await expectLoadedMaskGlyph(page.getByTestId('apps-tab-overview').locator('.tab-icon'), 'app');
      await expectLoadedMaskGlyph(page.getByTestId('apps-tab-focus_modes').locator('.tab-icon'), 'search');
      const tabBar = await page.getByTestId('apps-detail-tabs').boundingBox();
      for (const tab of await page.getByTestId('apps-detail-tabs').getByRole('tab').all()) {
        await expect(tab).toBeVisible();
        const bounds = await tab.boundingBox();
        expect(bounds!.x).toBeGreaterThanOrEqual(tabBar!.x - 1);
        expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(tabBar!.x + tabBar!.width + 1);
        await expectContainedInPreview(page, tab);
      }
      await expect(page.getByTestId('apps-tab-overview').locator('.tab-icon')).toBeVisible();
      const hero = await fullscreen.locator('.embed-header').boundingBox();
      const innerCard = await page.getByTestId('apps-detail-card').boundingBox();
      const floatingTabs = await page.getByTestId('apps-detail-tabs').boundingBox();
      expect(hero?.height).toBeGreaterThanOrEqual(width === 1180 ? 345 : 285);
      expect(floatingTabs?.y).toBeLessThan(innerCard?.y ?? 0);
      expect(floatingTabs?.width).toBeLessThanOrEqual(320);
      await expectContainedInPreview(page, page.getByTestId('apps-hero-identity'));
      await expectContainedInPreview(page, page.getByTestId('apps-hero-icon'));
      const category = await page.getByTestId('apps-hero-category').boundingBox();
      const heroIcon = await page.getByTestId('apps-hero-icon').boundingBox();
      expect((category?.y ?? 0) + (category?.height ?? 0)).toBeLessThan((heroIcon?.y ?? 0) - 2);
      await expectContainedInPreview(page, page.getByTestId('apps-detail-card'));
      await expectContainedInPreview(page, page.getByTestId('apps-detail-tabs'));
      await expect(page.getByRole('heading', { name: 'Which app skill do you want to use?' })).toBeVisible();
      await expectNoHorizontalOverflow(page);
      await attachWorkspaceScreenshot(page, `app-detail-${width}.png`);
    }
    const navigated = page.evaluate(() => new Promise<string>(resolve =>
      window.addEventListener('apps-preview-navigate', event => resolve((event as CustomEvent<string>).detail), { once: true })));
    await page.getByTestId('apps-detail-close').click();
    expect(await navigated).toBe('#apps');
    await page.goto(preview('apps/AppsWorkspace', 390, 'appFocus'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await expect(page.getByTestId('settings-focus-cards-scroll')).toBeVisible();
    await expect(page.getByTestId('settings-skill-cards-scroll')).toHaveCount(0);
    const focusRoute = page.evaluate(() => new Promise<string>(resolve =>
      window.addEventListener('apps-preview-navigate', event => resolve((event as CustomEvent<string>).detail), { once: true })));
    await page.getByTestId('apps-tab-settings_memories').click();
    expect(await focusRoute).toBe('#apps/health&tab=settings_memories');
    await page.goto(preview('apps/AppsWorkspace', 390, 'appMemory'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await expect(page.getByTestId('settings-memory-cards-scroll')).toBeVisible();
    await expect(page.getByTestId('settings-skill-cards-scroll')).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=apps.forms.metadata-driven,apps.presentation.shared-detail-and-recency
  test('renders a skill form and focuses its main input from Use skill', async ({ page }: { page: Page }) => {
    await fixturePublicApps(page);
    await page.setViewportSize({ width: 1180, height: 844 });
    await page.goto(preview('apps/AppsWorkspace', 1100, 'skill'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    const form = page.getByTestId('apps-skill-form');
    await expect(form).toBeVisible();
    await expect(page.getByTestId('apps-hero-category')).toContainText('Web');
    await expect(page.getByTestId('apps-hero-providers')).toContainText('Brave');
    await expect(page.getByTestId('apps-use-skill')).toBeVisible();
    await expectLoadedSkillHeroGlyph(page, 'search');
    await expect(page.getByTestId('apps-detail-tabs').getByRole('tab')).toHaveCount(3);
    await expectContainedInPreview(page, page.getByTestId('apps-hero-identity'));
    await expectContainedInPreview(page, page.getByTestId('apps-detail-card'));
    await expectContainedInPreview(page, page.getByTestId('apps-detail-tabs'));
    await expectContainedInPreview(page, page.getByTestId('apps-skill-primary-fields').locator('input'));
    await expectContainedInPreview(page, page.getByTestId('apps-skill-settings-toggle'));
    await expectContainedInPreview(page, page.getByTestId('apps-skill-signup'));
    await expect(page.getByTestId('apps-skill-primary-fields').locator('input')).toHaveCount(1);
    await attachWorkspaceScreenshot(page, 'skill-detail-1180.png');
    await page.getByTestId('apps-use-skill').click();
    await expect(form.locator('input').first()).toBeFocused();
    await expect(page.locator('.skill-form-area.highlight')).toBeVisible();
    await page.getByTestId('apps-skill-settings-toggle').click();
    await expect(page.getByTestId('apps-skill-settings')).toBeVisible();
    await page.evaluate(() => {
      (window as typeof window & { appsOpenedExample?: string[] }).appsOpenedExample = undefined;
      window.open = ((url, target, features) => {
        (window as typeof window & { appsOpenedExample?: string[] }).appsOpenedExample = [String(url), String(target), String(features)];
        return null;
      }) as typeof window.open;
    });
    await page.getByTestId('apps-skill-chat-example').first().click();
    const opened = await page.evaluate(() => (window as typeof window & { appsOpenedExample?: string[] }).appsOpenedExample);
    expect(opened?.[0]).toMatch(/^\/#new-message=.+/);
    expect(opened?.slice(1)).toEqual(['_blank', 'noopener,noreferrer']);
    await expectNoHorizontalOverflow(page);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(preview('apps/AppsWorkspace', 390, 'skill'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await expect(page.getByTestId('apps-skill-form')).toBeVisible();
    await expect(page.getByTestId('apps-use-skill')).toBeVisible();
    await expectContainedInPreview(page, page.getByTestId('apps-hero-identity'));
    await expectContainedInPreview(page, page.getByTestId('apps-detail-card'));
    await expectContainedInPreview(page, page.getByTestId('apps-detail-tabs'));
    await expectContainedInPreview(page, page.getByTestId('apps-skill-primary-fields').locator('input'));
    await expectContainedInPreview(page, page.getByTestId('apps-skill-settings-toggle'));
    await expectContainedInPreview(page, page.getByTestId('apps-skill-signup'));
    const category = await page.getByTestId('apps-hero-category').boundingBox();
    const heroIcon = await page.getByTestId('apps-hero-icon').boundingBox();
    expect((category?.y ?? 0) + (category?.height ?? 0)).toBeLessThan((heroIcon?.y ?? 0) - 2);
    await expectNoHorizontalOverflow(page);
    await attachWorkspaceScreenshot(page, 'skill-detail-390.png');
  });

  // contract-test: direct surface=gui.web assertions=apps.library.workflows-account-related
  test('switching Personal and Team clears rows and cursors before stale requests finish', async ({ page }: { page: Page }) => {
    await fixturePublicApps(page);
    const queries: Array<{ appId: string | null; teamId: string | null; offset: number; limit: number }> = [];
    let releasePersonalLate!: () => void;
    const personalLateGate = new Promise<void>(resolve => { releasePersonalLate = resolve; });
    let releaseTeamFirst!: () => void;
    const teamFirstGate = new Promise<void>(resolve => { releaseTeamFirst = resolve; });
    await page.route('**/v1/workflows?*', async route => {
      const url = new URL(route.request().url());
      const appId = url.searchParams.get('app_id');
      if (!appId) return route.continue();
      const teamId = url.searchParams.get('team_id');
      const offset = Number(url.searchParams.get('offset'));
      const limit = Number(url.searchParams.get('limit'));
      queries.push({ appId, teamId, offset, limit });
      if (!teamId && offset === 40) await personalLateGate;
      if (teamId && offset === 0) await teamFirstGate;
      const scope = teamId ? 'Team' : 'Personal';
      await route.fulfill({ json: {
        workflows: [{ id: `${scope.toLowerCase()}-${offset}`, title: `${scope} workflow ${offset}` }],
        has_more: !teamId && offset < 40, offset, limit,
      } });
    });
    await page.goto(preview('apps/AppsWorkspace', 1100, 'teamLibrary'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    expect(await page.evaluate(() => (window as Window & {
      appsPreviewAccountSnapshot?: () => unknown;
    }).appsPreviewAccountSnapshot?.())).toEqual({ isAuthenticated: true, userId: 'preview-user', teamId: null });
    await expect.poll(() => queries).toContainEqual({ appId: 'web', teamId: null, offset: 0, limit: 20 });
    const rows = page.getByTestId('apps-workflows-list');
    await expect(rows.getByText('Personal workflow 0')).toBeVisible();
    await page.getByTestId('apps-next-page').click();
    await expect(rows.getByText('Personal workflow 20')).toBeVisible();
    expect(queries.at(-1)).toEqual({ appId: 'web', teamId: null, offset: 20, limit: 20 });

    const firstTeamRequest = page.waitForRequest(request => {
      const url = new URL(request.url());
      return url.pathname.endsWith('/v1/workflows') && url.searchParams.get('team_id') === 'preview-studio';
    });
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('apps-preview-set-team', { detail: 'preview-studio' })));
    await firstTeamRequest;
    await expect(rows.getByText(/Personal workflow/)).toHaveCount(0);
    expect(queries.at(-1)).toEqual({ appId: 'web', teamId: 'preview-studio', offset: 0, limit: 20 });
    releaseTeamFirst();
    await expect(rows.getByText('Team workflow 0')).toBeVisible();
    await expect(page.getByTestId('apps-previous-page')).toBeDisabled();
    await expect(page.getByTestId('apps-next-page')).toBeDisabled();

    await page.evaluate(() => window.dispatchEvent(new CustomEvent('apps-preview-set-team', { detail: null })));
    await expect(rows.getByText(/Team workflow/)).toHaveCount(0);
    await expect(rows.getByText('Personal workflow 0')).toBeVisible();
    await expect(page.getByTestId('apps-previous-page')).toBeDisabled();
    expect(queries.at(-1)).toEqual({ appId: 'web', teamId: null, offset: 0, limit: 20 });
    await page.getByTestId('apps-next-page').click();
    await expect(rows.getByText('Personal workflow 20')).toBeVisible();

    const latePersonal = page.waitForRequest(request => {
      const url = new URL(request.url());
      return url.pathname.endsWith('/v1/workflows') && url.searchParams.get('offset') === '40';
    });
    await page.getByTestId('apps-next-page').click();
    await latePersonal;
    const teamRequest = page.waitForRequest(request => {
      const url = new URL(request.url());
      return url.pathname.endsWith('/v1/workflows') && url.searchParams.get('team_id') === 'preview-studio';
    });
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('apps-preview-set-team', { detail: 'preview-studio' })));
    await expect(rows.getByText(/Personal workflow/)).toHaveCount(0);
    await teamRequest;
    expect(queries.at(-1)).toEqual({ appId: 'web', teamId: 'preview-studio', offset: 0, limit: 20 });
    await expect(rows.getByText('Team workflow 0')).toBeVisible();
    await expect(page.getByTestId('apps-previous-page')).toBeDisabled();
    const staleResponse = page.waitForResponse(response => {
      const url = new URL(response.url());
      return url.pathname.endsWith('/v1/workflows') && url.searchParams.get('offset') === '40';
    });
    releasePersonalLate();
    await staleResponse;
    await expect(rows.getByText('Team workflow 0')).toBeVisible();
    await expect(rows.getByText(/Personal workflow/)).toHaveCount(0);
    await expect(page.getByTestId('apps-next-page')).toBeDisabled();
  });
});
