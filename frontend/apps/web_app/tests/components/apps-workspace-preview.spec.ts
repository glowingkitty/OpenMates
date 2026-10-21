// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

import type { Locator, Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { ALL_EXAMPLE_CHATS } from '../../../../packages/ui/src/demo_chats/exampleChatData';
import { waitForComponentPreview } from '../helpers/component-preview';
import { assertGuestHeaderControlsSeparated } from '../helpers/header-layout';

const { expect, test } = require('../helpers/cookie-audit');

const preview = (component: 'Header' | 'apps/AppsWorkspace' | 'apps/AppsResultFullscreen' | 'apps/AppsInlineResults' | 'apps/AppsEmbedPreview' | 'settings/AppDetails', width: number, variant?: string) =>
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
  await page.route('**/v1/apps/workspace/public/**',route=>route.fulfill({json:{recommendations:[],cta:null}}));
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

async function expectPreviewFailure(page: Page, message: string): Promise<void> {
  await expect.poll(() => page.evaluate(() => (window as Window & { appsResultPreviewClosed?: number }).appsResultPreviewClosed ?? 0)).toBe(1);
  await expect.poll(() => page.evaluate(() => (window as Window & { appsResultPreviewNotifications?: Array<{ type: string; message: string }> }).appsResultPreviewNotifications ?? [])).toContainEqual({ type: 'error', message });
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByTestId('search-template-grid')).toHaveCount(0);
}

async function expectSettingsDispatch(page: Page, path: string): Promise<void> {
  const opened = page.evaluate(() => new Promise<string>(resolve => window.addEventListener('apps-preview-settings', event => resolve((event as CustomEvent<string>).detail), { once: true })));
  await page.getByTestId('apps-settings-open').click();
  expect(await opened).toBe(path);
  await expect(page.getByTestId('apps-settings')).toHaveCount(0);
}

async function attachWorkspaceScreenshot(page: Page, name: string): Promise<void> {
  const path = test.info().outputPath(name);
  await page.screenshot({ path, animations: 'disabled' });
  await test.info().attach(name, { path, contentType: 'image/png' });
}

