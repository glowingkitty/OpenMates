import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

for (const { width, isMobile } of [{ width: 390, isMobile: false }, { width: 1280, isMobile: false }, { width: 390, isMobile: true }]) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.rendering.inline-entity-interaction
  test(`specialized previews retain their editor layout with explicit tools at ${width}, mobile=${isMobile}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
        writeText: async (value: string) => { (window as unknown as Record<string, unknown>).__previewCopied = value; },
        write: async (items: ClipboardItem[]) => {
          const value = await (await items[0].getType('text/plain')).text();
          (window as unknown as Record<string, unknown>).__previewCopied = value;
        },
      } });
      document.addEventListener('embed-context-menu', () => { (window as unknown as Record<string, unknown>).__previewMore = true; });
    });
    for (const entry of [
      { path: 'code/CodeEmbedPreview', content: '.code-preview-container', selected: 'code', copied: "import { onMount }" },
      { path: 'docs/DocsEmbedPreview', content: '.doc-page-content', selected: 'h1', copied: '' },
      { path: 'sheets/SheetEmbedPreview', content: '.preview-table', selected: 'th', copied: 'Name\tRole\tDepartment\tStart Date' },
    ]) {
      let expanded = 0;
      const listener = (message: { text(): string }) => { if (message.text() === '[Preview] specialized expanded') expanded++; };
      page.on('console', listener);
      const props = encodeURIComponent(JSON.stringify({ isMobile }));
      await page.goto(`/dev/preview/embeds/${entry.path}?chrome=0&variant=tools&width=${width}&props=${props}`);
      await waitForComponentPreview(page);
      const card = page.getByTestId('embed-preview');
      await expect(card).toHaveAttribute('role', 'group');
      await expect(card.getByTestId('embed-basic-infos-bar')).toBeVisible();
      await expect(card.locator('.details-section')).toBeVisible();
      await expect(card).toHaveCSS('width', isMobile ? '150px' : '300px');
      await expect(card).toHaveCSS('height', isMobile ? '290px' : '200px');
      const layout = await card.evaluate(element => {
        const rect = (selector: string) => {
          const box = element.querySelector(selector)!.getBoundingClientRect();
          return { x: box.x, y: box.y, right: box.right, bottom: box.bottom, width: box.width, height: box.height };
        };
        return { card: element.getBoundingClientRect().toJSON(), tools: rect('[data-testid="preview-tools"]'), title: rect('[data-testid="embed-basic-infos-bar"] .status-label'), body: rect('.details-section'), identity: rect('[data-testid="embed-basic-infos-bar"]') };
      });
      expect(layout.title.width).toBeGreaterThan(0);
      expect(layout.title.height).toBeGreaterThan(0);
      expect(layout.tools.x).toBeGreaterThanOrEqual(layout.card.x - 1);
      expect(layout.tools.right).toBeLessThanOrEqual(layout.card.right + 1);
      expect(layout.tools.bottom).toBeLessThanOrEqual(layout.body.y + 1);
      if (isMobile) {
        expect(layout.identity.bottom).toBeLessThanOrEqual(layout.tools.y + 1);
        expect(layout.title.bottom).toBeLessThanOrEqual(layout.tools.y + 1);
      } else expect(layout.title.right).toBeLessThanOrEqual(layout.tools.x + 1);
      await expect(card.getByTestId('result-card-content')).toHaveCount(0);
      const content = card.locator(entry.content);
      await expect(content).toBeVisible();
      const text = content.locator(entry.selected).first();
      await expect(text).toHaveCSS('user-select', 'text');
      await expect(text).toHaveCSS('pointer-events', 'auto');
      await text.click({ position: { x: 2, y: 2 } });
      expect(expanded).toBe(0);
      const selection = await text.evaluate(element => {
        const range = document.createRange(); range.selectNodeContents(element);
        const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range);
        return selection.toString();
      });
      expect(selection.length).toBeGreaterThan(0);
      if (entry.copied) {
        await card.getByTestId('preview-copy').click();
        await expect.poll(() => page.evaluate(() => (window as unknown as Record<string, unknown>).__previewCopied)).toContain(entry.copied);
        expect(expanded).toBe(0);
      }
      await card.getByTestId('result-preview-more').click();
      await expect.poll(() => page.evaluate(() => (window as unknown as Record<string, unknown>).__previewMore)).toBe(true);
      await card.getByTestId('result-preview-expand').focus();
      await page.keyboard.press('Enter');
      await expect.poll(() => expanded).toBe(1);
      await testInfo.attach(`${entry.path.split('/')[0]}-tools-${width}-mobile-${isMobile}`, { body: await page.screenshot(), contentType: 'image/png' });
      page.off('console', listener);
    }
  });
}
