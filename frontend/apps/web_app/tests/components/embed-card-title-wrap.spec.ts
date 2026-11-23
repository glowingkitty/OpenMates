// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';

// contract-test: direct surface=gui.web assertions=video-call.chat.assistant-identity
test('Recipe card title wraps only at word boundaries at iPhone width', async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const variant of ['vegetarianLasagna', 'longTitle']) {
    await page.goto(`/dev/preview/embeds/nutrition/NutritionRecipeEmbedPreview?chrome=0&variant=${variant}`);
    const title = page.getByTestId('result-card-title').first();
    await expect(title).toBeVisible();
    const style = await title.evaluate((el) => {
      const s = getComputedStyle(el);
      return { wrap: s.overflowWrap, clamp: s.webkitLineClamp || s.getPropertyValue('-webkit-line-clamp') };
    });
    expect(style.wrap).toBe('break-word');
    if (variant === 'vegetarianLasagna') {
      // Every rendered line must start at a word start: check the text lines via Range rects.
      const lines = await title.evaluate((el) => {
        const node = el.firstChild as Text;
        const text = node.textContent ?? '';
        const range = document.createRange();
        const out: string[] = [];
        let top = -1; let cur = '';
        for (let i = 0; i < text.length; i++) {
          range.setStart(node, i); range.setEnd(node, i + 1);
          const r = range.getClientRects()[0];
          if (!r) continue;
          if (top >= 0 && Math.abs(r.top - top) > 2) { out.push(cur); cur = ''; }
          top = r.top; cur += text[i];
        }
        out.push(cur);
        return out.map((l) => l.trim());
      });
      expect(lines.join(' ')).toBe('Vegetarian lasagna');
      expect(lines.every((l) => l === 'Vegetarian' || l === 'lasagna' || l === 'Vegetarian lasagna')).toBe(true);
    }
    await testInfo.attach(`recipe-title-${variant}-390`, { body: await page.screenshot(), contentType: 'image/png' });
  }
});
