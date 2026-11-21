// playwright-account: not_required reason=isolated_component_preview
// Included memories after an approved memory request (voice call or text chat): one pill
// per memory with its title, its icon in a round circle in its colour, never "(1)".
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

for (const [label, width] of [['phone', 390], ['desktop', 1280]] as const) {
  // contract-test: supporting surface=gui.web assertions=video-call.chat.permission-prompt
  test(`names each included memory with its icon circle on ${label}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(`/dev/preview/IncludedMemoryPills?chrome=0&theme=light&background=%23dbeafe&width=${Math.min(width - 40, 640)}`);
    await waitForComponentPreview(page);
    const pills = page.getByTestId('included-memory-pill');
    await expect(pills).toHaveCount(3);
    await expect(page.getByTestId('included-memory-title')).toHaveText(['Career profile', 'Preferred technologies', 'Memories']);
    await expect(page.getByTestId('included-memory-pills')).not.toContainText('(1)');
    const icons = await page.getByTestId('included-memory-icon').evaluateAll((nodes) => nodes.map((node) => ({
      background: getComputedStyle(node).backgroundImage + getComputedStyle(node).backgroundColor,
      glyph: getComputedStyle(node, '::before').backgroundImage,
      radius: getComputedStyle(node).borderRadius,
      width: (node as HTMLElement).getBoundingClientRect().width,
    })));
    for (const icon of icons) {
      expect(icon.radius).toBe('50%');
      expect(icon.glyph).not.toBe('none');
      expect(icon.background).not.toBe('nonergba(0, 0, 0, 0)');
      expect(icon.width).toBeGreaterThan(16);
    }
    await testInfo.attach(`included-memory-pills-${label}`, { body: await page.getByTestId('included-memory-pills').screenshot(), contentType: 'image/png' });
  });
}
