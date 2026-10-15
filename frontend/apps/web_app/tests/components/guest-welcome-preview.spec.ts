import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import landingExamples from '../../../../packages/ui/src/generated/landingExampleChats.generated.json';

// playwright-account: not_required reason=isolated_component_preview

// contract-test: direct surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,landing-onboarding.guest-examples,marketing-landing.example-catalog-alignment
test('bare Chat welcome exposes guest greeting and metadata-ordered default examples', async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1280, height: 900 });
  // The workspace fixture supplies the app's definite height and public guest inspirations.
  await page.goto('/dev/preview/ActiveChatFocusFixture?chrome=0', { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  await expect(page.getByTestId('chat-welcome-heading')).toHaveText('Hey there!');
  await expect(page.getByTestId('guest-interest-prompt')).toHaveText('Continue where you left off');
  const cards = page.locator('[data-testid="resume-chat-large-card"], [data-testid="resume-chat-card"]');
  await expect.poll(() => cards.evaluateAll(nodes => nodes.map(node => node.getAttribute('data-chat-id')).filter(id => id?.startsWith('example-')))).toEqual(landingExamples.map(example => example.chatId));
  await expect(page.getByTestId('guest-interest-select-interests')).toBeVisible();
  await page.getByTestId('guest-show-all-examples').click();
  await expect(page.getByTestId('guest-all-examples-view')).toBeVisible();
  await page.getByTestId('guest-all-examples-back').click();
  await expect(page.getByTestId('chat-welcome-heading')).toHaveText('Hey there!');
  await page.getByTestId('guest-interest-select-interests').click();
  await expect(page.getByTestId('guest-interest-tags')).toBeVisible();
});
