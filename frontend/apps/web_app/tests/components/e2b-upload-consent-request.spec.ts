/**
 * Component proof for the E2B upload-consent request card: plain text, privacy
 * policy link, own-machine alternative, three choices and the read-only answered
 * state. Fictional fixtures only; no account, sandbox or network is used.
 * Architecture: docs/plans/e2b-upload-consent/plan.yml
 */
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const preview = (variant?: string) =>
  `/dev/preview/E2bUploadConsentRequest?${new URLSearchParams({ chrome: '0', theme: 'light', width: '480', ...(variant ? { variant } : {}) })}`;

// contract-test: direct surface=gui.web assertions=code-run.e2b.upload-consent
test('asks before sending code to E2B and reports each choice', async ({ page }, testInfo) => {
  await page.goto(preview());
  await waitForComponentPreview(page);
  const card = page.getByTestId('e2b-consent-request');
  await expect(card).toBeVisible();
  await expect(page.getByTestId('e2b-consent-text')).toContainText('E2B');
  await expect(page.getByTestId('e2b-consent-text')).toContainText('cloud sandbox');
  await expect(page.getByTestId('e2b-consent-text')).toContainText('in the US');
  await expect(page.getByTestId('e2b-consent-privacy-link')).toHaveAttribute('href', 'https://openmates.org/privacy');
  await expect(page.getByTestId('e2b-consent-own-machine-hint')).toContainText('openmates remote-access');
  for (const id of ['e2b-consent-allow', 'e2b-consent-own-machine', 'e2b-consent-not-now']) {
    await expect(page.getByTestId(id)).toBeVisible();
  }
  await expect(page.getByTestId('e2b-consent-answered')).toHaveCount(0);
  await testInfo.attach('e2b-consent-unanswered', { body: await card.screenshot(), contentType: 'image/png' });

  await page.evaluate(() => {
    (window as unknown as { __e2bAnswers: string[] }).__e2bAnswers = [];
    window.addEventListener('e2b-consent-preview-answer', (event) => {
      (window as unknown as { __e2bAnswers: string[] }).__e2bAnswers.push((event as CustomEvent).detail.choice);
    });
  });
  for (const [id, choice] of [['e2b-consent-allow', 'allow'], ['e2b-consent-own-machine', 'own_machine'], ['e2b-consent-not-now', 'not_now']]) {
    await page.getByTestId(id).click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { __e2bAnswers: string[] }).__e2bAnswers.at(-1))).toBe(choice);
  }
});

for (const [variant, choice] of [['answered-allow', 'allow'], ['answered-not-now', 'not_now']]) {
  // contract-test: direct surface=gui.web assertions=code-run.e2b.upload-consent
  test(`shows the answer read-only: ${variant}`, async ({ page }, testInfo) => {
    await page.goto(preview(variant));
    await waitForComponentPreview(page);
    const card = page.getByTestId('e2b-consent-request');
    await expect(page.getByTestId('e2b-consent-answered')).toHaveAttribute('data-choice', choice);
    await expect(page.getByTestId('e2b-consent-allow')).toHaveCount(0);
    await expect(page.getByTestId('e2b-consent-own-machine')).toHaveCount(0);
    await expect(page.getByTestId('e2b-consent-not-now')).toHaveCount(0);
    await testInfo.attach(`e2b-consent-${variant}`, { body: await card.screenshot(), contentType: 'image/png' });
  });
}
