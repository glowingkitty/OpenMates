/**
 * Component proof for the web E2B consent surfaces besides the chat card: the
 * run-start dialog and the privacy settings entry. Fictional fixtures only; no
 * account, sandbox or network is used.
 * Architecture: docs/plans/e2b-upload-consent/plan.yml
 */
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const preview = (component: string) =>
  `/dev/preview/${component}?${new URLSearchParams({ chrome: '0', theme: 'light', width: '560' })}`;

// contract-test: direct surface=gui.web assertions=code-run.e2b.upload-consent
test('run-start dialog asks with the three choices and reports each', async ({ page }, testInfo) => {
  await page.goto(preview('E2bConsentRunDialog'));
  await waitForComponentPreview(page);
  const dialog = page.getByTestId('e2b-consent-dialog');
  await expect(dialog).toBeVisible();
  await expect(page.getByTestId('e2b-consent-text')).toContainText('E2B');
  await expect(page.getByTestId('e2b-consent-own-machine-hint')).toContainText('openmates remote-access');
  await testInfo.attach('e2b-run-dialog', { body: await page.screenshot(), contentType: 'image/png' });
  await page.evaluate(() => {
    const w = window as unknown as { __answers: string[] };
    w.__answers = [];
    window.addEventListener('e2b-consent-preview-answer', (e) => w.__answers.push((e as CustomEvent).detail.choice));
  });
  for (const [id, choice] of [['e2b-consent-allow', 'allow'], ['e2b-consent-own-machine', 'own_machine'], ['e2b-consent-not-now', 'not_now']]) {
    await page.getByTestId(id).click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { __answers: string[] }).__answers.at(-1))).toBe(choice);
  }
  await page.keyboard.press('Escape');
  await expect.poll(() => page.evaluate(() => (window as unknown as { __answers: string[] }).__answers.at(-1))).toBe('dismissed');
});

// contract-test: direct surface=gui.web assertions=code-run.e2b.upload-consent
test('privacy settings entry shows the decision and toggles it', async ({ page }, testInfo) => {
  await page.goto(preview('settings/privacy/SettingsE2bConsent'));
  await waitForComponentPreview(page);
  const entry = page.getByTestId('settings-e2b-consent');
  await expect(entry).toContainText('Run code in the E2B cloud sandbox');
  await expect(entry).toHaveAttribute('data-decision', 'none');
  await expect(entry).toContainText('Not decided yet');
  await testInfo.attach('e2b-settings-undecided', { body: await entry.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
  await entry.getByRole('button').first().click();
  await expect(entry).toHaveAttribute('data-decision', 'allowed');
  await expect(entry).toContainText('Allowed');
  await expect(entry.getByRole('checkbox')).toBeChecked();
  await testInfo.attach('e2b-settings-allowed', { body: await entry.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
  await entry.getByRole('button').first().click();
  await expect(entry).toHaveAttribute('data-decision', 'declined');
  await expect(entry).toContainText('Not allowed');
  // The toggle knob follows the decision (off when not allowed), not only the status text.
  await expect(entry.getByRole('checkbox')).not.toBeChecked();
  await testInfo.attach('e2b-settings-declined', { body: await entry.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
});
