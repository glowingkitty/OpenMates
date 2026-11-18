// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const previewUrl = (width: number) =>
  `/dev/preview/settings/SkillDetails?${new URLSearchParams({
    theme: 'light', background: '#dbeafe', width: String(width), chrome: '0', variant: 'events-search',
  })}`;

for (const width of [768, 380]) {
  // contract-test: direct surface=gui.web assertions=events-search.billing.usage
  test(`Event search settings show the web search price, Mercury 3 token prices and a typical cost at ${width}px`, async ({ page }, testInfo) => {
    test.setTimeout(60_000); // Cold local preview compilation may outlast Playwright's default 30s.
    await page.setViewportSize({ width, height: 900 });
    await page.goto(previewUrl(width));
    const canvas = await waitForComponentPreview(page);
    const lines = canvas.locator('p.pricing');
    // Usage-based price, never the old flat fee per request.
    await expect(lines.first()).toHaveText(/^10 credits \/ web search$/);
    await expect(canvas.getByText(/credits? \/ request/)).toHaveCount(0);
    // Token lines follow Mercury 3's current rate: the regular price or its active launch price.
    await expect(lines.nth(1)).toContainText(/3,?335|6,?670/);
    await expect(lines.nth(1)).toContainText(/input/i);
    await expect(lines.nth(2)).toContainText(/955|1,?905/);
    await expect(lines.nth(2)).toContainText(/output/i);
    const launch = (await lines.nth(1).textContent())?.match(/6,?670/) !== null;
    await expect(canvas.getByTestId('skill-temporary-price-note')).toHaveCount(launch ? 1 : 0);
    await expect(canvas.getByTestId('skill-pricing-note')).toContainText('15–25 credits');
    await expect(canvas.getByTestId('skill-pricing-note')).toContainText('official conference schedule costs 1 credit');
    // The notes wrap inside the window: nothing runs past its right edge.
    const note = await canvas.getByTestId('skill-pricing-note').boundingBox();
    expect(note && note.x + note.width).toBeLessThanOrEqual(width);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await testInfo.attach(`events-search-pricing-${width}`, { body: await canvas.screenshot(), contentType: 'image/png' });
  });
}
