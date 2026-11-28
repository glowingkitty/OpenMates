// playwright-account: not_required reason=isolated_component_preview
import type { Locator, Page } from '@playwright/test';
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';

test.describe.configure({ mode: 'parallel' });

// Available actions from the deployed fixtures before the correction. The
// snapshot excludes general navigation chrome and the old chat share label.
const fixtures: readonly (readonly [string, string, ...string[]])[] = [
  ["StandaloneEmbedFullscreen","","Copy","Download"],
  ["audio/RecordingEmbedFullscreen","","Download"],
  ["business/BusinessCompanyFinancialResultEmbedFullscreen",""],
  ["calendar/CalendarEventEmbedFullscreen","","Add to calendar"],
  ["checks/CheckEmbedFullscreen",""],
  ["code/ApplicationEmbedFullscreen","","Download"],
  ["code/CodeEmbedFullscreen","","Copy","Download","Next embed","Previous embed"],
  ["code/CodeEmbedFullscreen","editableInProject","Copy","Download"],
  ["code/CodeRepoEmbedFullscreen",""],
  ["code/TestResultEmbedFullscreen",""],
  ["design/DesignDocumentEmbedFullscreen",""],
  ["design/DesignDocumentEmbedFullscreen","proposal"],
  ["design/DesignEmbroideryEmbedFullscreen","","Download"],
  ["design/DesignIconResultEmbedFullscreen","","Copy"],
  ["design/editor/DesignEditorFullscreen",""],
  ["design/editor/DesignEditorFullscreen","saved-edit"],
  ["diagrams/DiagramHtmlEmbedFullscreen",""],
  ["diagrams/MermaidDiagramEmbedFullscreen","","Copy","Download"],
  ["docs/DocsEmbedFullscreen","","Copy","Download"],
  ["docs/DocsEmbedFullscreen","editableInChat","Copy","Download"],
  ["electronics/ElectronicsComponentEmbedFullscreen",""],
  ["events/EventEmbedFullscreen","","Add to calendar","Next embed"],
  ["fitness/FitnessResultEmbedFullscreen","","Add to calendar"],
  ["focus_mode/FocusModeActivationEmbedFullscreen",""],
  ["health/HealthAppointmentEmbedFullscreen","","Add to calendar"],
  ["home/HomeListingEmbedFullscreen",""],
  ["hosting/HostingDomainEmbedFullscreen","","Copy"],
  ["images/ImageEmbedFullscreen",""],
  ["images/ImageGenerateEmbedFullscreen",""],
  ["images/ImageResultEmbedFullscreen",""],
  ["jobs/JobsResultEmbedFullscreen","","Copy"],
  ["mail/MailEmbedFullscreen","","Copy"],
  ["maps/MapLocationEmbedFullscreen","","Copy"],
  ["maps/MapsLocationEmbedFullscreen","","Copy"],
  ["math/MathPlotEmbedFullscreen",""],
  ["mindmaps/MindMapEmbedFullscreen","","Download"],
  ["models3d/Model3DGenerateEmbedFullscreen",""],
  ["models3d/Model3DResultEmbedFullscreen",""],
  ["music/MusicGenerateEmbedFullscreen",""],
  ["news/NewsArticleEmbedFullscreen",""],
  ["news/NewsEmbedFullscreen",""],
  ["nutrition/NutritionRecipeEmbedFullscreen",""],
  ["pdf/PDFEmbedFullscreen",""],
  ["pdf/PdfReadEmbedFullscreen","","Copy","Download"],
  ["pdf/PdfSearchEmbedFullscreen","","Copy"],
  ["sheets/SheetEmbedFullscreen","","Copy","Download","Download CSV"],
  ["sheets/SheetEmbedFullscreen","editableFormulas","Copy","Download","Download CSV"],
  ["shopping/ShoppingResultEmbedFullscreen",""],
  ["slides/SlidesDeckEmbedFullscreen","","Copy"],
  ["slides/SlidesTemplateEmbedFullscreen",""],
  ["social_media/SocialMediaPostEmbedFullscreen",""],
  ["specifications/SpecificationEmbedFullscreen",""],
  ["travel/TravelConnectionEmbedFullscreen","","Add to calendar","Copy","Download"],
  ["travel/TravelFlightDetailsEmbedFullscreen",""],
  ["travel/TravelStayEmbedFullscreen",""],
  ["tv/TVTitleEmbedFullscreen",""],
  ["videos/VideoCreateEmbedFullscreen",""],
  ["videos/VideoEmbedFullscreen","","Copy"],
  ["videos/VideoGenerateEmbedFullscreen",""],
  ["weather/WeatherDayEmbedFullscreen",""],
  ["web/WebsiteEmbedFullscreen",""],
  ["wiki/WikipediaFullscreen",""],
  ["workflows/WorkflowEmbedFullscreen",""],
];

