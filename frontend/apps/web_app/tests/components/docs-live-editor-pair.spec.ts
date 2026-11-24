import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed

const URL = '/dev/preview/embeds/docs/DocsLiveEditorPair?chrome=0&theme=light&background=%23dbeafe&width=1000';
test.use({ viewport: { width: 1100, height: 800 }, trace: 'retain-on-failure' });

// Document text without remote caret overlays (their name labels are not content).
async function editorText(locator: import('@playwright/test').Locator): Promise<string> {
  return locator.evaluate((root) => {
    const clone = root.cloneNode(true) as HTMLElement;
    clone
      .querySelectorAll('.collaboration-carets__caret, .collaboration-carets__label, .collaboration-cursor__caret, .cm-ySelectionCaret, .cm-ySelectionInfo, .cm-ySelectionCaretDot')
      .forEach((node) => node.remove());
    const blocks = clone.querySelectorAll('p, h1, h2, h3, h4, h5, h6, li, .cm-line');
    const lines = blocks.length ? Array.from(blocks, (node) => node.textContent ?? '') : [clone.textContent ?? ''];
    return lines.join('\n').trim();
  });
}

async function open(page: import('@playwright/test').Page) {
  await page.goto(URL);
  await waitForComponentPreview(page);
  const a = page.getByTestId('docs-live-pane-a').getByTestId('docs-editor-content');
  const b = page.getByTestId('docs-live-pane-b').getByTestId('docs-editor-content');
  await expect(a).toBeVisible();
  await expect(b).toBeVisible();
  return { a, b };
}

// contract-test: supporting surface=gui.web assertions=live-collab.sync.concurrent-convergence,live-collab.core.one-shared-model
test('typing in one pane appears in the other', async ({ page }, testInfo) => {
  const { a, b } = await open(page);
  await a.click();
  await page.keyboard.type('Hello from Mara');
  await expect(b).toContainText('Hello from Mara');
  await testInfo.attach('typed-in-a-1000', { body: await page.getByTestId('docs-live-pair').screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=live-collab.sync.concurrent-convergence
test('concurrent edits in both panes are both kept and identical', async ({ page }, testInfo) => {
  const { a, b } = await open(page);
  await a.click();
  await page.keyboard.type('Start');
  await expect(b).toContainText('Start');
  await page.keyboard.press('Enter');
  await page.keyboard.type('Middle');
  await expect(b).toContainText('Middle');
  // A types at the end; B types at the very start, without waiting between them.
  await a.click();
  await page.keyboard.press('Control+End');
  await page.keyboard.type(' alpha');
  await b.click();
  await page.keyboard.press('Control+Home');
  await page.keyboard.type('beta ');
  await expect.poll(async () => editorText(a)).toContain('alpha');
  await expect.poll(async () => editorText(a)).toContain('beta');
  await expect.poll(async () => (await editorText(a)) === (await editorText(b))).toBe(true);
  await testInfo.attach('converged-1000', { body: await page.getByTestId('docs-live-pair').screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=live-collab.sync.concurrent-convergence
test('bold formatting syncs to the other pane', async ({ page }) => {
  const { a, b } = await open(page);
  await a.click();
  await page.getByTestId('docs-live-pane-a').getByTestId('docs-editor-bold').click();
  await page.keyboard.type('strong');
  await expect(b.locator('strong')).toHaveText('strong');
});

// contract-test: supporting surface=gui.web assertions=live-collab.presence.who-and-where
test('the other person shows as a named caret and a header avatar', async ({ page }, testInfo) => {
  const { a, b } = await open(page);
  await a.click();
  await page.keyboard.type('Where is Mara');
  await expect(b).toContainText('Where is Mara');
  await expect(page.getByTestId('docs-live-pane-b').locator('.collaboration-carets__label')).toHaveText('Mara');
  await expect(page.getByTestId('docs-live-pane-b').getByTestId('live-peer')).toHaveCount(1);
  await testInfo.attach('remote-caret-1000', { body: await page.getByTestId('docs-live-pair').screenshot(), contentType: 'image/png' });
});
