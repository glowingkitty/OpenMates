import { expect, test } from './helpers/cookie-audit';
/* eslint-disable @typescript-eslint/no-require-imports */
const { getE2EDebugUrl } = require('./signup-flow-helpers');

test.use({ locale: 'en-US' });

// contract-test: direct surface=gui.web assertions=storage.privacy.ciphertext-boundary
test('logged-out privacy policy distinguishes deleted records from retained database history', async ({ page }) => {
	test.setTimeout(60_000);
	await page.goto(getE2EDebugUrl('/privacy'), { waitUntil: 'domcontentloaded' });
	await expect(page).toHaveURL(/#chat-id=legal-privacy/, { timeout: 15_000 });

	const history = page.getByTestId('chat-history-container');
	await expect(history).toBeVisible({ timeout: 15_000 });
	const policy = history.getByTestId('message-assistant').first();
	await expect(policy).toBeVisible({ timeout: 15_000 });
	await expect(policy.getByText('Historical database revisions and activity', { exact: true }))
		.toBeVisible({ timeout: 15_000 });

	await expect(policy).toContainText('remove current account records');
	await expect(policy).toContainText('earlier account-profile fields or encrypted chat and artifact snapshots');
	await expect(policy).toContainText('Deleting the current records does not automatically purge');
	await expect(policy).toContainText('no enforced automatic expiry');
	await expect(policy).toContainText('60-day encrypted-backup lifecycle');
	await expect(policy).toContainText('60 days via S3 lifecycle');
	await expect(policy).not.toContainText('BSI §34 BDSG');
	await expect(policy).not.toContainText('audit logs retained 2 years');
});
