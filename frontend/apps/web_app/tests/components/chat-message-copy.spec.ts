// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

test.use({ hasTouch: true });

const response = 'This is the **complete response**.\n\n- Keep the first item.\n- Keep the second item.\n\nThe final paragraph must be copied too.';
const copySvg = readFileSync(resolve(__dirname, '../../../../packages/ui/static/icons/copy.svg'), 'utf8');
const copyPaths = Array.from(copySvg.matchAll(/<path\b[^>]*\bd="([^"]+)"/g), match => match[1]);

function previewUrl(width: number, theme: string, props: Record<string, unknown> = {}, variant = 'assistant') {
  return `/dev/preview/ChatMessage?${new URLSearchParams({
    chrome: '0', width: String(width), theme, background: '#dbeafe', variant,
    props: JSON.stringify({ containerWidth: width, ...props }),
  })}`;
}

// contract-test: supporting surface=gui.web assertions=chats.layout.responsive-history,chats.streaming.web-chunk-fade
test('assistant copy link fits both themes and widths and copies the entire selected response', async ({ page, context }) => {
  test.setTimeout(90_000);
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.setViewportSize({ width: 1280, height: 900 });

  for (const width of [820, 390]) {
    for (const theme of ['light', 'dark']) {
      await test.step(`Copy message at ${width}px in ${theme}`, async () => {
        await page.goto(previewUrl(width, theme, {
          content: response,
          original_message: { role: 'assistant', chat_id: 'preview-copy-chat', created_at: 1, content: response },
        }));
        const canvas = await waitForComponentPreview(page);
        const content = canvas.getByTestId('mate-message-content');
        await expect(content).toContainText('The final paragraph must be copied too.');
        const footer = canvas.getByTestId('generated-by-container');
        const copy = footer.getByRole('button', { name: 'Copy message', exact: true });
        const model = footer.getByTestId('generated-by');
        await expect(copy).toBeVisible();
        await expect(copy).toHaveText('Copy message');
        expect(await model.evaluate(element => element.nextElementSibling?.getAttribute('data-testid'))).toBe('copy-message-button');

        const modelStyle = await model.evaluate(element => {
          const style = getComputedStyle(element);
          return { color: style.color, fontSize: style.fontSize };
        });
        await expect(copy).toHaveCSS('color', modelStyle.color);
        await expect(copy).toHaveCSS('font-size', modelStyle.fontSize);
        await expect(copy).toHaveCSS('background-image', 'none');
        const icon = copy.locator('.icon_copy');
        await expect(icon).toBeVisible();
        await expect(icon).toHaveCSS('background-color', modelStyle.color);
        await expect(icon).toHaveCSS('background-image', 'none');
        // Vite may inline the URL; compare the rendered asset's SVG paths.
        const actualCopyPaths = await icon.evaluate(async element => {
          const url = getComputedStyle(element).maskImage.match(/^url\(["']?(.*?)["']?\)$/)?.[1];
          if (!url) return null;
          const svg = await (await fetch(url)).text();
          return Array.from(new DOMParser().parseFromString(svg, 'image/svg+xml').querySelectorAll('path'),
            path => path.getAttribute('d'));
        });
        expect(actualCopyPaths).toEqual(copyPaths);
        const iconBounds = (await icon.boundingBox())!;
        const thumbBounds = (await footer.locator('.icon_thumbsdown').boundingBox())!;
        expect(iconBounds.width).toBe(thumbBounds.width);
        expect(iconBounds.height).toBe(thumbBounds.height);
        expect(iconBounds.width).toBe(16);
        const copyBounds = (await copy.boundingBox())!;
        const footerBounds = (await footer.boundingBox())!;
        expect(copyBounds.x).toBeGreaterThanOrEqual(footerBounds.x);
        expect(copyBounds.x + copyBounds.width).toBeLessThanOrEqual(footerBounds.x + footerBounds.width + 1);
        expect(await canvas.locator('.chat-message').evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);

        await copy.hover();
        await expect(copy).toHaveCSS('text-decoration-line', 'none');
        await expect(copy).toHaveCSS('color', modelStyle.color);
        await page.evaluate(() => navigator.clipboard.writeText('previous clipboard contents'));
        await copy.click();
        await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(response);

        // Enter the existing text-selection mode, then activate the footer with
        // the keyboard. A full-message action must ignore that partial selection.
        await content.locator('p').first().click({ button: 'right', position: { x: 10, y: 10 } });
        await page.getByTestId('message-context-menu').locator('.menu-item.select').click();
        // Select already chooses the word at the pointer through the editor.
        // Wait for that native selection instead of racing it with a DOM Range.
        await expect.poll(() => page.evaluate(() => window.getSelection()!.toString()))
          .toBe('This');
        await model.focus();
        await page.keyboard.press('Tab');
        await expect(copy).toBeFocused();
        await expect(copy).toHaveCSS('outline-style', 'solid');
        await expect(copy).toHaveCSS('text-decoration-line', 'none');
        await page.evaluate(() => navigator.clipboard.writeText('replace this partial selection'));
        await copy.press('Enter');
        await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(response);
      });
    }
  }
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.streaming.web-chunk-fade
test('copy uses readable text without a stored original and respects hidden personal data', async ({ page, context }) => {
  test.setTimeout(60_000);
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  const cases = [
    { props: { content: response, original_message: null }, expected: response },
    { props: { original_message: null, content: { type: 'doc', content: [
      { type: 'paragraph', content: [{ type: 'text', text: 'A formatted response.' }] },
      { type: 'paragraph', content: [{ type: 'text', text: 'Final paragraph.' }] },
    ] } }, expected: 'A formatted response.\n\nFinal paragraph.' },
    ...[false, true].map(piiRevealed => ({
      props: { content: 'Contact [EMAIL_1_com].',
        original_message: { role: 'assistant', chat_id: 'preview-copy-chat', created_at: 1, content: 'Contact [EMAIL_1_com].' },
        piiMappings: [{ placeholder: '[EMAIL_1_com]', original: 'alex@example.com', type: 'EMAIL' }], piiRevealed },
      expected: piiRevealed ? 'Contact alex@example.com.' : 'Contact [EMAIL_1_com].',
    })),
  ];
  for (const { props, expected } of cases) {
    await page.goto(previewUrl(820, 'light', props));
    const canvas = await waitForComponentPreview(page);
    await canvas.getByTestId('copy-message-button').click();
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(expected);
  }
});

// contract-test: supporting surface=gui.web assertions=chat-processing-feedback.turn-lifecycle
test('user and active assistant messages do not offer the completed-response copy link', async ({ page }) => {
  test.setTimeout(60_000);
  for (const variant of ['streaming', 'processing', 'responseThinking']) {
    await page.goto(previewUrl(390, 'light', {}, variant));
    const canvas = await waitForComponentPreview(page);
    await expect(canvas.getByTestId('using-model')).toBeVisible();
    await expect(canvas.getByTestId('copy-message-button')).toHaveCount(0);
  }
  await page.goto('/dev/preview/ChatMessage?chrome=0');
  const canvas = await waitForComponentPreview(page);
  await expect(canvas.getByTestId('user-message-content')).toBeVisible();
  await expect(canvas.getByTestId('copy-message-button')).toHaveCount(0);
});
