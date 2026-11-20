import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Locator } from '@playwright/test';

// playwright-account: not_required reason=isolated_component_preview
const preview = (width: number, language: string, standalone = false) => `/dev/preview/landing/LandingFeatureAnimation?${new URLSearchParams({width:String(width),chrome:'0',theme:width < 760 ? 'dark' : 'light',background:width < 760 ? '#161616' : '#dbeafe',...(standalone ? {variant:language === 'de' ? 'standaloneGerman' : 'standalone'} : language === 'de' ? {variant:'german'} : {})})}`;

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

// The app host shows the real event embed; the UI-free website shows the public package's own.
for (const profile of [{width:390,language:'de',standalone:false},{width:1280,language:'en',standalone:false},{width:390,language:'de',standalone:true},{width:1280,language:'en',standalone:true}]) {
  const label = `${profile.standalone ? 'standalone website' : 'app'} ${profile.width}px`;
  // contract-test: direct surface=gui.web assertions=authored-results.demonstrations.proven-capability,marketing-landing.section-stories,marketing-landing.feature-layout
  test(`natural conference question shows and expands the FOSDEM event embed (${label})`, async ({ page }, testInfo) => {
    // Cold Vite compilation may consume the default 30s before playback starts.
    test.setTimeout(60_000);
    await page.setViewportSize({width:profile.width,height:800});
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.goto(preview(profile.width,profile.language,profile.standalone), {waitUntil:'domcontentloaded'});
    await waitForComponentPreview(page);
    const animation = page.getByTestId('landing-feature-animation');
    await expect(animation).toHaveAttribute('inert', '');
    const animationBounds = await animation.boundingBox();
    expect(animationBounds?.width).toBeGreaterThan(100);
    await expect(animation).toHaveAttribute('data-active-stage','user-request');
    await expect(animation).toContainText(profile.language === 'de' ? 'Gibt es bald Konferenzen für Open-Source-Software?' : 'Any upcoming open source software conferences?');
    await expect(animation.getByTestId('landing-actionable-illustration')).toContainText(profile.language === 'de' ? 'Beispiel' : 'Illustrative');
    await expect(animation).toHaveAttribute('data-active-stage','assistant-response');
    await expect(animation).toContainText('FOSDEM');
    await expect(animation).toHaveAttribute('data-active-stage','event-preview');
    const card = animation.getByTestId('landing-actionable-event-preview');
    await expect(card).toBeVisible();
    await expect(card).toContainText('FOSDEM 2027');
    await expect(card.getByTestId('embed-preview')).toHaveAttribute('data-app-id','events');
    await expect(card.getByTestId('embed-calendar-date')).toBeVisible();
    await expect(card.getByTestId('result-preview-expand')).toBeVisible();
    await expect(card.getByTestId('event-preview-rsvps')).toHaveCount(0);
    await expectUnobscuredInHost(card.getByTestId('embed-preview'), animation);
    await expect(animation).toHaveAttribute('data-interaction-state','preview-targeted');
    await testInfo.attach(`event-preview-${label}`, {body: await animation.screenshot(), contentType: 'image/png'});
    await expect(animation.getByTestId('landing-actionable-pointer')).toBeVisible();
    await expect(animation).toHaveAttribute('data-interaction-state','preview-clicked');
    // This flag is set only by the preview's expand callback.
    await expect(animation).toHaveAttribute('data-embed-expanded','true');
    const details = animation.getByTestId('landing-actionable-event-details');
    await expect(details).toBeVisible();
    await expect(details).toContainText('FOSDEM 2027');
    const cta = details.getByTestId('external-provider-cta');
    await expect(cta).toContainText(profile.standalone && profile.language === 'de' ? 'Auf fosdem.org öffnen' : /(Open on|Auf) fosdem\.org/);
    await expectUnobscuredInHost(cta, animation, true);
    // The controls are rendered, but this aria-hidden illustration must never focus them.
    await page.keyboard.press('Tab');
    expect(await animation.evaluate(element => element.contains(document.activeElement))).toBe(false);
    await expect(animation).toHaveAttribute('data-fullscreen-view','week');
    await expect(details.getByTestId('event-venue-card')).toContainText('ULB Solbosch');
    await testInfo.attach(`event-expanded-${label}`, {body: await animation.screenshot(), contentType: 'image/png'});
    await expect(page.getByTestId('landing-animation-fixture')).toHaveAttribute('data-completed','true',{timeout:8000});
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
