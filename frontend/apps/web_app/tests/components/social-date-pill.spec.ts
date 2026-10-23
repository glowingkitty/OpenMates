import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

for (const width of [390, 1100]) for (const theme of ['light', 'dark']) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`Social publication date reuses the appointment time pill at ${width}px in ${theme}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const query = `chrome=0&width=${width}&theme=${theme}${width > 400 ? '&context=chat' : ''}`;
    await page.goto(`/dev/preview/embeds/social_media/SocialMediaPostEmbedPreview?${query}`);
    await waitForComponentPreview(page);
    const card = page.getByTestId('embed-preview');
    const publication = card.getByTestId('social-post-publication-date');
    await expect(publication).toHaveText('May 24, 2026');
    await expect(publication).toHaveAttribute('datetime', '2026-05-24T10:30:00.000Z');
    await expect(card.getByTestId('embed-calendar-date')).toHaveCount(0);
    const style = (element: Element) => {
      const computed = getComputedStyle(element), bounds = element.getBoundingClientRect();
      return { radius: computed.borderTopLeftRadius, background: computed.backgroundColor,
        color: computed.color, shadow: computed.boxShadow, padding: computed.padding, weight: computed.fontWeight,
        height: bounds.height, width: bounds.width };
    };
    const social = await publication.evaluate(style);
    expect(Number.parseFloat(social.radius)).toBeGreaterThanOrEqual(social.height / 2);
    expect(social.shadow).not.toBe('none');
    expect(social.width).toBeGreaterThan(60);
    await testInfo.attach(`social-rounded-date-${width}-${theme}`, { body: await card.screenshot(), contentType: 'image/png' });

    await page.goto(`/dev/preview/embeds/health/HealthAppointmentEmbedPreview?${query}`);
    await waitForComponentPreview(page);
    const appointment = await page.getByTestId('embed-calendar-time').evaluate(style);
    for (const property of ['radius', 'background', 'color', 'shadow', 'padding', 'weight'] as const)
      expect(social[property]).toBe(appointment[property]);
  });
}
