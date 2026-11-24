import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed

const URL = '/dev/preview/embeds/slides/SlidesLivePair?chrome=0&theme=light&background=%23dbeafe&width=1000';
const MATE_URL = `${URL}&props=${encodeURIComponent(JSON.stringify({ mate: 'Atlas' }))}`;
test.use({ viewport: { width: 1100, height: 900 }, trace: 'retain-on-failure' });

async function open(page: import('@playwright/test').Page, url = URL) {
  await page.goto(url);
  await waitForComponentPreview(page);
  const a = page.getByTestId('slides-live-pane-a');
  const b = page.getByTestId('slides-live-pane-b');
  await expect(a.getByTestId('slides-editor')).toHaveAttribute('data-status', 'ready');
  await expect(b.getByTestId('slides-editor')).toHaveAttribute('data-status', 'ready');
  return { a, b };
}

// contract-test: supporting surface=gui.web assertions=live-collab.sync.concurrent-convergence,live-collab.core.one-shared-model
test('adding a slide in one editor appears in the other', async ({ page }, testInfo) => {
  const { a, b } = await open(page);
  await expect(b.getByTestId('slides-editor-strip-item')).toHaveCount(2);
  await a.getByTestId('slides-editor-add-slide').click();
  await expect(b.getByTestId('slides-editor-strip-item')).toHaveCount(3);
  await expect(a.getByTestId('slides-editor-strip-item')).toHaveCount(3);
  await testInfo.attach('converged-1000', { body: await page.getByTestId('slides-live-pair').screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=live-collab.presence.who-and-where
test('a peer selecting an element is outlined with their name', async ({ page }, testInfo) => {
  const { a, b } = await open(page);
  await expect(a.getByTestId('slides-editor')).toHaveAttribute('data-slide-id', 's1');
  await a.getByTestId('slides-editor-canvas').getByTestId('slides-editor-element').first().click();
  await expect(b.getByTestId('slides-editor-peer-selection')).toContainText('Mara');
  await testInfo.attach('peer-selection-1000', { body: await page.getByTestId('slides-live-pair').screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=live-collab.presence.who-and-where
test('an assistant peer shows "is editing here" on its slide', async ({ page }) => {
  const { a, b } = await open(page, MATE_URL);
  await b.getByTestId('slides-editor-canvas').getByTestId('slides-editor-element').first().click();
  await expect(a.getByTestId('slides-editor-mate-badge')).toContainText('Atlas');
});

// contract-test: supporting surface=gui.web assertions=live-collab.assistant.live-edits
test('the deck toolbar undoes the assistant edit and clears the undo state', async ({ page }, testInfo) => {
  const edited = `${URL}&props=${encodeURIComponent(JSON.stringify({ assistantEdit: true }))}`;
  const { a, b } = await open(page, edited);
  const undo = a.getByTestId('slides-editor-undo');
  await expect(undo).toBeEnabled();
  for (const pane of [a, b]) {
    await expect(pane.getByTestId('slides-editor-canvas')).toContainText('Updated quarterly review');
  }
  await testInfo.attach('assistant-edit-1000', { body: await a.screenshot(), contentType: 'image/png' });
  await undo.click();
  await expect(undo).toBeDisabled();
  for (const pane of [a, b]) {
    await expect(pane.getByTestId('slides-editor-canvas')).toContainText('Quarterly update');
  }
  await testInfo.attach('assistant-undo-1000', { body: await a.screenshot(), contentType: 'image/png' });
});
