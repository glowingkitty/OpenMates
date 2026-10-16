import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Page } from '@playwright/test';

// playwright-account: not_required reason=isolated_component_preview
const preview = '/dev/preview/ChatPresentationAnimationHarness?theme=light&background=%23ffffff&width=900&chrome=0';

async function clickAndObserveChunk(page: Page, buttonId: string, expectedText: string) {
  return page.evaluate(({ buttonId, expectedText }) => new Promise<{ text: string; animation: string; prefix: string }>((resolve, reject) => {
    const button = document.querySelector<HTMLButtonElement>(`[data-testid="${buttonId}"]`);
    if (!button) { reject(new Error('Animation preview is unavailable')); return; }
    const readChunk = () => {
      const root = document.querySelector('[data-testid="message-assistant"]');
      if (!root) return;
      const chunk = [...root.querySelectorAll<HTMLElement>('.stream-fade-chunk')]
        .find(element => element.textContent?.includes(expectedText));
      if (!chunk) return;
      clearTimeout(timeout);
      observer.disconnect();
      resolve({
        text: chunk.textContent ?? '',
        animation: getComputedStyle(chunk).animationName,
        prefix: root.querySelector('.ProseMirror p')?.firstChild?.textContent ?? ''
      });
    };
    const observer = new MutationObserver(readChunk);
    const timeout = setTimeout(() => {
      observer.disconnect();
      reject(new Error(`New chunk did not receive a fade; reduced motion=${matchMedia('(prefers-reduced-motion: reduce)').matches}; rendered=${document.querySelector('[data-testid="message-assistant"] .ProseMirror')?.textContent ?? ''}`));
    }, 3000);
    observer.observe(document.body, { subtree: true, childList: true, attributes: true });
    button.click();
    readChunk();
  }), { buttonId, expectedText });
}

for (const width of [390, 1024]) {
  // contract-test: direct surface=gui.web assertions=chats.streaming.web-chunk-fade,chats.rendering.web-history-entrance
  test(`fades loaded history once and only fresh assistant text at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 760 });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.goto(preview);
    await waitForComponentPreview(page);

    const historyAnimation = await page.evaluate(async () => {
      document.querySelector<HTMLButtonElement>('[data-testid="load-saved-history"]')?.click();
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
      const row = document.querySelector<HTMLElement>('[data-testid="message-assistant"]');
      return { reveal: row?.dataset.historyReveal, animation: row ? getComputedStyle(row).animationName : '' };
    });
    const saved = page.getByTestId('message-assistant');
    expect(historyAnimation.reveal).toBe('true');
    expect(historyAnimation.animation).toContain('loaded-history-reveal');
    await expect(saved).toContainText('A saved answer.');
    await testInfo.attach(`loaded-history-${width}`, { body: await saved.screenshot(), contentType: 'image/png' });
    await expect(saved).toHaveAttribute('data-history-reveal', 'false');

    await page.getByTestId('append-saved-row').click();
    await expect(page.getByTestId('message-user').last()).toHaveAttribute('data-history-reveal', 'false');
    await expect(saved).toHaveAttribute('data-history-reveal', 'false');

    await page.reload();
    await waitForComponentPreview(page);
    await page.getByTestId('start-live-stream').click();
    const user = page.getByTestId('message-user');
    const assistant = page.getByTestId('message-assistant');
    await expect(user).toHaveAttribute('data-history-reveal', 'false');
    await expect(assistant).toContainText('Stable opening.');
    const firstChunk = await clickAndObserveChunk(page, 'append-live-chunk', 'New chunk');
    expect(firstChunk.text).toContain('New chunk');
    expect(firstChunk.text).not.toContain('Stable opening.');
    expect(firstChunk.animation).toContain('stream-chunk-fade');
    expect(firstChunk.prefix).toBe('Stable opening.');
    await expect(assistant.locator('.ProseMirror')).toContainText('Stable opening. New chunk');
    await testInfo.attach(`new-assistant-text-${width}`, { body: await assistant.screenshot(), contentType: 'image/png' });
    const secondChunk = await clickAndObserveChunk(page, 'append-second-chunk', 'Another');
    expect(secondChunk.text).toContain('Another');
    expect(secondChunk.text).not.toContain('Stable opening.');
    expect(secondChunk.text).not.toContain('New chunk');
    expect(secondChunk.animation).toContain('stream-chunk-fade');
    expect(secondChunk.prefix).toContain('Stable opening.');
    await expect(assistant.locator('.ProseMirror')).toContainText('Stable opening. New chunk. Another');
    await page.getByTestId('finish-live-stream').click();
    await expect(assistant).toHaveAttribute('data-streaming', 'false');
    await expect(assistant.locator('.ProseMirror')).toContainText('Stable opening. New chunk. Another chunk.');
    const copiedSelection = await assistant.locator('.ProseMirror p').evaluate(el => {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(el);
      selection?.removeAllRanges();
      selection?.addRange(range);
      const text = selection?.toString();
      selection?.removeAllRanges();
      return text;
    });
    expect(copiedSelection).toBe('Stable opening. New chunk. Another chunk.');
  });

  // contract-test: direct surface=gui.web assertions=chats.streaming.web-chunk-fade,chats.rendering.web-history-entrance
  test(`shows both presentations immediately with reduced motion at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 760 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(preview);
    await waitForComponentPreview(page);
    await page.getByTestId('load-saved-history').click();
    const saved = page.getByTestId('message-assistant');
    await expect(saved).toContainText('A saved answer.');
    expect(await saved.evaluate(el => getComputedStyle(el).animationName)).toBe('none');
    await page.reload();
    await waitForComponentPreview(page);
    await page.getByTestId('start-live-stream').click();
    await page.getByTestId('append-live-chunk').click();
    const assistant = page.getByTestId('message-assistant');
    await expect(assistant).toContainText('Stable opening. New chunk');
    await expect(assistant.locator('.stream-fade-chunk')).toHaveCount(0);
  });
}
