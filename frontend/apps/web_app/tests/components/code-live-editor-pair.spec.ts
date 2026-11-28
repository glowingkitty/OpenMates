import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed

const URL = '/dev/preview/embeds/code/CodeLiveEditorPair?chrome=0&theme=light&background=%23dbeafe&width=1000';
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
  const a = page.getByTestId('code-live-pane-a').getByTestId('code-editor-textarea');
  const b = page.getByTestId('code-live-pane-b').getByTestId('code-editor-textarea');
  await expect(a).toContainText('return a + b;');
  await expect(b).toContainText('return a + b;');
  return { a, b };
}

// contract-test: supporting surface=gui.web assertions=live-collab.sync.concurrent-convergence,live-collab.core.one-shared-model
test('a line inserted at the top in B keeps A edit and A cursor on its line', async ({ page }, testInfo) => {
  const { a, b } = await open(page);
  await a.focus();
  await page.keyboard.press('Control+Home');
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('End');
  await page.keyboard.type(' // A');
  await b.focus();
  await page.keyboard.press('Control+Home');
  await page.keyboard.type('// header\n');
  await expect(b).toContainText('// A');
  await expect(a).toContainText('// header');
  await expect.poll(async () => (await editorText(a)) === (await editorText(b))).toBe(true);
  // A keeps typing: the text lands on the same line as before, not shifted by B's insert.
  await a.focus();
  await page.keyboard.type('X');
  const lines = (await editorText(a)).split('\n');
  expect(lines[0]).toContain('// header');
  expect(lines.find((l) => l.includes('return a + b;'))).toContain('// AX');
  await testInfo.attach('top-insert-1000', { body: await page.getByTestId('code-live-pair').screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=live-collab.presence.who-and-where
test('the other person shows as a remote cursor and a header avatar', async ({ page }, testInfo) => {
  const { a } = await open(page);
  await a.focus();
  await page.keyboard.press('Control+Home');
  await page.keyboard.press('ArrowDown');
  await page.keyboard.type('x');
  await expect(page.getByTestId('code-live-pane-b').locator('.cm-ySelectionCaret')).toHaveCount(1);
  await expect(page.getByTestId('code-live-pane-b').getByTestId('live-peer')).toHaveCount(1);
  await testInfo.attach('remote-cursor-1000', { body: await page.getByTestId('code-live-pair').screenshot(), contentType: 'image/png' });
});