const moreName = { name: 'More', exact: true } as const;

async function openPreview(page: Page, fixture: string, width: number, variant = '', props?: unknown) {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 860 });
  const params = new URLSearchParams({ chrome: '0', theme: 'light', background: '#dbeafe', width: String(width) });
  if (variant) params.set('variant', variant);
  if (props) params.set('props', JSON.stringify(props));
  await page.goto(`/dev/preview/embeds/${fixture}?${params}`);
  await waitForComponentPreview(page);
}

async function expectFlushCorner(shell: Locator) {
  await waitForComponentMotion(shell);
  const bar = shell.getByTestId('embed-top-bar');
  const tile = bar.getByTestId('embed-preview-corner');
  await expect(tile).toHaveCSS('border-top-left-radius', '0px');
  await expect(tile).toHaveCSS('border-top-right-radius', '0px');
  await expect(tile).toHaveCSS('border-bottom-left-radius', '0px');
  await expect(tile).toHaveCSS('border-bottom-right-radius', '22px');
  await expect(shell).toHaveCSS('border-top-left-radius', '0px');
  expect(await tile.evaluate(element => {
    const tile = element.getBoundingClientRect();
    const shell = element.closest('[data-embed-shell="shared"]')!.getBoundingClientRect();
    return [tile.x - shell.x, tile.y - shell.y, tile.width, tile.height].map(Math.round);
  })).toEqual([0, 0, 44, 44]);
}

async function expectMenu(shell: Locator, expected: readonly string[]) {
  const bar = shell.getByTestId('embed-top-bar');
  await bar.getByRole('button', moreName).click();
  const menu = bar.getByTestId('embed-more-menu');
  await expect(menu).toBeVisible();
  await expect(menu.getByTestId('embed-report-issue-button')).toHaveAccessibleName('Report Issue');
  if (await menu.getByTestId('embed-share-button').count()) {
    await expect(menu.getByTestId('embed-share-button')).toHaveAccessibleName('Share embed');
  }
  const entries = await menu.locator('button, a').evaluateAll(elements =>
    elements.map(element => (element.getAttribute('aria-label') ?? element.textContent ?? '').trim()));
  expect(entries.filter(label => /\bchat\b/i.test(label))).toEqual([]);
  expect(entries).toEqual(expect.arrayContaining(expected));
  return menu;
}

for (const [fixture, variant, ...actions] of fixtures) {
  // contract-test: supporting surface=gui.web assertions=shared-embed-fullscreen.content,shared-embed-fullscreen.menu
  test(`${fixture} ${variant || 'default'} retains its fullscreen actions`, async ({ page }) => {
    await openPreview(page, fixture, 1280, variant);
    const shell = page.locator('[data-embed-shell="shared"][data-header-kind="content"]').last();
    await expect(shell).toBeVisible();
    await expectFlushCorner(shell);
    await expectMenu(shell, actions);
  });
}

// contract-test: supporting surface=gui.web assertions=shared-embed-fullscreen.content
test('the Code and Sheets fullscreen corners match their distinct preview tiles', async ({ page }) => {
  const glyphs = new Set<string>();
  async function cornerStyle() {
    const tile = page.getByTestId('embed-preview-corner').first();
    await expect(tile).toBeVisible();
    return tile.evaluate(element => {
      const style = getComputedStyle(element);
      return {
        background: style.background,
        width: style.width,
        height: style.height,
        glyph: getComputedStyle(element.firstElementChild!).maskImage,
      };
    });
  }
  for (const prefix of ['code/CodeEmbed', 'sheets/SheetEmbed']) {
    await openPreview(page, `${prefix}Preview`, 390);
    const preview = await cornerStyle();
    expect(preview.glyph).not.toBe('none');
    glyphs.add(preview.glyph);
    await openPreview(page, `${prefix}Fullscreen`, 390);
    expect(await cornerStyle()).toEqual(preview);
  }
  expect(glyphs.size).toBe(2);
});

