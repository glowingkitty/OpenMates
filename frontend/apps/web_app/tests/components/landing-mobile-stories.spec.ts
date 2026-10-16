import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { actionableStages, privacyStages } from '../../../../packages/public-site/src/components/landing/landingFeatureAnimationContent';

// playwright-account: not_required reason=isolated_component_preview
const profiles = [
  { width: 320, height: 568, language: 'de' },
  { width: 390, height: 664, language: 'en' },
  { width: 1280, height: 720, language: 'en' },
  { width: 1440, height: 900, language: 'en' },
  { width: 1920, height: 1080, language: 'de' },
];

for (const profile of profiles) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.feature-layout,marketing-landing.section-stories,marketing-landing.six-feature-viewport
  test(`feature animations fit clear of fixed controls at ${profile.width}x${profile.height} ${profile.language}`, async ({ page }, testInfo) => {
    test.setTimeout(100_000);
    await page.setViewportSize({ width: profile.width, height: profile.height });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.addInitScript(language => localStorage.setItem('preferredLanguage', language), profile.language);
    await page.route('**/v1/settings/server-status', route => route.fulfill({ json: { anonymous_free_usage: { active: true, can_send_text: true } } }));
    await page.goto(`/dev/preview/landing/LandingPage?${new URLSearchParams({ width: String(profile.width), theme: 'dark', chrome: '0', background: '#161616' })}`, { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 60_000);
    await expect(page.getByTestId('landing-compose')).toBeVisible();
    for (const section of ['actionable', 'privacy'] as const) {
      const feature = page.getByTestId(`landing-feature-${section}`);
      await page.getByTestId('landing-scroll-container').evaluate((element, id) => {
        const target = element.querySelector(`#${id}`)!;
        element.scrollTo({ top: target.getBoundingClientRect().top - element.getBoundingClientRect().top + element.scrollTop, behavior: 'instant' });
      }, section);
      await expect(feature).toHaveAttribute('data-story-state', 'playing');
      const animation = feature.getByTestId('landing-feature-animation');
      const stages = section === 'actionable' ? actionableStages : privacyStages;
      for (const stage of stages) {
        await expect(animation).toHaveAttribute('data-active-stage', stage.id, { timeout: 6_000 });
        // Inspect the readable part of each CSS scene while its real JS timeline
        // keeps advancing. Entry/exit deliberately move and fade the content.
        await animation.locator('.scene').evaluate((element, duration) => {
          for (const motion of element.getAnimations()) { motion.pause(); motion.currentTime = duration / 2; }
        }, stage.durationMs);
        await expect.poll(() => animation.evaluate(element => {
          const content = element.querySelector<HTMLElement>('.scene-content')!;
          const frame = element.getBoundingClientRect(), payload = content.getBoundingClientRect();
          return payload.left >= frame.left - 1 && payload.right <= frame.right + 1 && payload.top >= frame.top - 1 && payload.bottom <= frame.bottom + 1;
        }), { message: `${section}/${stage.id} must fit within its animation frame` }).toBe(true);
        // The whole desktop composition must fit its safe region, and its
        // readable scene must stay close enough to the intro to form one group.
        const geometry = await animation.evaluate(element => {
          const root = element.closest('[data-testid="landing-page"]')!;
          const stage = element.getBoundingClientRect();
          const payload = element.querySelector('.scene-content')!.getBoundingClientRect();
          const previous = root.querySelector('[data-testid="landing-previous-section"]')!.getBoundingClientRect();
          const next = root.querySelector('[data-testid="landing-next-section"]')!.getBoundingClientRect();
          const composer = root.querySelector('[data-testid="landing-compose"]')!.getBoundingClientRect();
          const section = element.closest('section')!;
          const heading = section.querySelector('h2')!.getBoundingClientRect();
          const intro = section.querySelector('.feature-copy')!.getBoundingClientRect();
          const skip = section.querySelector('.skip-animation')!.getBoundingClientRect();
          const sectionStyle = getComputedStyle(section);
          const safeTop = section.getBoundingClientRect().top + parseFloat(sectionStyle.paddingTop);
          const safeBottom = section.getBoundingClientRect().bottom - parseFloat(sectionStyle.paddingBottom);
          return { frameBottom: stage.bottom, introTop: intro.top, skipBottom: skip.bottom, safeTop, safeBottom, top: payload.top, bottom: payload.bottom, height: stage.height, previousBottom: previous.bottom, nextTop: next.top, composeTop: composer.top, headingBottom: heading.bottom, scale: Number(element.querySelector<HTMLElement>('.scene-content')!.dataset.sceneScale) };
        });
        expect(geometry.top).toBeGreaterThan(geometry.headingBottom);
        expect(geometry.top).toBeGreaterThan(geometry.previousBottom);
        expect(geometry.bottom).toBeLessThanOrEqual(geometry.nextTop - 4);
        expect(geometry.bottom).toBeLessThan(geometry.composeTop);
        if (profile.width > 760) {
          expect(geometry.introTop).toBeGreaterThanOrEqual(geometry.previousBottom + 8);
          expect(geometry.frameBottom).toBeLessThanOrEqual(geometry.nextTop - 8);
          expect(geometry.height).toBeGreaterThan(96);
          expect(geometry.height).toBeLessThanOrEqual(288);
          expect(geometry.top - geometry.skipBottom, `${section}/${stage.id} stays grouped with its intro`).toBeLessThanOrEqual(160);
          const groupCenter = (geometry.introTop + geometry.frameBottom) / 2;
          const safeCenter = (geometry.safeTop + geometry.safeBottom) / 2;
          expect(Math.abs(groupCenter - safeCenter), 'intro and scene center together above the controls').toBeLessThanOrEqual(2);
          if (profile.width >= 1440) {
            expect(geometry.scale, `desktop ${section}/${stage.id} retains its natural size`).toBeCloseTo(1, 2);
          }
        }
        if (stage.id === 'personalized-copy' || stage.id === 'memory-permission' || stage.id === 'event-preview') {
          await page.screenshot({ path: testInfo.outputPath(`${section}-${stage.id}-${profile.width}.png`) });
        }
      }
      await expect(feature).toHaveAttribute('data-story-state', 'complete', { timeout: 6_000 });
      await expect(feature.getByTestId(`landing-replay-${section}`)).toBeVisible();
    }
  });
}
