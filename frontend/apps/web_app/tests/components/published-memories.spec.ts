import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const DETAIL = '/dev/preview/settings/PublishedMemoryDetail?chrome=0&theme=light&background=%23dbeafe&width=350';

// contract-test: supporting surface=gui.web assertions=app-memories.catalog.declared-types-only,app-memories.transparency.loaded-set
test('shows the exact read-only app Memory with its automatic loading scope at phone width', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(DETAIL);
  await waitForComponentPreview(page);
  await expect(page.getByText('Mobile first design', { exact: true })).toBeVisible();
  await expect(page.getByRole('status')).toHaveText('Public · Provided by the app · Read-only · Loads automatically when relevant');
  const body = page.getByTestId('published-memory-body');
  await expect(body.locator('pre')).toHaveText('- Start with the smallest screen.\n- Keep the primary action visible.\n- Make touch targets large enough to use comfortably.');
  await expect(page.getByRole('textbox')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /save|delete|edit/i })).toHaveCount(0);
  await page.getByRole('button', { name: 'Copy to clipboard' }).focus();
  expect(await body.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  const bounds = await body.boundingBox();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  await expect(body).toBeInViewport();
  await expect(page.getByText('Mobile first design', {exact: true})).toBeInViewport();
  await testInfo.attach('published-memory-phone', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=app-memories.catalog.declared-types-only,app-memories.discovery.visibility-cards
test('discovers the actual Code and Design Memory catalogs in the existing Memories hub', async ({ page }, testInfo) => {
  await page.setViewportSize({width: 900, height: 1400});
  await page.goto('/dev/preview/settings/SettingsMemoriesHub?chrome=0&theme=light&background=%23dbeafe&width=700');
  await waitForComponentPreview(page);
  const hubBounds = await page.locator('.settings-memories-hub').boundingBox();
  expect(hubBounds!.x).toBeGreaterThanOrEqual(0);
  expect(hubBounds!.x + hubBounds!.width).toBeLessThanOrEqual(900);
  for (const [appId, id, title] of [['code', 'javascript', 'JavaScript best practices'], ['code', 'typescript', 'TypeScript best practices'], ['code', 'svelte', 'Svelte best practices'], ['code', 'python', 'Python best practices'], ['design', 'mobile-first', 'Mobile first design'], ['design', 'accessibility', 'Accessibility best practices']]) {
    const card = page.getByTestId(`published-memory-${appId}-published_${id}`);
    await card.scrollIntoViewIfNeeded();
    await expect(card).toBeInViewport();
    await expect(card.getByTestId('app-card-name')).toHaveText(title);
    await expect(card.getByTestId('memory-card-visibility')).toHaveText('Public');
    expect((await card.boundingBox())!.width).toBe(223);
  }
  await expect(page.getByTestId('memory-card-visibility').filter({hasText: 'Public'})).toHaveCount(6);
  const privateCard = page.locator('[data-testid^="private-memory-"]').first();
  await expect(privateCard.getByTestId('memory-card-visibility')).toHaveText('Private');
  expect((await privateCard.boundingBox())!.width).toBe(223);
  await page.getByTestId('published-memory-code-published_javascript').scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await testInfo.attach('published-memory-hub', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=app-memories.catalog.declared-types-only,app-memories.discovery.visibility-cards
test('shows published Code Memories beside existing private memory types in app details', async ({ page }, testInfo) => {
  await page.goto('/dev/preview/settings/AppDetails?chrome=0&theme=light&background=%23dbeafe&width=700');
  await waitForComponentPreview(page);
  await expect(page.getByText('Public memories are provided by apps and load automatically when relevant. Private memories are encrypted. Personal memories are shared with your approval or an explicit mention; Project memories load with active Project access.', {exact: true})).toBeVisible();
  expect((await page.locator('.app-details').boundingBox())!.width).toBeLessThanOrEqual(700);
  const carousel = page.getByTestId('settings-memory-cards-scroll');
  for (const id of ['javascript', 'typescript', 'svelte', 'python']) {
    const card = carousel.getByTestId(`published-memory-${id}`);
    await card.scrollIntoViewIfNeeded();
    await expect(card).toBeInViewport();
    await expect(card.getByTestId('memory-card-visibility')).toHaveText('Public');
    expect((await card.boundingBox())!.width).toBe(223);
  }
  const privateCard = carousel.getByTestId('app-store-card').first();
  await privateCard.scrollIntoViewIfNeeded();
  await expect(privateCard).toBeInViewport();
  await expect(privateCard.getByTestId('memory-card-visibility')).toHaveText('Private');
  expect((await privateCard.boundingBox())!.width).toBe(223);
  await page.getByTestId('published-memory-javascript').scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await testInfo.attach('published-code-app-details', {body: await page.screenshot(), contentType: 'image/png'});
});

// contract-test: supporting surface=gui.web assertions=app-memories.discovery.visibility-cards
test('keeps public and private Memory cards and their explanation inside the phone viewport', async ({page}, testInfo) => {
  await page.setViewportSize({width: 390, height: 844});
  await page.goto('/dev/preview/settings/AppDetails?chrome=0&theme=light&background=%23dbeafe&width=350');
  await waitForComponentPreview(page);
  const explanation = page.locator('.section-description');
  const bounds = await explanation.boundingBox();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  const publicCard = page.getByTestId('published-memory-javascript');
  await publicCard.scrollIntoViewIfNeeded();
  await expect(publicCard).toBeInViewport();
  await expect(publicCard.getByTestId('memory-card-visibility')).toHaveText('Public');
  const privateCard = page.getByTestId('settings-memory-cards-scroll').getByTestId('app-store-card').first();
  await privateCard.scrollIntoViewIfNeeded();
  await expect(privateCard).toBeInViewport();
  await expect(privateCard.getByTestId('memory-card-visibility')).toHaveText('Private');
  await testInfo.attach('private-memory-app-details-phone', {body: await page.screenshot(), contentType: 'image/png'});
});

// contract-test: supporting surface=gui.web assertions=app-memories.catalog.declared-types-only
test('renders an actual published category through the existing memory route component', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await page.goto('/dev/preview/settings/AppSettingsMemoriesCategory?chrome=0&theme=light&background=%23dbeafe&width=350');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('app-settings-memories-category')).toHaveAttribute('data-app-id', 'design');
  await expect(page.getByText('Mobile first design', {exact: true})).toBeInViewport();
  await expect(page.getByTestId('published-memory-body')).toContainText('Begin with the smallest intended layout');
  const bounds = await page.getByTestId('published-memory-body').boundingBox();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  await expect(page.getByRole('button', {name: /save|delete|edit/i})).toHaveCount(0);
});
