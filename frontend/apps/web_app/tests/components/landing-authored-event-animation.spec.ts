import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Locator } from '@playwright/test';

// playwright-account: not_required reason=isolated_component_preview
const preview = (width: number, language: string) => `/dev/preview/landing/LandingFeatureAnimation?${new URLSearchParams({width:String(width),chrome:'0',theme:width < 760 ? 'dark' : 'light',background:width < 760 ? '#161616' : '#dbeafe',...(language === 'de' ? {variant:'german'} : {})})}`;

async function expectUnobscuredInHost(target: Locator, animation: Locator, clearOverlays = false) {
  let lastBounds: Record<string, unknown> | undefined;
  try {
    await expect.poll(async () => {
      lastBounds = await target.evaluate((element, overlays) => {
        const frame = element.closest('[data-testid="landing-feature-animation"]')!.getBoundingClientRect();
        const bounds = element.getBoundingClientRect();
        const overlay = element.closest('.unified-embed-fullscreen-overlay');
        const topBar = overlays ? overlay?.querySelector('.embed-top-bar')?.getBoundingClientRect() : undefined;
        const composer = overlays ? overlay?.querySelector('[data-testid="embed-fixed-bottom"]')?.getBoundingClientRect() : undefined;
        const area = overlay?.querySelector('.content-area');
        const topLimit = Math.max(frame.top, topBar?.bottom ?? frame.top);
        const bottomLimit = Math.min(frame.bottom, composer?.top ?? frame.bottom);
        return {
          unobscured: bounds.width > 0 && bounds.height > 0 && bounds.left >= frame.left - 1 && bounds.right <= frame.right + 1
            && bounds.top >= topLimit - 1 && bounds.bottom <= bottomLimit + 1,
          target: element.getAttribute('data-testid'), bounds: bounds.toJSON(), frame: frame.toJSON(),
          topBar: topBar?.toJSON(), composer: composer?.toJSON(), topLimit, bottomLimit,
          scrollTop: area?.scrollTop, scrollHeight: area?.scrollHeight, clientHeight: area?.clientHeight,
        };
      }, clearOverlays);
      return lastBounds.unobscured;
    }, { timeout: 2000 }).toBe(true);
  } catch (error) {
    throw new Error(`Expected native component inside unobscured animation host. Last geometry: ${JSON.stringify(lastBounds)}`, { cause: error });
  }
  await expect(animation).toBeVisible();
}

