import { expect, test, type Page } from '@playwright/test';

/** Sample related controls in one frame while responsive layout/CTA transitions settle. */
export async function assertGuestHeaderControlsSeparated(page: Page, includeProfile = false): Promise<void> {
  let geometry: unknown;
  try {
    await expect.poll(async () => {
      const sample = await page.evaluate((requireProfile) => {
        const rect = (id: string) => {
          const element = document.querySelector(`[data-testid="${id}"]`);
          return element?.getBoundingClientRect().toJSON() ?? null;
        };
        const selector = rect('workspace-mobile-select');
        const cta = rect('header-login-signup-btn');
        const profile = rect('profile-container');
        return {
          selector, cta, profile,
          separated: {
            selectorBeforeCta: Boolean(selector?.width && cta?.width && selector.right <= cta.left),
            ctaBeforeProfile: !requireProfile || Boolean(cta?.width && profile?.width && cta.right <= profile.left),
          },
        };
      }, includeProfile);
      geometry = sample;
      return sample.separated;
    }, { message: 'Guest header controls must remain separated after responsive/CTA layout settles' }).toEqual({
      selectorBeforeCta: true, ctaBeforeProfile: true,
    });
  } catch (error) {
    await test.info().attach('guest-header-geometry', { body: JSON.stringify(geometry), contentType: 'application/json' });
    throw error;
  }
}
