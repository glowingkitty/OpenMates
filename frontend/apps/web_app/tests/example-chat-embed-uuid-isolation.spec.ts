/* eslint-disable @typescript-eslint/no-require-imports */
/** Public example UUIDs can also exist in the authenticated owner's private cache. */
const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email, password, otpKey } = getTestAccount();

test.describe('example embed UUID isolation', () => {
  skipWithoutCredentials(test, email, password, otpKey);

  // contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  test('authenticated same-ID private cache survives opening a public example', async ({ page }: { page: any }) => {
    test.setTimeout(120_000);
    await loginToTestAccount(page);
    const input = {
      exampleChatId: 'example-berlin-english-speaking-gp',
    };
    const check = async (seedPrivate: boolean) => page.evaluate(async (data: typeof input & { seedPrivate: boolean }) => {
      const hook = (window as typeof window & {
        __openmatesE2EExampleEmbedCollision?: (value: typeof data) => Promise<{
          privateCachePreserved: boolean; privateResolverPreserved: boolean; publicResolverSelected: boolean;
          missingPublicFixtureBlocked: boolean; privateRefIndexPreserved: boolean; privatePiiPreserved: boolean;
        }>;
      }).__openmatesE2EExampleEmbedCollision;
      if (!hook) throw new Error('Scoped collision hook unavailable');
      return hook(data);
    }, { ...input, seedPrivate });

    expect(await check(true)).toEqual({
      privateCachePreserved: true,
      privateResolverPreserved: true,
      publicResolverSelected: true,
      missingPublicFixtureBlocked: true,
      privateRefIndexPreserved: true,
      privatePiiPreserved: true,
    });
    await page.evaluate((chatId: string) => { window.location.hash = `#chat-id=${chatId}`; }, input.exampleChatId);
    await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 25_000 });
    await expect(page.getByTestId('embed-preview').first()).toBeVisible({ timeout: 25_000 });
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('embedfullscreen', {
      detail: { embedId: '11111111-1111-4111-8111-111111111111', sourceChatId: 'e2e-stale-source-chat' },
    })));
    await expect(page.getByTestId('embed-fullscreen-container')).toHaveCount(0);
    expect(await check(false), 'Opening the example must not replace the owner cache').toEqual({
      privateCachePreserved: true,
      privateResolverPreserved: true,
      publicResolverSelected: true,
      missingPublicFixtureBlocked: true,
      privateRefIndexPreserved: true,
      privatePiiPreserved: true,
    });
  });
});
