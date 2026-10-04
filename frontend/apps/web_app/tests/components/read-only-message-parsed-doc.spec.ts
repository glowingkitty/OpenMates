import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const preview = (variant: string) =>
  `/dev/preview/ReadOnlyMessage?theme=light&background=%23dbeafe&width=520&chrome=0&variant=${variant}`;

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
test('keeps a parsed code embed after markdown-looking saved text', async ({ page }, testInfo) => {
  await page.goto(preview('parsedCode'));
  await waitForComponentPreview(page);
  const message = page.getByTestId('message-content');
  await expect(message).toContainText('STORAGE_CAPACITY_SCENARIO:round');
  await expect(message.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]'))
    .toBeVisible();
  const card = message.getByTestId('embed-preview');
  await expect(card.locator('.code-preview')).toContainText('const saved = 1;');
  const footerGeometry = await card.evaluate((element) => {
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
      footer: measure('[data-testid="embed-basic-infos-bar"]'),
    };
  });
  const { card: cardBox, footer: footerBox } = footerGeometry;
  expect(
    !!cardBox && !!footerBox && footerBox.top >= cardBox.top - 1 && footerBox.bottom <= cardBox.bottom + 1,
    `The code preview footer must remain within its card: ${JSON.stringify(footerGeometry)}`,
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