for (const profile of [{width:390,language:'de'},{width:1280,language:'en'}]) {
  // contract-test: direct surface=gui.web assertions=authored-results.demonstrations.proven-capability,marketing-landing.section-stories,marketing-landing.feature-layout
  test(`supplied event request expands the existing calendar event at ${profile.width}px`, async ({ page }, testInfo) => {
    // Cold Vite compilation may consume the default 30s before playback starts.
    test.setTimeout(60_000);
    await page.setViewportSize({width:profile.width,height:800});
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.goto(preview(profile.width,profile.language), {waitUntil:'domcontentloaded'});
    await waitForComponentPreview(page);
    const animation = page.getByTestId('landing-feature-animation');
    await expect(animation).toHaveAttribute('inert', '');
    const animationBounds = await animation.boundingBox();
    expect(animationBounds?.width).toBeGreaterThan(100);
    await expect(animation).toHaveAttribute('data-active-stage','user-request');
    await expect(animation).toContainText('FOSDEM 2027');
    await expect(animation.getByTestId('landing-actionable-illustration')).toContainText(profile.language === 'de' ? 'Beispielinteraktion' : 'Illustrative interaction');
    await expect(animation).toHaveAttribute('data-active-stage','assistant-response');
    await expect(animation).toContainText(profile.language === 'de' ? 'aus deinen Angaben' : 'from your supplied details');
    const card = animation.getByTestId('landing-actionable-event-preview');
    await expect(card).toBeVisible();
    await expect(card).toContainText('FOSDEM 2027');
    const sharedPreview = card.getByTestId('embed-preview');
    await expect(sharedPreview).toHaveAttribute('data-app-id','calendar');
    await expect(sharedPreview).toHaveAttribute('data-skill-id','event');
    await expect(sharedPreview).not.toHaveAttribute('data-embed-id');
    await expect(sharedPreview.locator('.result-corner')).toBeVisible();
    await expect(card.getByTestId('calendar-event-preview')).toBeVisible();
    await expect(card.getByTestId('calendar-event-date')).toContainText('2027');
    const previewWeek = card.getByTestId('calendar-event-week');
    await expect(previewWeek.getByTestId('embeds-results-view-calendar-week-label')).toContainText('2027');
    await expect(previewWeek.getByTestId('embeds-results-view-calendar-day')).toHaveCount(7);
    await expect(previewWeek.getByTestId('embeds-results-view-calendar-date-only')).toHaveCount(2);
    await expect(card.getByTestId('calendar-event-add')).toBeEnabled();
    await expect(card.getByTestId('result-preview-expand')).toBeVisible();
    await expect(card.getByTestId('event-preview-rsvps')).toHaveCount(0);
    await expect(card.locator('img')).toHaveCount(0);
    await expectUnobscuredInHost(previewWeek.getByTestId('embeds-results-view-calendar-week'), animation);
    await expectUnobscuredInHost(card.getByTestId('calendar-event-add'), animation);
    await expect(animation).toHaveAttribute('data-interaction-state','preview-targeted');
    await page.screenshot({path:testInfo.outputPath(`authored-event-preview-${profile.width}.png`)});
    await expect(animation.getByTestId('landing-actionable-pointer')).toBeVisible();
    await expect(animation).toHaveAttribute('data-interaction-state','preview-clicked');
    // This flag is set only by the existing preview's real expand callback.
    await expect(animation).toHaveAttribute('data-embed-expanded','true');
    const details = animation.getByTestId('landing-actionable-event-details');
    await expect(details).toBeVisible();
    await expect(details.getByTestId('result-embed-content')).toHaveAttribute('data-app-id','calendar');
    await expect(details.getByTestId('embed-header-title')).toContainText('FOSDEM 2027');
    await expect(details.getByTestId('embed-header-subtitle')).toContainText('2027');
    await expect(details.getByTestId('calendar-event-location')).toContainText(profile.language === 'de' ? 'ULB-Campus Solbosch, Brüssel' : 'ULB Solbosch campus, Brussels');
    await expect(details.getByTestId('calendar-event-fullscreen-add')).toBeEnabled();
    await expectUnobscuredInHost(details.getByTestId('calendar-event-fullscreen-add'), animation, true);
    // The existing controls are rendered, but this aria-hidden illustration
    // must never focus them or submit/share its synthetic embed identity.
    await page.keyboard.press('Tab');
    expect(await animation.evaluate(element => element.contains(document.activeElement))).toBe(false);
    const fullscreenWeek = details.getByTestId('calendar-event-fullscreen').getByTestId('embeds-results-view-calendar-week');
    await expect(animation).toHaveAttribute('data-fullscreen-view','week');
    await expect(fullscreenWeek).toBeVisible();
    await expect(fullscreenWeek.getByTestId('embeds-results-view-calendar-day')).toHaveCount(7);
    await expect(fullscreenWeek.getByTestId('embeds-results-view-calendar-date-only')).toHaveCount(2);
    await expect(details.getByTestId('calendar-event-source')).toHaveAttribute('href','https://fosdem.org/2027/news/fosdem-2027-dates/');
    await expect(details.getByTestId('calendar-event-date-info')).not.toContainText(/\d{1,2}:\d{2}/);
    // Match the established landing-mobile-stories checkpoint: inspect the
    // readable middle of the actual CSS scene, not its entry/exit translation.
    // The real JS sequence and previously observed pointer click keep running.
    await details.evaluate(element => {
      const scene = element.closest('.scene')!;
      for (const motion of scene.getAnimations()) {
        const duration = Number(motion.effect?.getTiming().duration);
        if (!Number.isFinite(duration)) throw new Error('Event details motion has no finite duration');
        motion.pause();
        motion.currentTime = duration / 2;
      }
    });
    const bounds = await details.evaluate(element => {
      const frame = element.closest('[data-testid="landing-feature-animation"]')!.getBoundingClientRect();
      const content = element.getBoundingClientRect();
      return {left:content.left-frame.left,right:content.right-frame.right,top:content.top-frame.top,bottom:content.bottom-frame.bottom};
    });
    expect(bounds.left).toBeGreaterThanOrEqual(-1);
    expect(bounds.right).toBeLessThanOrEqual(1);
    expect(bounds.top).toBeGreaterThanOrEqual(-1);
    expect(bounds.bottom).toBeLessThanOrEqual(1);
    await expectUnobscuredInHost(details.getByTestId('embeds-results-view-calendar-week-label'), animation, true);
    await expectUnobscuredInHost(fullscreenWeek, animation, true);
    for (const day of await fullscreenWeek.getByTestId('embeds-results-view-calendar-date-only').all()) {
      await expectUnobscuredInHost(day, animation, true);
    }
    await page.screenshot({path:testInfo.outputPath(`authored-event-details-${profile.width}.png`)});
    await expect(page.getByTestId('landing-animation-fixture')).toHaveAttribute('data-completed','true',{timeout:6000});
  });
}

// contract-test: direct surface=gui.web assertions=authored-results.demonstrations.proven-capability,marketing-landing.section-stories
test('reduced motion completes without playing a pointer demonstration', async ({ page }) => {
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.goto(preview(390,'en'), {waitUntil:'domcontentloaded'});
  await waitForComponentPreview(page);
  await expect(page.getByTestId('landing-animation-fixture')).toHaveAttribute('data-completed','true');
  await expect(page.getByTestId('landing-feature-animation')).toBeHidden();
  await expect(page.getByTestId('landing-actionable-pointer')).toHaveCount(0);
});