for (const width of [1280, 390]) {
  for (const kind of ['news', 'website', 'website from search'] as const) {
    // contract-test: supporting surface=gui.web assertions=shared-embed-fullscreen.content,shared-embed-fullscreen.article
    test(`${kind} hands off the article title on scroll at ${width}px`, async ({ page }, info) => {
      const title = 'The city market';
      const description = 'The market opens at dawn and brings produce from nearby farms. '.repeat(70);
      const content = { title, description, url: 'https://example.com/market', image: '/store-examples/events-1.webp' };
      if (kind === 'news') {
        await openPreview(page, 'news/NewsEmbedFullscreen', width, '', content);
      } else if (kind === 'website') {
        await openPreview(page, 'web/WebsiteEmbedFullscreen', width, '', {
          data: { decodedContent: content, embedData: { status: 'finished' }, attrs: { app_id: 'web', skill_id: 'website' } },
        });
      } else {
        await openPreview(page, 'web/WebSearchEmbedFullscreen', width, '', { results: [content] });
        await page.locator('[data-header-kind="execution"]').getByText(title, { exact: true }).click();
      }
      const shell = page.locator('[data-embed-shell="shared"][data-header-kind="content"]').last();
      const viewport = shell.getByTestId('embed-scrollport');
      const heading = viewport.getByRole('heading', { name: title, level: 1 });
      const image = viewport.getByRole('img').first();
      const source = viewport.getByRole('button', { name: 'Open on example.com' });
      const text = shell.getByTestId('embed-compact-text');
      await expect(heading).toBeInViewport();
      await expect(image).toBeInViewport();
      await expect(source).toBeVisible();
      await expect(text).toHaveAttribute('data-title-visible', 'false');
      await expect(text).toHaveCSS('opacity', '0');
      const [headingBox, imageBox, sourceBox] = await Promise.all([heading.boundingBox(), image.boundingBox(), source.boundingBox()]);
      expect(headingBox!.y + headingBox!.height).toBeLessThanOrEqual(imageBox!.y);
      expect(imageBox!.y + imageBox!.height).toBeLessThanOrEqual(sourceBox!.y);
      await expectFlushCorner(shell);
      await info.attach(`${kind}-top-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
      await viewport.evaluate(element => { element.scrollTop = element.scrollHeight; });
      await expect(heading).not.toBeInViewport();
      await expect(text).toHaveAttribute('data-title-visible', 'true');
      await expect(text).toHaveCSS('opacity', '1');
      await expectFlushCorner(shell);
      await expect(shell.getByTestId('embed-followup-composer')).toBeInViewport({ ratio: 1 });
      await info.attach(`${kind}-scrolled-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
      await viewport.evaluate(element => { element.scrollTop = 0; });
      await expect(heading).toBeInViewport();
      await expect(text).toHaveCSS('opacity', '0');
    });
  }
}

for (const width of [1280, 390]) {
  // contract-test: supporting surface=gui.web assertions=shared-embed-fullscreen.menu
  test(`the Code More menu preserves Copy and Download at ${width}px`, async ({ page }, info) => {
    await openPreview(page, 'code/CodeEmbedFullscreen', width, 'editableInProject');
    const shell = page.locator('[data-embed-shell="shared"]');
    const menu = await expectMenu(shell, ['Copy', 'Download', 'Share embed']);
    await expect(menu.getByTestId('embed-share-button')).toBeVisible();
    await info.attach(`code-more-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
    await menu.getByRole('button', { name: 'Copy', exact: true }).click();
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain('def greet(name)');
    const reopened = await expectMenu(shell, ['Copy', 'Download', 'Share embed']);
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      reopened.getByTestId('embed-download-button').click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/\.[a-z]+$/i);
  });

  // contract-test: supporting surface=gui.web assertions=shared-embed-fullscreen.menu,design-editor.export.artboard
  test(`Design exports remain available from More at ${width}px`, async ({ page }, info) => {
    await openPreview(page, 'design/DesignDocumentEmbedFullscreen', width);
    const shell = page.locator('[data-embed-shell="shared"]');
    const menu = await expectMenu(shell, ['Download SVG', 'Download PNG', 'Download PDF']);
    await info.attach(`design-more-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      menu.getByTestId('design-more-export-svg').click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/\.svg$/);
  });
}

// contract-test: supporting surface=gui.web assertions=shared-embed-fullscreen.menu
test('a loaded Design icon retains its header download', async ({ page }) => {
  await page.route('**/v1/apps/design/icons/iconify/tabler/home.svg', route => route.fulfill({
    contentType: 'image/svg+xml',
    headers: { 'access-control-allow-origin': '*' },
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><rect width="24" height="24" fill="currentColor"/></svg>',
  }));
  await openPreview(page, 'design/DesignIconResultEmbedFullscreen', 390);
  const shell = page.locator('[data-embed-shell="shared"]');
  await expect(shell.getByRole('button', { name: 'Download PNG', exact: true })).toHaveAttribute('href', /^data:image\/png/);
  const menu = await expectMenu(shell, ['Download', 'Share embed']);
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    menu.getByTestId('embed-download-button').click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.png$/);
});
