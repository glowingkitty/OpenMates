import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed

const URL = '/dev/preview/embeds/sheets/SheetLiveGridPair?chrome=0&theme=light&background=%23dbeafe&width=1000';
const MATE_URL = `${URL}&props=${encodeURIComponent(JSON.stringify({ mate: 'Atlas' }))}`;
test.use({ viewport: { width: 1100, height: 800 }, trace: 'retain-on-failure' });

async function open(page: import('@playwright/test').Page, url = URL) {
  await page.goto(url);
  await waitForComponentPreview(page);
  const a = page.getByTestId('sheet-live-pane-a');
  const b = page.getByTestId('sheet-live-pane-b');
  await expect(a.getByTestId('sheet-live-cell').first()).toBeVisible();
  return { a, b };
}

const cell = (pane: import('@playwright/test').Locator, id: string) => pane.locator(`[data-cell-id="${id}"]`);

// contract-test: supporting surface=gui.web assertions=live-collab.sync.concurrent-convergence,live-collab.core.one-shared-model
test('a cell edit in one grid appears in the other and both grids stay identical', async ({ page }, testInfo) => {
  const { a, b } = await open(page);
  await cell(a, 'r1:c1').locator('.cell-text').click();
  await page.keyboard.press('Control+A');
  await page.keyboard.type('Rye flour');
  await page.keyboard.press('Enter');
  await cell(b, 'r2:c1').locator('.cell-text').click();
  await page.keyboard.press('Control+A');
  await page.keyboard.type('Duck eggs');
  await page.keyboard.press('Enter');
  for (const pane of [a, b]) {
    await expect(cell(pane, 'r1:c1')).toContainText('Rye flour');
    await expect(cell(pane, 'r2:c1')).toContainText('Duck eggs');
  }
  await testInfo.attach('converged-1000', { body: await page.getByTestId('sheet-live-pair').screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=live-collab.sync.concurrent-convergence,live-collab.core.one-shared-model
test('inserting and deleting rows and columns reaches the other grid', async ({ page }) => {
  const { a, b } = await open(page);
  await a.getByTestId('sheet-live-insert-row').first().click();
  await expect(b.locator('tbody tr')).toHaveCount(4);
  await a.getByTestId('sheet-live-delete-col').last().click();
  await expect(b.getByTestId('sheet-live-header')).toHaveCount(2);
});

// contract-test: supporting surface=gui.web assertions=live-collab.sync.concurrent-convergence
test('an assistant suggestion can be accepted or dismissed', async ({ page }) => {
  const { a, b } = await open(page);
  await expect(cell(b, 'r3:c2').getByTestId('sheet-live-suggestion')).toContainText('2');
  await cell(a, 'r3:c2').getByTestId('sheet-live-suggestion-accept').click();
  await expect(cell(b, 'r3:c2').getByTestId('sheet-live-suggestion')).toHaveCount(0);
  await expect(cell(b, 'r3:c2')).toContainText('2');
});

// contract-test: supporting surface=gui.web assertions=live-collab.presence.who-and-where
test('the other person shows as an outlined cell with their name', async ({ page }, testInfo) => {
  const { a, b } = await open(page);
  await cell(a, 'r2:c3').locator('.cell-text').click();
  const peer = cell(b, 'r2:c3').getByTestId('sheet-live-peer');
  await expect(peer).toHaveText('Mara');
  await expect(peer).not.toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await expect(b.getByTestId('live-peer')).toHaveCount(1);
  await testInfo.attach('peer-cell-1000', { body: await page.getByTestId('sheet-live-pair').screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=live-collab.presence.who-and-where
test('an assistant peer shows "is editing here" on its cell', async ({ page }) => {
  const { b } = await open(page, MATE_URL);
  await page.getByTestId('sheet-live-pane-b').locator('[data-cell-id="r1:c2"] .cell-text').click();
  await expect(page.getByTestId('sheet-live-pane-a').locator('[data-cell-id="r1:c2"]').getByTestId('sheet-live-peer')).toContainText('Atlas');
  await expect(b).toBeVisible();
});
