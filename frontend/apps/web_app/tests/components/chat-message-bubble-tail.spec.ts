// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const tailStyle = (element: Element, selector: string) => {
  const bubble = element.querySelector(selector)!;
  const style = getComputedStyle(bubble, '::before');
  return { classes: bubble.className, rootClasses: element.className, transform: style.transform, width: style.width, height: style.height, top: style.top,
    left: style.left, clipPath: style.clipPath };
};

for (const width of [390, 820]) {
  for (const theme of ['light', 'dark']) {
    // contract-test: direct surface=gui.web assertions=video-call.chat.assistant-identity
    test(`Assistant and user bubble tails attach to the bubble at ${width}px in ${theme}`, async ({ page }, testInfo) => {
      test.setTimeout(60_000);
      await page.setViewportSize({ width: 1280, height: 900 });
      for (const variant of ['assistant', 'user']) {
        const params = new URLSearchParams({ chrome: '0', theme, background: '#dbeafe',
          width: String(width), props: JSON.stringify({ containerWidth: width }) });
        if (variant === 'assistant') params.set('variant', 'assistant');
        await page.goto(`/dev/preview/ChatMessage?${params}`);
        const canvas = await waitForComponentPreview(page);
        const message = canvas.locator('.chat-message');
        const selector = variant === 'assistant' ? '.mate-message-content' : '.user-message-content';
        const tail = await message.evaluate(tailStyle, selector);
        if (variant === 'assistant' && width <= 500) {
          // Stacked: avatar above, tail is an unrotated upward triangle overlapping the bubble's top edge.
          expect(tail, JSON.stringify(tail)).toMatchObject({ transform: 'none' });
          expect(tail.width).toBe('20px');
          expect(tail.height).toBe('13px');
          expect(tail.top).toBe('-10px');
          expect(tail.left).toBe('20px');
        } else if (variant === 'assistant') {
          expect(tail.width).toBe('13px');
          expect(tail.left).toBe('-10px');
        }
        await testInfo.attach(`${variant}-${width}-${theme}`, {
          body: await message.screenshot(), contentType: 'image/png' });
      }
    });
  }
}
