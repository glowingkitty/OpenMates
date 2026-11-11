import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=isolated_component_preview
const LIST = '/dev/preview/settings/MemoryList?chrome=0&theme=light';
const ENTRY = '/dev/preview/settings/MemoryEntryPage?chrome=0&theme=light';
const COLD_START_MS = 75_000;

test.beforeEach(async ({ page }) => {
  test.setTimeout(COLD_START_MS + 30_000);
  await page.addInitScript(() => {
    for (const name of ['memory-preview-create', 'memory-preview-open', 'memory-preview-renew', 'memory-preview-cancel']) {
      window.addEventListener(name, (event) => {
        document.documentElement.dataset.memoryPreviewEvent = `${name}:${String((event as CustomEvent).detail ?? '')}`;
      });
    }
  });
});

const titles = (page: import('@playwright/test').Page) => page.getByTestId('memory-row-title').allTextContents();

// contract-test: supporting surface=gui.web assertions=app-memories.document.canonical-shape,app-memories.expiry.client-enforced
test('lists memories as settings rows sorted by last change, with app icons, dates and Renew', async ({ page }, testInfo) => {
  await page.goto(`${LIST}&width=650`);
  await waitForComponentPreview(page, COLD_START_MS);
  const rows = page.getByTestId('memory-row');
  await expect(rows).toHaveCount(5);
  await expect(page.getByTestId('memory-sort')).toHaveValue('modified');
  expect(await titles(page)).toEqual([
    'Window seat on long flights',
    'Kitchen renovation: keep the original oak floor, prefer matte black fittings and leave room for a second oven later',
    'Svelte component habits', 'Summer train pass', 'Writing tone',
  ]);
  const trip = rows.filter({ hasText: 'Window seat' });
  await expect(trip).toContainText(/Private · Modified /);
  await expect(trip.getByTestId('memory-row-icon')).toHaveClass(/app-travel/);
  const untimed = rows.filter({ hasText: 'Writing tone' });
  await expect(untimed.getByTestId('memory-row-subtitle')).toHaveText('Private');
  await expect(untimed.getByTestId('memory-row-icon')).toHaveClass(/settings_memories/);
  await expect(rows.filter({ hasText: 'Summer train pass' })).toContainText('Expired');
  await expect(page.getByTestId('memory-renew')).toHaveCount(1);
  await expect(page.getByTestId('memory-char-budget')).toContainText('/ 64000 characters used');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await testInfo.attach('memory-list-default', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });

  await page.getByTestId('memory-sort').selectOption('added');
  expect((await titles(page))[0]).toMatch(/^Kitchen renovation/);
  await page.getByTestId('memory-sort').selectOption('title');
  expect(await titles(page)).toEqual([
    'Kitchen renovation: keep the original oak floor, prefer matte black fittings and leave room for a second oven later',
    'Summer train pass', 'Svelte component habits', 'Window seat on long flights', 'Writing tone',
  ]);
  await page.getByTestId('memory-search').fill('svelte');
  await expect(rows).toHaveCount(1);
  await testInfo.attach('memory-list-title-sort-search', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });

  await page.getByTestId('memory-search').fill('');
  await page.getByTestId('memory-renew').click();
  await expect(page.locator('html')).toHaveAttribute('data-memory-preview-event', 'memory-preview-renew:personal:expired');
  await rows.filter({ hasText: 'Svelte component habits' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-memory-preview-event', 'memory-preview-open:personal:code');
  await page.getByTestId('memory-create').click();
  await expect(page.locator('html')).toHaveAttribute('data-memory-preview-event', 'memory-preview-create:');
});

// contract-test: supporting surface=gui.web assertions=app-memories.document.canonical-shape
test('shows empty and saved states with canonical elements', async ({ page }, testInfo) => {
  await page.goto(`${LIST}&variant=empty&width=390`);
  await waitForComponentPreview(page, COLD_START_MS);
  await expect(page.getByTestId('memory-row')).toHaveCount(0);
  await expect(page.getByTestId('memory-create')).toBeVisible();
  await expect(page.getByText('No Memories saved here yet.')).toBeVisible();
  await testInfo.attach('memory-list-empty', { body: await page.screenshot(), contentType: 'image/png' });
  await page.goto(`${LIST}&variant=saved&width=390`);
  await waitForComponentPreview(page, COLD_START_MS);
  await expect(page.getByTestId('rule-saved-notice')).toHaveText('Memory saved.');
});

// contract-test: supporting surface=gui.web assertions=app-memories.document.canonical-shape,app-memories.references.embeds
test('create page uses the standard field pattern with Title, Memory, When to use and App', async ({ page }, testInfo) => {
  await page.goto(`${ENTRY}&width=650`);
  await waitForComponentPreview(page, COLD_START_MS);
  const entry = page.getByTestId('memory-entry-page');
  await expect(entry).toHaveAttribute('data-new', 'true');
  for (const [field, label] of [['title', 'Title'], ['memory', 'Memory'], ['when-to-use', 'When to use (optional)'], ['app', 'App']]) {
    await expect(page.getByTestId(`memory-field-${field}`)).toHaveText(label);
  }
  await expect(entry).not.toContainText('Markdown');
  await expect(page.getByTestId('memory-app')).toHaveValue('');
  await expect(page.getByTestId('memory-delete')).toHaveCount(0);
  await page.getByTestId('rule-title').fill('Seat choice');
  await page.getByTestId('rule-body').click();
  await page.keyboard.type('Window seat.');
  await page.getByTestId('memory-app').selectOption('travel');
  await testInfo.attach('memory-create-page', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
  await page.getByTestId('rule-save').click();
  const saved = JSON.parse(await page.locator('html').getAttribute('data-memory-preview-saved') ?? '{}');
  expect(saved).toMatchObject({ title: 'Seat choice', app_id: 'travel' });
  await page.getByTestId('rule-cancel').click();
  await expect(page.locator('html')).toHaveAttribute('data-memory-preview-event', 'memory-preview-cancel:');
});

// contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
test('edit page shows the stored app, and a suggestion shows the unsaved diff', async ({ page }, testInfo) => {
  await page.goto(`${ENTRY}&variant=edit&width=650`);
  await waitForComponentPreview(page, COLD_START_MS);
  await expect(page.getByTestId('rule-title')).toHaveValue('Window seat on long flights');
  await expect(page.getByTestId('memory-app')).toHaveValue('travel');
  await expect(page.getByTestId('memory-delete')).toBeVisible();
  await page.getByTestId('memory-app').selectOption('');
  await page.getByTestId('rule-save').click();
  expect(JSON.parse(await page.locator('html').getAttribute('data-memory-preview-saved') ?? '{}')).not.toHaveProperty('app_id');

  await page.goto(`${ENTRY}&variant=suggestion&width=650`);
  await waitForComponentPreview(page, COLD_START_MS);
  await expect(page.getByTestId('memory-draft-banner')).toBeVisible();
  await expect(page.getByTestId('memory-draft-diff-title')).toContainText('Window seat on long flights');
  await expect(page.getByTestId('memory-draft-diff-body')).toBeVisible();
  await expect(page.getByTestId('memory-draft-diff-when_to_use')).toHaveCount(0);
  await testInfo.attach('memory-suggestion-diff', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });

  await page.goto(`${ENTRY}&variant=error&width=650`);
  await waitForComponentPreview(page, COLD_START_MS);
  await expect(page.getByTestId('memory-error-text')).toHaveText('Could not load or save the Memories. Please try again.');
});
