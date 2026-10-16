import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const preview = (variant: string) =>
  `/dev/preview/ReadOnlyMessage?theme=light&background=%23dbeafe&width=520&chrome=0&variant=${variant}`;

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,chats.rendering.preview-info-top
test('keeps a parsed code embed after markdown-looking saved text', async ({ page }, testInfo) => {
  await page.goto(preview('parsedCode'));
  await waitForComponentPreview(page);
  const message = page.getByTestId('message-content');
  await expect(message).toContainText('STORAGE_CAPACITY_SCENARIO:round');
  await expect(message.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]'))
    .toBeVisible();
  const card = message.getByTestId('embed-preview');
  await expect(card.locator('.code-preview')).toContainText('const saved = 1;');
  const infoGeometry = await card.evaluate((element) => {
    const measure = (selector: string) => {
      const node = selector === ':scope' ? element : element.querySelector(selector);
      if (!node) return null;
      const bounds = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      return {
        top: Math.round(bounds.top), bottom: Math.round(bounds.bottom), height: Math.round(bounds.height),
        styleHeight: style.height, minHeight: style.minHeight, paddingTop: style.paddingTop,
        marginTop: style.marginTop, marginBottom: style.marginBottom, flex: style.flex,
      };
    };
    return {
      card: measure(':scope'), layout: measure('.desktop-layout'),
      details: measure('.details-section'), codeDetails: measure('.code-details'),
      info: measure('[data-testid="embed-basic-infos-bar"]'),
    };
  });
  const { card: cardBox, details: detailsBox, info: infoBox } = infoGeometry;
  expect(
    !!cardBox && !!detailsBox && !!infoBox &&
      infoBox.top >= cardBox.top - 1 && infoBox.bottom <= detailsBox.top + 1 &&
      detailsBox.bottom <= cardBox.bottom + 1,
    `The restored code preview must keep its info bar above the details within the card: ${JSON.stringify(infoGeometry)}`,
  ).toBe(true);
  await testInfo.attach('parsed-code-embed', {
    body: await message.screenshot(), contentType: 'image/png',
  });
});

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
test('keeps later paragraphs and inline nodes in an already parsed document', async ({ page }) => {
  await page.goto(preview('parsedParagraphs'));
  await waitForComponentPreview(page);
  const message = page.getByTestId('message-content');
  await expect(message).toContainText('STORAGE_CAPACITY_SCENARIO:round');
  await expect(message).toContainText('Later saved paragraph.');
  await expect(message.locator('.ProseMirror > p')).toHaveCount(2);

  await page.goto(preview('parsedInline'));
  await waitForComponentPreview(page);
  const inlineMessage = page.getByTestId('message-content');
  await expect(inlineMessage).toContainText('STORAGE_CAPACITY_SCENARIO:round with inline saved content.');

  await page.goto(preview('parsedMarkedSingle'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('message-content').locator('strong'))
    .toHaveText('Synthetic storage reference. STORAGE_CAPACITY_SCENARIO:round');
});

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
test('still reparses a legacy single raw markdown text node', async ({ page }) => {
  await page.goto(preview('legacySingleMarkdown'));
  await waitForComponentPreview(page);
  const message = page.getByTestId('message-content');
  await expect(message.locator('strong')).toHaveText('Legacy saved markdown');
});

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
test('renders stored user line breaks and each blank line with Markdown emphasis', async ({ page }) => {
  await page.goto(preview('multilineUser'));
  await waitForComponentPreview(page);
  const paragraphs = page.getByTestId('message-content').locator('.ProseMirror > p');
  await expect(paragraphs).toHaveCount(4);
  await expect(paragraphs.first().locator('strong')).toHaveText('social posts');
  await expect(paragraphs.first().locator('br')).toHaveCount(1);
  await expect(paragraphs.nth(1)).toHaveText('');
  await expect(paragraphs.nth(2)).toHaveText('');
  await expect(paragraphs.nth(3)).toHaveText('Include a short summary after the gap.');

  await page.goto(preview('multilineUserCode'));
  await waitForComponentPreview(page);
  const codeMessage = page.getByTestId('message-content');
  // Read-mode fenced code is a compact chip. Exact source whitespace is
  // covered by markdownParser.preprocess.test.ts; this bare preview exposes
  // the chip's fullscreen callback rather than an ActiveChat fullscreen host.
  const codeChip = codeMessage.getByRole('button', { name: 'Code snippet 6 lines, Svelte', exact: true });
  await expect(codeChip).toBeVisible();
  await expect(codeChip).toBeEnabled();
  await page.evaluate(() => {
    const target = window as typeof window & {
      savedCodeFullscreen?: { embedType: string; language: string; lineCount: number; hasEmbedId: boolean };
    };
    document.addEventListener('embedfullscreen', event => {
      const detail = (event as CustomEvent<{
        embedId?: string; embedType?: string; attrs?: { language?: string; lineCount?: number };
      }>).detail;
      target.savedCodeFullscreen = {
        embedType: detail.embedType ?? '',
        language: detail.attrs?.language ?? '',
        lineCount: detail.attrs?.lineCount ?? 0,
        hasEmbedId: typeof detail.embedId === 'string' && detail.embedId.length > 0,
      };
    }, { once: true });
  });
  await codeChip.click();
  await expect.poll(() => page.evaluate(() =>
    (window as typeof window & { savedCodeFullscreen?: unknown }).savedCodeFullscreen,
  )).toEqual({ embedType: 'code-code', language: 'svelte', lineCount: 6, hasEmbedId: true });
  await expect(codeMessage).toContainText('After the code.');
  await expect(codeMessage).not.toContainText(/EMPTY_PARAGRAPH|MATH_(?:INLINE|BLOCK)_\d+/);

  await page.goto(preview('multilineUserStructured'));
  await waitForComponentPreview(page);
  const structuredMessage = page.getByTestId('message-content');
  const orderedList = structuredMessage.locator('.ProseMirror > ol');
  await expect(orderedList).toHaveCount(1);
  await expect(orderedList.locator(':scope > li')).toHaveCount(2);
  await expect(orderedList.locator(':scope > li').first().locator(':scope > p')).toHaveCount(2);
  await expect(orderedList.locator('strong')).toHaveText('First');
  await expect(orderedList.locator('em')).toHaveText('emphasis');
  const bulletList = structuredMessage.locator('.ProseMirror > ul');
  await expect(bulletList).toHaveCount(1);
  await expect(bulletList.locator(':scope > li')).toHaveCount(2);
  await expect(bulletList.locator('strong')).toHaveText('Bullet first');
  const quote = structuredMessage.locator('.ProseMirror > blockquote');
  await expect(quote).toHaveCount(1);
  await expect(quote.locator(':scope > p')).toHaveCount(2);
  await expect(quote.locator('strong')).toHaveText('Quote first');
});
