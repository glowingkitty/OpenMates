// playwright-account: not_required reason=public_logged_out_example_admission
import { expect, test } from './helpers/cookie-audit';
import { INTERNAL_EXAMPLE_CHATS } from '../../../packages/ui/src/demo_chats/exampleChatData';
import { landingAppExamples, landingAppOrder } from '../../../packages/public-site/src/components/landing/landingPageContent';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { getE2EDebugUrl } = require('./signup-flow-helpers');

// contract-test: direct surface=gui.web assertions=marketing-landing.app-metadata-defaults,public-example-chats.catalog.discoverable
test('guest header exposes public examples and excludes internal fixtures', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(getE2EDebugUrl('/landing'), { waitUntil: 'domcontentloaded' });
  const rail = page.getByTestId('landing-app-rail');
  const prompt = page.getByTestId('landing-prompt');
  await expect(rail).toBeVisible();
  const internalIds = new Set(INTERNAL_EXAMPLE_CHATS.map(chat => chat.chat_id));
  const observedApps = new Set<string>();
  const origin = new URL(page.url()).origin;
  for (let step = 0; step < landingAppOrder.length; step++) {
    const appId = await prompt.getAttribute('data-active-app');
    expect(appId).not.toBeNull();
    observedApps.add(appId!);
    const chatId = landingAppExamples[appId!];
    expect(internalIds.has(chatId), `${appId} must use a public example`).toBe(false);
    await expect(prompt).toHaveAttribute('href', `${origin}/?lang=en#chat-id=${encodeURIComponent(chatId)}`);
    for (const internalId of internalIds) {
      await expect(page.locator(`a[href*="chat-id=${encodeURIComponent(internalId)}"]`)).toHaveCount(0);
    }
    if (step + 1 < landingAppOrder.length) {
      await rail.press('ArrowRight');
      await expect(prompt).not.toHaveAttribute('data-active-app', appId!);
    }
  }
  expect([...observedApps].sort()).toEqual([...landingAppOrder].sort());
  expect(observedApps.has('code')).toBe(true);
  expect(landingAppExamples.code).toBe('example-habit-garden-web-application');
});
