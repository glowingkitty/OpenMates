import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
test.setTimeout(120_000);
// contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
test('natural request composer submits text with compatible files and preserves the draft on empty submit', async ({ page }) => {
  await page.goto('/dev/preview/apps/AppsRequestComposer?chrome=0&theme=light&width=390');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('apps-request-mic')).toBeVisible();
  await expect(page.getByTestId('apps-request-add-files')).toBeVisible();
  await page.getByTestId('apps-request-file-input').setInputFiles({ name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('quiet cafes') });
  await expect(page.getByTestId('apps-request-attachments')).toContainText('notes.txt');
  await page.getByTestId('apps-request-textarea').fill('Find quiet cafés in Berlin');
  const submitted = page.evaluate(() => new Promise(resolve => window.addEventListener('apps-request-preview-submit', event => resolve((event as CustomEvent).detail), { once: true })));
  await page.getByTestId('apps-request-submit').click();
  expect(await submitted).toEqual({ text: 'Find quiet cafés in Berlin', filenames: ['notes.txt'] });
  await expect(page.getByTestId('apps-request-textarea')).toHaveValue('');
  await expect(page.getByTestId('apps-request-attachments')).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
test('saved result fullscreen keeps typed cards, toggleable filters and a followup composer with native context', async ({ page }) => {
  await page.goto('/dev/preview/apps/AppsResultFullscreen?chrome=0&theme=light&width=390&variant=sharedResults');
  await waitForComponentPreview(page);
  const grid = page.getByTestId('search-template-grid');
  await expect(grid.getByTestId('embed-preview')).toHaveCount(12);
  // The grid can be ready while its fullscreen ancestor is still sliding in.
  await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
  const composer = page.getByTestId('apps-request-composer');
  const before = await composer.boundingBox();
  const contentArea = page.locator('.content-area').first();
  // An absolute fullscreen needs the same definite scrollport as the real Apps host.
  const scrollport = await contentArea.boundingBox();
  expect(scrollport?.height ?? 0).toBeGreaterThan(300);
  await contentArea.evaluate(element => element.scrollTop = element.scrollHeight);
  await expect(page.getByTestId('search-template-filter')).toHaveCount(0);
  await page.getByTestId('search-template-filter-button').click();
  await expect(page.getByTestId('search-template-filter-button')).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByTestId('search-template-filter')).toBeFocused();
  await expect(page.getByTestId('search-template-toolbar')).toBeInViewport();
  await expect(composer).toBeInViewport();
  const after = await composer.boundingBox();
  expect(Math.abs((before?.y ?? 0) - (after?.y ?? 0))).toBeLessThan(2);
  await page.getByTestId('search-template-filter').fill('books');
  await expect(grid.getByTestId('embed-preview')).toHaveCount(1);
  await expect(grid).toContainText('Cafe 1');
  await page.getByTestId('search-template-filter-button').click();
  await expect(page.getByTestId('search-template-filter')).toHaveCount(0);
  await expect(grid.getByTestId('embed-preview')).toHaveCount(1);
  await expect(page.getByTestId('search-template-query')).toHaveText('Saved cafes');
  for (const id of ['search-template-save-search', 'search-template-create-workflow']) {
    const action = page.getByTestId(id);
    await expect(action).toHaveCSS('text-decoration-line', 'none');
    await action.hover();
    await expect(action).toHaveCSS('text-decoration-line', 'none');
    await action.focus();
    await expect(action).toBeFocused();
    await expect(action).toHaveCSS('text-decoration-line', 'none');
  }
  const saved = page.evaluate(() => new Promise<unknown>(resolve => window.addEventListener('apps-result-preview-save', event => resolve((event as CustomEvent).detail), { once: true })));
  await page.getByTestId('search-template-save-search').click();
  expect(await saved).toMatchObject({ skill_id: 'search', input: { requests: [{ query: 'Saved cafes' }] } });
  await expect(page.getByTestId('search-template-save-search')).toHaveText('Saved search');
  await expect(page.getByTestId('search-template-save-search')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('search-template-save-search')).toBeDisabled();
  await expect(page.getByTestId('search-template-save-search').locator('.search-heart')).toHaveCSS('background-color', 'rgb(253, 80, 160)');
  await page.getByTestId('apps-request-textarea').fill('Which has outdoor seats?');
  const followup = page.evaluate(() => new Promise<unknown>(resolve => window.addEventListener('apps-result-preview-followup', event => resolve((event as CustomEvent).detail), { once: true })));
  await page.getByTestId('apps-request-submit').click();
  expect(await followup).toMatchObject({ text: 'Which has outdoor seats?', context: { skill_id: 'search', input: { requests: [{ query: 'Saved cafes' }] }, result: { results: expect.any(Array) } } });
});

// contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
test('fullscreen map collections reuse actual previews in a vertical grid with typed filters', async ({ page }) => {
  await page.goto('/dev/preview/embeds/EmbedsMapView?chrome=0&theme=light&width=390&variant=fullscreen');
  await waitForComponentPreview(page);
  const view = page.getByTestId('embeds-map-view');
  await expect(view.getByTestId('embeds-map-view-card')).toHaveCount(5);
  await expect(view.getByTestId('embeds-map-view-map')).toHaveAttribute('data-map-hydrated', 'true');
  const cards = view.getByTestId('embeds-map-view-card');
  const first = await cards.nth(0).boundingBox(); const second = await cards.nth(1).boundingBox();
  expect((second?.y ?? 0)).toBeGreaterThan((first?.y ?? 0));
  expect(Math.abs((first?.x ?? 0) - (second?.x ?? 0))).toBeLessThan(2);
  await expect(view.getByTestId('embeds-map-view-filter-button')).toBeVisible();
});

// contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
test('calendar collections initialize after real entries load and preserve subsequent user tab choice', async ({ page }) => {
  await page.goto('/dev/preview/embeds/EmbedsMapView?chrome=0&theme=light&width=1000&variant=fullscreenCalendar');
  await waitForComponentPreview(page);
  const view = page.getByTestId('embeds-map-view');
  await expect(view.getByTestId('embeds-results-view-tab-calendar')).toHaveAttribute('aria-selected', 'true');
  await expect(view.getByTestId('embeds-results-view-calendar')).toBeVisible();
  await expect(view.getByTestId('embeds-results-view-calendar-item')).toHaveCount(10);
  await view.getByTestId('embeds-results-view-tab-map').click();
  await expect(view.getByTestId('embeds-results-view-tab-map')).toHaveAttribute('aria-selected', 'true');
  await expect(view.getByTestId('embeds-map-view-map')).toBeVisible();
});

// contract-test: direct surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen
test('native paid audio transcription opens the shared recording fullscreen with its transcript', async ({ page }) => {
  await page.goto('/dev/preview/apps/AppsResultFullscreen?chrome=0&theme=light&width=390&variant=transcription');
  await waitForComponentPreview(page);
  await expect(page.getByText('The meeting starts at nine.', { exact: true })).toBeVisible();
  await expect(page.getByTestId('embed-header-title')).toContainText('Meeting notes');
  await expect(page.getByText('This result could not be opened.', { exact: true })).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=apps.results.shared-fullscreen,apps.recommendations.private-daily
test('reopened search fullscreen recognizes the saved native request without another save', async ({ page }) => {
  await page.goto('/dev/preview/apps/AppsResultFullscreen?chrome=0&theme=light&width=1000&variant=savedResults');
  await waitForComponentPreview(page);
  const saveSearch = page.getByTestId('search-template-save-search');
  await expect(saveSearch).toHaveText('Saved search');
  await expect(saveSearch).toHaveAttribute('aria-pressed', 'true');
  await expect(saveSearch).toBeDisabled();
  await expect(saveSearch.locator('.search-heart')).toHaveCSS('background-color', 'rgb(253, 80, 160)');
  await expect(page.getByTestId('search-template-create-workflow')).toBeVisible();
  await expect(page.getByTestId('search-template-filter')).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=apps.results.shared-fullscreen,apps.recommendations.private-daily
test('declining a guest search save leaves the search unsaved and retryable', async ({ page }) => {
  await page.goto('/dev/preview/apps/AppsResultFullscreen?chrome=0&theme=light&width=390&variant=guestSaveDeclined');
  await waitForComponentPreview(page);
  await page.evaluate(() => {
    const browser = window as Window & { signupAttempts?: number };
    browser.signupAttempts = 0;
    window.addEventListener('apps-result-preview-signup', () => { browser.signupAttempts = (browser.signupAttempts ?? 0) + 1; });
  });
  const saveSearch = page.getByTestId('search-template-save-search');
  for (const attempts of [1, 2]) {
    await saveSearch.click();
    await expect.poll(() => page.evaluate(() => (window as Window & { signupAttempts?: number }).signupAttempts)).toBe(attempts);
    await expect(saveSearch).toHaveText('Save this search');
    await expect(saveSearch).toHaveAttribute('aria-pressed', 'false');
    await expect(saveSearch).toBeEnabled();
  }
});
