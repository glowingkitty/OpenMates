import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// Contract: Project skill embeds list references only; opening originals requires project access.
const ROOT = '/dev/preview/embeds/projects/';

async function open(page: import('@playwright/test').Page, component: string, variant = '', width = 390) {
  await page.setViewportSize({ width, height: width < 600 ? 844 : 900 });
  await page.goto(`${ROOT}${component}?chrome=0&width=${width}${variant ? `&variant=${variant}` : ''}`);
  await waitForComponentPreview(page);
}

// contract-test: supporting surface=gui.web assertions=projects.files.chat-focus-required,message-input.actions.visibility
test('empty-chat welcome hydrates without a Project operation', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dev/preview/ActiveChatFocusFixture?chrome=0&theme=dark&background=%23171717&width=390');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('active-chat-container')).toBeVisible();
  await expect(page.getByTestId('landing-intro-expanded')).toBeVisible();
  await expect(page.getByTestId('message-input-wrapper')).toHaveCount(1);
  expect(pageErrors).toEqual([]);
});

// contract-test: supporting surface=gui.web assertions=projects.files.connected-embed-previews
test('project search preview names the project, uses its icon, and opens fullscreen on phone and desktop', async ({ page }) => {
  for (const width of [390, 1100]) {
    await open(page, 'ProjectReferenceEmbedPreview', width === 390 ? 'mobile' : '', width);
    const preview = page.getByTestId('project-reference-preview');
    await expect(preview).toContainText('“README” in OpenMates');
    await expect(preview).toContainText('2 file references');
    await expect(page.getByTestId('embed-basic-infos-bar')).toContainText('Search files');
    const card = page.getByTestId('embed-preview');
    const icon = page.getByTestId('embed-app-icon-mask').first();
    await expect(icon).toBeVisible();
    const iconMasks = await icon.evaluate((element) => {
      const rendered = getComputedStyle(element);
      const expected = document.createElement('span');
      expected.style.maskImage = rendered.getPropertyValue('--icon-url-project').trim();
      return { actual: rendered.maskImage, expected: expected.style.maskImage };
    });
    expect(iconMasks.expected).not.toBe('');
    expect(iconMasks.actual).toBe(iconMasks.expected);
    const bounds = await card.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(-1);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width + 1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
    await page.evaluate(() => {
      (window as Window & { projectReferenceOpens?: number }).projectReferenceOpens = 0;
      window.addEventListener('project-reference-fullscreen-request', () => {
        (window as Window & { projectReferenceOpens?: number }).projectReferenceOpens! += 1;
      }, { once: true });
    });
    await card.click();
    await expect.poll(() => page.evaluate(() => (window as Window & { projectReferenceOpens?: number }).projectReferenceOpens)).toBe(1);
  }
});

// contract-test: supporting surface=gui.web assertions=projects.files.connected-embed-previews
test('legacy empty results and processing have honest states', async ({ page }) => {
  await open(page, 'ProjectReferenceEmbedPreview', 'legacyEmpty');
  await expect(page.getByTestId('project-reference-preview')).toContainText('No file references found');
  await open(page, 'ProjectReferenceEmbedPreview', 'processing');
  await expect(page.getByTestId('project-reference-preview')).toContainText('Waiting for Project results');
});

// contract-test: supporting surface=gui.web assertions=projects.files.connected-embed-previews
test('content search and legacy Project references retain distinct skill labels', async ({ page }) => {
  await open(page, 'ProjectReferenceEmbedPreview', 'textSearch');
  await expect(page.getByTestId('embed-basic-infos-bar')).toContainText('Search text');
  await expect(page.getByTestId('project-reference-preview')).toContainText('“README” in OpenMates');
  await open(page, 'ProjectReferenceEmbedPreview', 'legacyEmpty');
  await expect(page.getByTestId('embed-basic-infos-bar')).toContainText('Search Projects');
});

// contract-test: supporting surface=gui.web assertions=projects.files.no-server-decryption-authority,projects.files.connected-embed-previews
test('fullscreen lists original file references without copied content', async ({ page }) => {
  await open(page, 'ProjectReferenceEmbedFullscreen');
  const fullscreen = page.getByTestId('project-reference-fullscreen');
  await expect(fullscreen).toBeVisible();
  const rows = page.getByTestId('project-reference-row');
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText('README.md');
  await expect(rows.first()).toContainText('L12');
  await expect(rows.nth(1)).toContainText('docs/architecture.md');
  await expect(fullscreen).not.toContainText('This preview is loaded from the connected source');
  await rows.first().focus();
  await expect(rows.first()).toBeFocused();
  await rows.first().click();
  await expect(page.locator('.child-state[role="alert"]')).toBeVisible();
  await page.locator('.child-state button').click();
  await expect(rows.first()).toBeVisible();
  await open(page, 'ProjectReferenceEmbedFullscreen', 'empty');
  await expect(page.getByTestId('project-reference-empty')).toContainText('No file references found');
});