test.describe('Apps bare component previews', () => {
  // contract-test: supporting surface=gui.web assertions=apps.results.web-retained-graph,apps.presentation.shared-detail-and-recency
  test('saved native request envelopes supply the regular collection fullscreen query', async ({ page }: { page: Page }) => {
    await page.goto(preview('apps/AppsResultFullscreen', 390, 'legacyRequest'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await expect(page.getByTestId('embed-header-title')).toContainText('Saved native request');
    const closed = page.evaluate(() => new Promise<void>(resolve => window.addEventListener('apps-result-preview-close', () => resolve(), { once: true })));
    await page.getByTestId('embed-minimize').click();
    await closed;
  });
  // contract-test: supporting surface=gui.web assertions=apps.results.web-retained-graph
  test('a saved failed request remains a truthful failure rather than an unavailable empty search', async ({ page }: { page: Page }) => {
    await page.goto(preview('apps/AppsResultFullscreen', 390, 'failedRequest'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await expectPreviewFailure(page, 'The request could not finish. You can try again.');
  });
  // contract-test: supporting surface=gui.web assertions=apps.results.web-retained-graph,apps.presentation.shared-detail-and-recency
  test('inline results use the regular child previews and pass their parent graph when opened', async ({ page }: { page: Page }) => {
    for (const width of [1180, 390]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(preview('apps/AppsInlineResults', width), { waitUntil: 'domcontentloaded' });
      await waitForComponentPreview(page);
      const grid = page.getByTestId('apps-inline-results-grid');
      await expect(grid.getByTestId('embed-preview')).toHaveCount(2);
      await expect(grid).toContainText('Preview page 1');
      await expect(grid).toContainText('Preview page 2');
      const cards = await grid.getByTestId('embed-preview').all();
      const first = await cards[0].boundingBox();
      const second = await cards[1].boundingBox();
      if (width === 1180) {
        expect(second!.x).toBeGreaterThanOrEqual(first!.x + first!.width);
        expect(second!.y).toBeCloseTo(first!.y, 0);
      } else {
        expect(second!.y).toBeGreaterThanOrEqual(first!.y + first!.height);
      }
      await expectNoHorizontalOverflow(page);
      const opened = page.evaluate(() => new Promise(resolve => window.addEventListener('apps-inline-preview-open', event => resolve((event as CustomEvent).detail), { once: true })));
      await grid.getByTestId('embed-preview').first().click();
      expect(await opened).toEqual({ id: '90000000-0000-4000-8000-000000000002', parent: '90000000-0000-4000-8000-000000000001' });
      await attachWorkspaceScreenshot(page, `inline-results-${width}.png`);
    }
    await page.goto(preview('apps/AppsInlineResults', 390, 'empty'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await expect(page.getByRole('status')).toHaveText('No results found.');
    await expect(page.getByTestId('embed-preview')).toHaveCount(0);
  });

  // contract-test: supporting surface=gui.web assertions=apps.library.embeds-account-paginated,apps.presentation.shared-detail-and-recency
  test('saved parent cards use the regular Search preview with query and result count', async ({ page }: { page: Page }) => {
    await page.goto(preview('apps/AppsEmbedPreview', 390), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await expect(page.getByTestId('embed-preview')).toContainText('Preview search');
    await expect(page.getByTestId('embed-preview')).toContainText('2');
    const opened = page.evaluate(() => new Promise(resolve => window.addEventListener('apps-embed-preview-open', resolve, { once: true })));
    await page.getByTestId('embed-preview').click();
    await opened;
  });
  // contract-test: supporting surface=gui.web assertions=apps.results.web-retained-graph,apps.presentation.shared-detail-and-recency
  test('closes a missing renderer and sends its failure to shared notifications', async ({ page }: { page: Page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(preview('apps/AppsResultFullscreen', 390, 'missingRegistry'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await expectPreviewFailure(page, 'This result could not be opened.');
  });

  // contract-test: supporting surface=gui.web assertions=apps.results.web-retained-graph,apps.presentation.shared-detail-and-recency
  test('closes a null renderer and sends its failure to shared notifications', async ({ page }: { page: Page }) => {
    await page.route('**/WebSearchEmbedFullscreen.svelte*', route => route.fulfill({ contentType: 'application/javascript', body: 'export default null;' }));
    await page.setViewportSize({ width: 1180, height: 844 });
    await page.goto(preview('apps/AppsResultFullscreen', 1100), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await expectPreviewFailure(page, 'This result could not be opened.');
  });
  // contract-test: direct surface=gui.web assertions=apps.discovery.public-catalog,workspace-shell.nav.released-surfaces-visible
  test('orders signed-in workspaces with Apps second and keeps the public Apps choice on phone', async ({ page }: { page: Page }) => {
    await fixturePublicApps(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(preview('Header', 1280, 'signedIn'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    const nav = page.locator('.icon-tab-bar');
    const apps = page.getByTestId('apps-nav-link');
    const header = page.getByTestId('global-header');
    const headerBounds = await header.boundingBox();
    expect(headerBounds).not.toBeNull();
    expect(headerBounds!.width).toBeGreaterThanOrEqual(1200);
    expect(headerBounds!.height).toBeLessThanOrEqual(65);
    await expect(nav.getByRole('link')).toHaveCount(5);
    await expect(page.getByTestId('header-login-signup-btn')).toBeHidden();
    expect(await nav.getByRole('link').evaluateAll(links => links.map(link => link.getAttribute('data-testid')))).toEqual([
      'chats-nav-link', 'apps-nav-link', 'projects-nav-link', 'tasks-nav-link', 'workflows-nav-link',
    ]);
    await expect(apps).toBeVisible();
    await expect(apps).toHaveAttribute('href', '/#apps');
    for (const control of [header.getByRole('link', { name: /OpenMates/i }).first(), ...await nav.getByRole('link').all()]) {
      await expect(control).toBeVisible();
      const bounds = await control.boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds!.x).toBeGreaterThanOrEqual(headerBounds!.x);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(headerBounds!.x + headerBounds!.width);
      expect(bounds!.y).toBeGreaterThanOrEqual(headerBounds!.y);
      expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(headerBounds!.y + headerBounds!.height);
    }
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
    await page.goto(preview('Header', 390, 'signedIn'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    const mobileSelect = page.getByTestId('workspace-mobile-select');
    await expect(mobileSelect).toBeVisible();
    expect(await mobileSelect.locator('option').evaluateAll(options => options.map(option => (option as HTMLOptionElement).value))).toEqual([
      '/', '/#apps', '/#projects', '/#tasks', '/#workflows',
    ]);
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(preview('Header', width), { waitUntil: 'domcontentloaded' });
      await waitForComponentPreview(page);
      const selector = page.getByTestId('workspace-mobile-select');
      const login = page.getByTestId('header-login-signup-btn');
      expect(await selector.locator('option').evaluateAll(options => options.map(option => (option as HTMLOptionElement).value))).toEqual([
        '/', '/#apps', '/#workflows',
      ]);
      await expect(selector.locator('option[value="/#apps"]')).toHaveText(/Apps/i);
      await expect(selector.locator('option[value="/#workflows"]')).toHaveText(/Workflows/i);
      await expect(login).toBeVisible();
      await expect(login).toHaveAccessibleName(/Login|Sign\s*up/i);
      await expect(login).toContainText(/Login|Sign\s*up/i);
      await login.focus();
      await expect(login).toBeFocused();
      await assertGuestHeaderControlsSeparated(page);
      await expectContainedInPreview(page, login);
      await expectNoHorizontalOverflow(page);
      await attachWorkspaceScreenshot(page, `guest-header-${width}.png`);
    }
  });

  // contract-test: supporting surface=gui.web assertions=apps.discovery.public-catalog,workspace-shell.nav.released-surfaces-visible
  test('restores separated phone header controls when the guest CTA becomes visible again', async ({ page }: { page: Page }) => {
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(preview('Header', width, 'guestCtaToggle'), { waitUntil: 'domcontentloaded' });
      await waitForComponentPreview(page);
      const login = page.getByTestId('header-login-signup-btn');
      const toggle = page.getByTestId('sidebar-toggle');
      await expect(login).toBeVisible();
      await toggle.click();
      await expect(login).toBeHidden();
      await toggle.click();
      await expect(login).toBeVisible();
      await assertGuestHeaderControlsSeparated(page);
      await expectNoHorizontalOverflow(page);
      await attachWorkspaceScreenshot(page, `restored-guest-header-${width}.png`);
    }
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
      await expect(page.getByTestId('apps-workspace-home').locator('.workspace-eyebrow')).toHaveCount(0);
      await expect(page.getByTestId('apps-workspace-background-icon')).toBeVisible();
      const heading = await page.getByRole('heading', { name: 'What app do you want to use?' }).boundingBox();
      expect(heading!.y).toBeGreaterThanOrEqual(banner!.y + banner!.height);
      await expect(page.getByTestId('apps-workspace-home').getByTestId('workspace-composer-slot')).toHaveCount(0);
      await expect(page.getByTestId('apps-workspace-home').getByRole('textbox')).toHaveCount(0);
      for (const link of [page.getByTestId('apps-show-all'), page.getByTestId('apps-search')]) {
        await expect(link).toBeVisible();
        await expectContainedInPreview(page, link);
        expect(await link.evaluate(element => {
          const rect = element.getBoundingClientRect();
          const top = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
          return top === element || element.contains(top);
        })).toBe(true);
      }
      await expect(page.getByTestId('apps-app-card').first()).toBeVisible();
      const webCard = page.getByTestId('apps-app-card').getByTestId('app-store-card').filter({ has: page.getByTestId('app-card-name').getByText('Web') });
      await expect(webCard).toHaveAttribute('data-app-id', 'web');
      await expect(webCard.getByTestId('app-card-icon')).toBeVisible();
      await expect(webCard.getByTestId('app-card-name')).toHaveCSS('text-align', 'left');
      const iconBounds = await webCard.getByTestId('app-card-icon').boundingBox();
      const nameBounds = await webCard.getByTestId('app-card-name').boundingBox();
      expect(iconBounds!.x + iconBounds!.width).toBeLessThan(nameBounds!.x);
      await expect(page.getByTestId('apps-app-card').getByTestId('app-store-card').filter({ has: page.getByTestId('app-card-name').getByText('Health') })).toHaveAttribute('data-app-id', 'health');
      const webCardBounds = await webCard.boundingBox();
      expect(webCardBounds).not.toBeNull();
      if (width === 390) {
        expect(webCardBounds!.width).toBeGreaterThanOrEqual(275);
        expect(webCardBounds!.width).toBeLessThanOrEqual(285);
        expect(webCardBounds!.height).toBeGreaterThanOrEqual(42);
        expect(webCardBounds!.height).toBeLessThanOrEqual(46);
        await expect(webCard.getByTestId('app-card-name')).toBeVisible();
        await expect(webCard.getByTestId('app-card-description')).toHaveCount(0);
        await expect(webCard).toHaveText('Web');
      } else {
        expect(webCardBounds!.height).toBeGreaterThanOrEqual(125);
        await expect(webCard.getByTestId('app-card-description')).toBeVisible();
        await expect(webCard.getByTestId('app-card-description')).toHaveCSS('text-align', 'left');
      }
      await attachWorkspaceScreenshot(page, `apps-home-${width}.png`);
      const inspiredSkill = page.evaluate(() => new Promise<string>(resolve =>
        window.addEventListener('apps-preview-navigate', event => resolve((event as CustomEvent<string>).detail), { once: true })));
      await page.getByTestId('daily-inspiration-phrase').click();
      expect(await inspiredSkill).toMatch(/^#apps\/(web\/search|weather\/forecast)$/);
      const navigated = page.evaluate(() => new Promise<string>(resolve =>
        window.addEventListener('apps-preview-navigate', event => resolve((event as CustomEvent<string>).detail), { once: true })));
      await page.getByTestId('apps-app-card').first().getByTestId('app-store-card').click();
      expect(await navigated).toMatch(/^#apps\/[a-z0-9-]+$/);
      if (width === 390) {
        const keyboardNavigation = page.evaluate(() => new Promise<string>(resolve =>
          window.addEventListener('apps-preview-navigate', event => resolve((event as CustomEvent<string>).detail), { once: true })));
        await webCard.focus();
        await expect(webCard).toBeFocused();
        await webCard.press('Enter');
        expect(await keyboardNavigation).toBe('#apps/web');
      }
      await expectNoHorizontalOverflow(page);
    }
  });

  // contract-test: direct surface=gui.web assertions=apps.discovery.public-catalog,apps.navigation.hash-and-forwarding,workspace-shell.start.shared-affordances
  test('replaces the home with the shared All Apps grid and keeps catalog search usable', async ({ page }: { page: Page }) => {
    await fixturePublicApps(page);
    for (const width of [1180, 390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(preview('apps/AppsWorkspace', width, 'allApps'), { waitUntil: 'domcontentloaded' });
      await waitForComponentPreview(page);
      const grid = page.getByTestId('apps-all-items-grid');
      await expect(grid).toBeVisible();
      await expect(grid).toHaveCSS('display', 'grid');
      await expect(page.getByTestId('apps-all-items-toolbar')).toBeVisible();
      await expect(page.getByTestId('apps-search')).toHaveText('Search');
      await expect(page.getByTestId('apps-daily-inspiration-area')).toHaveCount(0);
      await expect(page.getByRole('heading', { name: 'What app do you want to use?' })).toHaveCount(0);
      await expect(page.getByTestId('apps-home-apps')).toHaveCount(0);
      await expect(page.getByTestId('workspace-composer-slot')).toHaveCount(0);
      const webCard = grid.getByTestId('apps-all-item').filter({ has: page.getByTestId('app-card-name').getByText('Web', { exact: true }) });
      await expect(webCard).toBeVisible();
      await expect(webCard).toHaveClass(/app-store-card/);
      await expect(webCard.getByTestId('app-card-description')).toBeVisible();
      await expect(webCard.getByTestId('app-card-name')).toHaveCSS('text-align', 'left');
      await expectContainedInPreview(page, webCard);
      await expectNoHorizontalOverflow(page);
      await attachWorkspaceScreenshot(page, `apps-all-${width}.png`);
      await page.getByTestId('apps-search').click();
      const search = page.getByTestId('apps-catalog-controls').getByRole('textbox');
      await expect(search).toBeFocused();
      await search.fill('Brave');
      await expect(webCard).toBeVisible();
      await expect(grid.getByTestId('apps-all-item').filter({ has: page.getByTestId('app-card-name').getByText('Health', { exact: true }) })).toHaveCount(0);
      await search.fill('no-app-matches-this-query-7295');
      await expect(grid.getByTestId('apps-all-item')).toHaveCount(0);
      await expect(page.getByTestId('apps-all-items-empty')).toHaveText(/No apps found/i);
      await search.fill('');
      await page.getByTestId('apps-catalog-controls').getByRole('combobox', { name: 'Sort' }).selectOption('name_asc');
      const names = await grid.getByTestId('app-card-name').allTextContents();
      expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b)));
      const back = page.evaluate(() => new Promise<string>(resolve =>
        window.addEventListener('apps-preview-navigate', event => resolve((event as CustomEvent<string>).detail), { once: true })));
      await page.getByTestId('apps-back-to-recent').click();
      expect(await back).toBe('#apps');
    }
  });

  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen,apps.navigation.hash-and-forwarding
  test('app home keeps its header, clipped example carousel, controls and composer bounded on laptop and phone', async ({ page }: { page: Page }) => {
    await fixturePublicApps(page);
    for (const theme of ['light', 'dark']) for (const width of [1180, 390]) {
      await page.setViewportSize({width,height:844});
      await page.goto(preview('apps/AppsWorkspace',width,'app').replace('theme=light', 'theme=' + theme),{waitUntil:'domcontentloaded'});
      await waitForComponentPreview(page);
      const fullscreen=page.getByTestId('apps-detail-fullscreen');
      await expect(fullscreen).toBeVisible();
      await expect(fullscreen.getByTestId('embed-header-title')).toContainText('Health');
      const hero=fullscreen.getByTestId('apps-hero-icon');
      await expect(hero).toBeVisible();await expect(hero).toHaveAttribute('aria-hidden','true');await expect(hero).not.toHaveAttribute('tabindex','0');await expect(hero).toHaveCSS('pointer-events','none');
      const tile=hero.locator('.apps-header-app-icon');await expect(tile).toBeVisible();expect(await tile.evaluate(element=>getComputedStyle(element).backgroundImage)).toContain('linear-gradient');expect(await tile.evaluate(element=>getComputedStyle(element,'::before').backgroundImage)).not.toBe('none');
      await expect(page.getByTestId('apps-skill-form')).toHaveCount(0);
      await expect(page.getByTestId('apps-request-textarea')).toBeVisible();
      await expect(page.getByTestId('apps-sidebar-toggle')).toHaveCount(0);
      const inner = fullscreen.locator('.content-area').first();
      await expect.poll(() => inner.evaluate(element => element.scrollHeight - element.clientHeight)).toBeLessThanOrEqual(1);
      const headerHeight = await fullscreen.locator('.embed-header').first().evaluate(element => element.getBoundingClientRect().height);
      expect(headerHeight).toBeLessThanOrEqual(width === 390 ? 190 : 240);
      const scrollBefore = await inner.evaluate(element => element.scrollTop);
      await inner.hover(); await page.mouse.wheel(0, 600);
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      await expect.poll(() => inner.evaluate(element => element.scrollTop)).toBe(scrollBefore);

      for(const id of ['apps-settings-open','apps-request-add-files','apps-request-mic']) {
        const control=page.getByTestId(id);await expect(control).toBeVisible();await expectContainedInPreview(page,control);
      }
      for (const id of ['apps-settings-open']) {
        const bounds = await page.getByTestId(id).boundingBox();
        expect(bounds!.width).toBeCloseTo(bounds!.height, 0);
        expect(bounds!.width).toBeLessThanOrEqual(44);
      }
      const submit=page.getByTestId('apps-request-submit');
      await expect(submit).toHaveCount(0);
      await page.getByTestId('apps-request-textarea').fill('Find dermatologists in Berlin');
      await expect(submit).toBeVisible();await expectContainedInPreview(page,submit);
      await page.getByTestId('apps-request-textarea').fill('');
      await expect(submit).toHaveCount(0);await expect(page.getByTestId('apps-request-mic')).toBeVisible();
      await expect(page.getByTestId('apps-settings-open')).toHaveCount(1);
      const carousel=page.getByTestId('apps-preview-carousel');
      const examples=carousel.getByTestId('app-store-example-chat-card');
      await expect(examples.first()).toBeVisible();
      const ids=await examples.evaluateAll(elements=>elements.map(element=>element.getAttribute('data-chat-id')));
      expect(ids.length).toBeGreaterThan(0);expect(ids.every(id=>ALL_EXAMPLE_CHATS.some(chat=>chat.chat_id===id))).toBe(true);
      await expect(carousel).toHaveCSS('overflow-x','auto');
      const geometry=await carousel.evaluate(element=>({scroll:element.scrollWidth,client:element.clientWidth}));
      if(width===390&&ids.length>1)expect(geometry.scroll).toBeGreaterThan(geometry.client);
      await carousel.evaluate(element=>{element.scrollLeft=element.scrollWidth;});
      await expect(examples.last()).toBeInViewport();
      const exampleNavigation=page.evaluate(()=>new Promise<string>(resolve=>window.addEventListener('apps-preview-navigate',event=>resolve((event as CustomEvent<string>).detail),{once:true})));
      await examples.last().click();expect(await exampleNavigation).toBe('#chat-id='+encodeURIComponent(ids.at(-1)!));
      await page.getByTestId('apps-request-textarea').focus();await expect(page.getByTestId('apps-request-textarea')).toBeFocused();
      await expectSettingsDispatch(page, 'apps/health');
      await expect(page.getByTestId('apps-daily-searches')).toHaveCount(0);
      await expectNoHorizontalOverflow(page);
      const navigated=page.evaluate(()=>new Promise<string>(resolve=>window.addEventListener('apps-preview-navigate',event=>resolve((event as CustomEvent<string>).detail),{once:true})));
      await page.getByTestId('apps-detail-close').click();expect(await navigated).toBe('#apps');
    }
  });

  // contract-test: supporting surface=gui.web assertions=apps.presentation.shared-detail-and-recency,apps.results.shared-fullscreen
  test('Travel map zoom and round controls remain reachable below header overlays on laptop and phone', async ({ page }: { page: Page }) => {
    await fixturePublicApps(page);
    await page.route('https://*.tile.openstreetmap.org/**', route => route.fulfill({
      contentType: 'image/png',
      body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64'),
    }));
    for (const width of [1180, 390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(preview('apps/AppsWorkspace', width, 'appTravel'), { waitUntil: 'domcontentloaded' });
      await waitForComponentPreview(page);
      const header = page.getByTestId('apps-map-header');
      await expect(header.getByTestId('embed-leaflet-map')).toHaveAttribute('data-map-ready', 'true');
      const zoom = header.getByTestId('embed-map-zoom-controls');
      const zoomButtons = zoom.getByRole('button');
      await expect(zoomButtons).toHaveCount(2);
      for (const control of [...await zoomButtons.all(), page.getByTestId('apps-detail-close'), page.getByTestId('apps-map-toggle'), page.getByTestId('apps-settings-open')]) {
        await expect(control).toBeVisible();
        await expectContainedInPreview(page, control);
        expect(await control.evaluate(element => {
          const rect = element.getBoundingClientRect();
          return element.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2));
        })).toBe(true);
      }
      const headerBounds = await header.boundingBox();
      const zoomBounds = await zoom.boundingBox();
      expect(zoomBounds!.y).toBeGreaterThan(headerBounds!.y + 44);
      expect(zoomBounds!.y + zoomBounds!.height).toBeLessThanOrEqual(headerBounds!.y + headerBounds!.height);
      const composer = page.getByTestId('apps-request-composer');
      await expectContainedInPreview(page, composer);
      expect((await composer.boundingBox())!.height).toBeLessThanOrEqual(88);
      await zoomButtons.first().click();
      await zoomButtons.last().click();
      await expectNoHorizontalOverflow(page);
      await attachWorkspaceScreenshot(page, `apps-travel-controls-${width}.png`);
    }
  });

  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.library.embeds-account-paginated
  test('drafts survive profile publications and login readiness while account and Team changes clear private attachments', async ({ page }: { page: Page }) => {
    await fixturePublicApps(page);
    await page.route('**/v1/apps/workspace/library/web*', route => route.fulfill({ json: {
      app_id: 'web', daily_searches_enabled: false, saved_searches: [], recommendations: [],
    } }));
    await page.route('**/v1/apps/workspace/results?*', route => route.fulfill({ json: { items: [], offset: 0, limit: 20, has_more: false } }));
    await page.goto(preview('apps/AppsWorkspace', 1180, 'teamLibrary'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    const input = page.getByTestId('apps-request-textarea');
    const attach = async () => page.getByTestId('apps-request-file-input').setInputFiles({
      name: 'private-garden.txt', mimeType: 'text/plain', buffer: Buffer.from('Synthetic garden reference'),
    });
    await input.fill('Find quiet gardens'); await attach();
    await expectSettingsDispatch(page, 'apps/web');
    await expect(input).toBeVisible();
    await expect(input).toHaveValue('Find quiet gardens');
    await expect(page.getByTestId('apps-request-attachments')).toContainText('private-garden.txt');
    await page.evaluate(() => window.dispatchEvent(new Event('apps-preview-refresh-account')));
    await expect(input).toHaveValue('Find quiet gardens');
    await expect(page.getByTestId('apps-request-attachments')).toContainText('private-garden.txt');
    await expect(page.getByTestId('apps-request-submit')).toBeEnabled();
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('apps-preview-set-team', { detail: 'preview-studio' })));
    await expect(input).toHaveValue(''); await expect(page.getByTestId('apps-request-attachments')).toHaveCount(0);
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('apps-preview-set-team', { detail: null })));
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('apps-preview-set-owner', { detail: { authenticated: false, userId: null } })));
    await input.fill('Continue this guest search after login'); await attach();
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('apps-preview-set-owner', { detail: { authenticated: true, userId: null } })));
    await expect(input).toHaveValue('Continue this guest search after login');
    await expect(input).toBeDisabled();
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('apps-preview-set-owner', { detail: { authenticated: true, userId: 'preview-user' } })));
    await expect(input).toHaveValue('Continue this guest search after login');
    await expect(input).toBeEnabled();
    await expect(page.getByTestId('apps-request-attachments')).toContainText('private-garden.txt');
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('apps-preview-set-owner', { detail: { authenticated: true, userId: 'preview-other' } })));
    await expect(input).toHaveValue(''); await expect(page.getByTestId('apps-request-attachments')).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=apps.recommendations.private-daily,apps.requests.natural-language
  test('saved and recommended carousels and the explicit sidebar use the active account',async({page}:{page:Page})=>{
    await fixturePublicApps(page);
    const now=Math.floor(Date.now()/1000);const enabled=true;
    const library=()=>({app_id:'web',daily_searches_enabled:enabled,saved_searches:Array.from({length:4},(_,index)=>({id:`saved-${index}`,skill_id:'search',title:`Saved garden ${index}`,query:`Saved garden ${index}`,parameters:{query:`garden ${index}`},saved_at:now-index})),
      recommendations:[{id:'90000000-0000-4000-8000-000000000010',skill_id:'search',created_at:now,expires_at:now+3600,result:{query:'Recommended gardens',result_count:1,results:[{title:'Fresh garden result',url:'https://example.test/garden'}]}}]});
    await page.route('**/v1/apps/workspace/library/web',route=>route.fulfill({json:library()}));
    await page.route('**/v1/apps/workspace/results?*',route=>route.fulfill({json:{items:[],offset:0,limit:20,has_more:false}}));
    for(const width of [1180,390]){
      await page.setViewportSize({width,height:844});await page.goto(preview('apps/AppsWorkspace',width,'teamLibrary'),{waitUntil:'domcontentloaded'});await waitForComponentPreview(page);
      await expect(page.getByTestId('apps-tab-recommended')).toHaveAttribute('aria-pressed','true');
      await expect(page.getByTestId('apps-preview-carousel').getByTestId('embed-preview')).toBeVisible();
      await page.getByTestId('apps-tab-saved').click();await expect(page.getByTestId('apps-tab-saved')).toHaveAttribute('aria-pressed','true');
      const carousel=page.getByTestId('apps-preview-carousel');await expect(carousel.getByTestId('apps-saved-search-query')).toHaveCount(4);
      expect(await carousel.evaluate(element=>element.scrollWidth>element.clientWidth)).toBe(true);
      await carousel.evaluate(element=>{element.scrollLeft=element.scrollWidth;});await expect(carousel.getByTestId('apps-saved-search-query').last()).toBeInViewport();
      await page.goto(preview('apps/AppsWorkspace',width,'teamLibrarySidebar'),{waitUntil:'domcontentloaded'});await waitForComponentPreview(page);const sidebar=page.getByTestId('apps-sidebar');await expect(sidebar).toBeVisible();
      expect(await sidebar.locator('section').evaluateAll(elements=>elements.map(element=>element.getAttribute('data-testid')))).toEqual(['apps-sidebar-saved','apps-sidebar-recent','apps-sidebar-examples']);
      await expect(sidebar.getByTestId('apps-sidebar-saved').getByRole('button')).toHaveCount(4);
      const closed=page.evaluate(()=>new Promise<void>(resolve=>window.addEventListener('apps-preview-sidebar-close',()=>resolve(),{once:true})));await sidebar.getByRole('button',{name:'Close',exact:true}).click();await closed;
      await expectNoHorizontalOverflow(page);
    }
  });

  // contract-test: direct surface=gui.web assertions=apps.recommendations.private-daily,settings-ui.composition.canonical-and-accessible
  test('canonical app settings show skill cards and persist Daily searches for the active owner', async ({ page }: { page: Page }) => {
    let enabled = true; const bodies: Record<string, unknown>[] = [];
    const library = () => ({ app_id: 'web', daily_searches_enabled: enabled, saved_searches: [], recommendations: [] });
    await page.route('**/v1/apps/workspace/library/web', route => route.fulfill({ json: library() }));
    await page.route('**/v1/apps/workspace/library/web/settings', route => { const body = route.request().postDataJSON(); bodies.push(body); enabled = body.daily_searches_enabled; return route.fulfill({ json: library() }); });
    for (const width of [1180, 390]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(preview('settings/AppDetails', width, 'authenticatedSettings'), { waitUntil: 'domcontentloaded' });
      await waitForComponentPreview(page);
      await expect(page.getByTestId('settings-skill-cards-scroll').getByTestId('app-store-card').first()).toBeVisible();
      const toggle = page.getByTestId('apps-daily-searches').getByRole('checkbox');
      await expect(toggle).toBeEnabled();
      await expect(toggle).toBeChecked({ checked: enabled });
      const before = enabled; await page.getByTestId('apps-daily-searches-toggle').click();
      await expect.poll(() => bodies.at(-1)?.daily_searches_enabled).toBe(!before);
      await expect(toggle).toBeChecked({ checked: !before });
      expect(bodies.at(-1)?.expected_user_id).toBe('preview-settings-user');
      await expect(page.getByTestId('apps-workspace')).toHaveCount(0);
      await expectNoHorizontalOverflow(page);
    }
  });

  // contract-test: direct surface=gui.web assertions=apps.navigation.hash-and-forwarding
  test('a public focus detail still opens its real published example safely',async({page}:{page:Page})=>{
    await page.goto(preview('apps/AppsWorkspace',390,'politicsFocus'),{waitUntil:'domcontentloaded'});await waitForComponentPreview(page);
    await page.evaluate(()=>{window.open=((url,target,features)=>{(window as Window&{appsOpenedExample?:string[]}).appsOpenedExample=[String(url),String(target),String(features)];return null;}) as typeof window.open;});
    await page.getByTestId('app-store-example-chat-card').click();expect(await page.evaluate(()=>(window as Window&{appsOpenedExample?:string[]}).appsOpenedExample)).toEqual(['/#chat-id=example-housing-policy-dinner-discussion','_blank','noopener,noreferrer']);
  });

  // contract-test: direct surface=gui.web assertions=apps.recommendations.private-daily,apps.library.embeds-account-paginated
  test('switching Personal and Team clears private saved entries before rejecting stale responses',async({page}:{page:Page})=>{
    await fixturePublicApps(page);let releasePersonal!:()=>void;let releaseTeam!:()=>void;
    const personalGate=new Promise<void>(resolve=>{releasePersonal=resolve;});const teamGate=new Promise<void>(resolve=>{releaseTeam=resolve;});
    let blockPersonal=false;const queries:string[]=[];
    await page.route('**/v1/apps/workspace/results?*',route=>route.fulfill({json:{items:[],offset:0,limit:20,has_more:false}}));
    await page.route('**/v1/apps/workspace/library/web*',async route=>{
      const team=new URL(route.request().url()).searchParams.get('team_id');queries.push(team??'personal');
      if(!team&&blockPersonal)await personalGate;if(team)await teamGate;
      await route.fulfill({json:{app_id:'web',daily_searches_enabled:true,recommendations:[],saved_searches:[{id:team?'team':'personal',skill_id:'search',query:team?'Team garden':'Personal garden',parameters:{query:'garden'},saved_at:1}]}});
    });
    await page.goto(preview('apps/AppsWorkspace',1100,'teamLibrarySidebar'),{waitUntil:'domcontentloaded'});await waitForComponentPreview(page);
    await page.getByTestId('apps-tab-saved').click();await expect(page.getByTestId('apps-saved-search-query')).toContainText('Personal garden');
    // A synthetic encrypted Personal memory exercises the actual snapshot reader,
    // rather than treating a server saved-search row as a decrypted memory.
    await page.evaluate(async () => {
      const browser = window as Window & {
        appsBlockMemoryRead?: boolean;
        appsMemoryReadStarted?: number;
        appsMemoryReadReleased?: number;
        appsReleaseMemoryReads?: Array<() => void>;
      };
      const open = (name: string, version?: number) => new Promise<IDBDatabase>((resolve, reject) => {
        const request = version ? indexedDB.open(name, version) : indexedDB.open(name);
        request.onupgradeneeded = () => { if (name === 'openmates_crypto' && !request.result.objectStoreNames.contains('keys')) request.result.createObjectStore('keys'); };
        request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
      });
      const write = (db: IDBDatabase, store: string, value: unknown, key?: IDBValidKey) => new Promise<void>((resolve, reject) => {
        const transaction = db.transaction(store, 'readwrite');
        if (key === undefined) transaction.objectStore(store).put(value); else transaction.objectStore(store).put(value, key);
        transaction.oncomplete = () => resolve(); transaction.onerror = () => reject(transaction.error);
      });
      const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const ciphertext = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(JSON.stringify({
        embed_id: '72000000-0000-4000-8000-000000000001', title: 'Personal encrypted memory marker', skill_id: 'search', _original_item_key: 'personal-memory',
      }))));
      const combined = new Uint8Array(iv.length + ciphertext.length); combined.set(iv); combined.set(ciphertext, iv.length);
      const keyDb = await open('openmates_crypto', 1);
      try { await write(keyDb, 'keys', key, 'master_key'); } finally { keyDb.close(); }
      const chatDb = await open('chats_db');
      try { await write(chatDb, 'app_settings_memories', {
        id: '72000000-0000-4000-8000-000000000002', app_id: 'web', item_key: 'synthetic-personal-hash', item_type: 'read_later',
        encrypted_item_json: btoa(String.fromCharCode(...combined)), encrypted_app_key: '', created_at: 1, updated_at: 1, item_version: 1,
      }); } finally { chatDb.close(); }
      const expected = btoa(String.fromCharCode(...ciphertext));
      const decrypt = crypto.subtle.decrypt.bind(crypto.subtle);
      browser.appsReleaseMemoryReads = [];
      browser.appsMemoryReadStarted = 0; browser.appsMemoryReadReleased = 0;
      crypto.subtle.decrypt = (async (...args: Parameters<SubtleCrypto['decrypt']>) => {
        const decrypted = await decrypt(...args);
        const data = args[2];
        const bytes = data instanceof ArrayBuffer ? new Uint8Array(data) : new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
        if (!browser.appsBlockMemoryRead || btoa(String.fromCharCode(...bytes)) !== expected) return decrypted;
        browser.appsMemoryReadStarted = (browser.appsMemoryReadStarted ?? 0) + 1;
        return new Promise<ArrayBuffer>(resolve => browser.appsReleaseMemoryReads!.push(() => {
          browser.appsMemoryReadReleased = (browser.appsMemoryReadReleased ?? 0) + 1; resolve(decrypted);
        }));
      }) as SubtleCrypto['decrypt'];
      window.dispatchEvent(new Event('appsWorkspaceLibraryUpdated'));
    });
    await expect(page.getByTestId('apps-sidebar').getByText('Personal encrypted memory marker', { exact: true })).toBeVisible();

    blockPersonal=true;await page.evaluate(()=>{(window as Window & {appsBlockMemoryRead?:boolean}).appsBlockMemoryRead=true;window.dispatchEvent(new Event('appsWorkspaceLibraryUpdated'));});
    await page.waitForFunction(() => ((window as Window & {appsMemoryReadStarted?:number}).appsMemoryReadStarted ?? 0) > 0);await expect.poll(()=>queries.filter(value=>value==='personal').length).toBeGreaterThan(1);
    await page.evaluate(()=>window.dispatchEvent(new CustomEvent('apps-preview-set-team',{detail:'preview-studio'})));await expect.poll(()=>queries.at(-1)).toBe('preview-studio');
    await expect(page.getByText('Personal garden',{exact:true})).toHaveCount(0);await expect(page.getByText('Personal encrypted memory marker',{exact:true})).toHaveCount(0);releaseTeam();
    await page.getByTestId('apps-tab-saved').click();await expect(page.getByTestId('apps-saved-search-query')).toContainText('Team garden');
    const lateResponse=page.waitForResponse(response=>response.url().endsWith('/v1/apps/workspace/library/web'));releasePersonal();
    await page.evaluate(() => {const browser=window as Window & {appsBlockMemoryRead?:boolean;appsReleaseMemoryReads?:Array<()=>void>};browser.appsBlockMemoryRead=false;for(const release of browser.appsReleaseMemoryReads??[])release();});
    await page.waitForFunction(() => ((window as Window & {appsMemoryReadReleased?:number}).appsMemoryReadReleased ?? 0) > 0);
    await lateResponse;await expect(page.getByText('Personal encrypted memory marker',{exact:true})).toHaveCount(0);await expect(page.getByTestId('apps-saved-search-query')).toContainText('Team garden');await expect(page.getByText('Personal garden',{exact:true})).toHaveCount(0);
    blockPersonal=false;await page.evaluate(()=>window.dispatchEvent(new CustomEvent('apps-preview-set-team',{detail:null})));await page.getByTestId('apps-tab-saved').click();await expect(page.getByTestId('apps-saved-search-query')).toContainText('Personal garden');await expect(page.getByText('Team garden',{exact:true})).toHaveCount(0);expect(queries.at(-1)).toBe('personal');await expect(page.getByTestId('apps-sidebar').getByText('Personal encrypted memory marker',{exact:true})).toBeVisible();
  });

});

for (const theme of ['light', 'dark'] as const) {
    // contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible
    test(`selected SettingsTabs icon stays white in ${theme} theme after switching tabs`, async ({ page }, testInfo) => {
        await page.goto(
            `/dev/preview/settings/elements/SettingsTabs?theme=${theme}&background=%23dbeafe&width=640&chrome=0`
        );
        await waitForComponentPreview(page);

        const overview = page.getByTestId('preview-settings-tab-overview');
        const results = page.getByTestId('preview-settings-tab-results');
        const overviewIcon = overview.locator('.tab-icon');
        const resultsIcon = results.locator('.tab-icon');
        await expect(overview).toHaveAttribute('aria-selected', 'true');
        await expect(results).toHaveAttribute('aria-selected', 'false');
        await expect(overviewIcon).toHaveCSS('background-color', 'rgb(255, 255, 255)');
        const inactiveColor = await resultsIcon.evaluate(element => getComputedStyle(element).backgroundColor);
        expect(inactiveColor).not.toBe('rgb(255, 255, 255)');
        await expect(overviewIcon).not.toHaveCSS('mask-image', 'none');

        await results.click();
        await expect(results).toHaveAttribute('aria-selected', 'true');
        await expect(overview).toHaveAttribute('aria-selected', 'false');
        await expect(resultsIcon).toHaveCSS('background-color', 'rgb(255, 255, 255)');
        await expect(overviewIcon).toHaveCSS('background-color', inactiveColor);
        await expect(resultsIcon).not.toHaveCSS('mask-image', 'none');

        await testInfo.attach(`settings-tabs-${theme}-selected`, {
            body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }),
            contentType: 'image/png',
        });
    });
}
