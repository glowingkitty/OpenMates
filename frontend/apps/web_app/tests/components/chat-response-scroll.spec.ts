// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

for (const [width, headerFirst] of [[1024, true], [390, false]] as const) {
  // contract-test: supporting surface=gui.web assertions=chats.layout.responsive-history,chats.rendering.assistant-document-convergence
  test(`reveals the response after both header and stream are ready at ${width}px`, async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width, height: 760 });
    await page.goto(`/dev/preview/ChatResponseScrollHarness?theme=light&width=${width}&chrome=0`);
    await waitForComponentPreview(page, 60_000);
    const container = page.getByTestId('chat-history-container');
    const user = page.getByTestId('message-user');
    const assistant = page.getByTestId('message-assistant');
    await page.getByTestId('send-prompt').click();
    await expect(user).toContainText('First requirement.');

    await page.getByTestId(headerFirst ? 'update-header' : 'stream-response').click();
    if (headerFirst) await expect(page.getByText('A clear summary', { exact: true })).toBeVisible();
    else await expect(assistant).toContainText('Here is the beginning');
    // Flush layout before proving that only one prerequisite cannot move the view.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    expect(await container.evaluate(element => element.scrollTop)).toBe(0);

    await page.getByTestId(headerFirst ? 'stream-response' : 'update-header').click();
    await expect(assistant).toContainText('Here is the beginning');
    await expect(container).toHaveAttribute('data-scroll-state', 'ready');
    const geometry = await user.locator('.ProseMirror').evaluate(element => {
      const container = element.closest('[data-testid="chat-history-container"]')!;
      const lineHeight = parseFloat(getComputedStyle(element.querySelector('p')!).lineHeight);
      const text = element.getBoundingClientRect();
      const viewport = container.getBoundingClientRect();
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
      const readableLines: string[] = [];
      while (walker.nextNode()) {
        const node = walker.currentNode;
        if (!node.textContent?.trim()) continue;
        const range = document.createRange();
        range.selectNodeContents(node);
        if ([...range.getClientRects()].some(rect => rect.top >= viewport.top + 30)) {
          readableLines.push(node.textContent.trim());
        }
      }
      return { readableLines, visibleHeight: text.bottom - viewport.top, hiddenHeight: viewport.top - text.top, lineHeight };
    });
    expect(geometry.hiddenHeight, 'Earlier prompt lines are above the viewport').toBeGreaterThan(geometry.lineHeight * 2);
    expect(geometry.readableLines, 'Only the two final prompt lines are readable below the fade').toEqual([
      'Keep the answer clear.', 'Start with a summary.'
    ]);
    const responsePosition = await assistant.evaluate(element => {
      const viewport = element.closest('[data-testid="chat-history-container"]')!.getBoundingClientRect();
      return element.getBoundingClientRect().top - viewport.top;
    });
    expect(responsePosition).toBeGreaterThan(geometry.visibleHeight);
    expect(responsePosition).toBeLessThan(200);
    await testInfo.attach(`response-start-${width}`, { body: await container.screenshot(), contentType: 'image/png' });

    const readingPosition = await container.evaluate(element => element.scrollTop);
    await page.getByTestId('stream-response').click();
    await expect(assistant).toContainText('Stream update 2.');
    expect(await container.evaluate(element => element.scrollTop)).toBeCloseTo(readingPosition, 0);

    // A real upward wheel must continue to work while further chunks arrive.
    await container.hover();
    await page.mouse.wheel(0, -120);
    await expect.poll(() => container.evaluate(element => element.scrollTop)).toBeLessThan(readingPosition - 50);
    const manualPosition = await container.evaluate(element => element.scrollTop);
    await page.getByTestId('stream-response').click();
    await expect(assistant).toContainText('Stream update 3.');
    expect(await container.evaluate(element => element.scrollTop)).toBeCloseTo(manualPosition, 0);

    // Clearing a chat cancels an unfulfilled scroll rather than leaving it busy.
    await page.getByTestId('clear-chat').click();
    await expect(user).toHaveCount(0);
    await expect(container).toHaveAttribute('data-scroll-state', 'ready');
    expect(errors).toEqual([]);
  });
}
