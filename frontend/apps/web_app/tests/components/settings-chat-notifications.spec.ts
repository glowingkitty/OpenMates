import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const base = '/dev/preview/settings/notifications/SettingsChatNotifications?theme=light&background=%23dbeafe&width=390&chrome=0';

// contract-test: direct surface=gui.web assertions=notifications.content.privacy-boundary
// contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible,settings-ui.localization.visible-content-resolves
test('push answer text and chat title switches are on by default and saved one at a time', async ({ page }) => {
	const bodies: unknown[] = [];
	await page.route('**/v1/push/preferences', async route => {
		bodies.push(route.request().postDataJSON());
		await route.fulfill({ json: { success: true } });
	});
	await page.goto(`${base}&email=1`);
	const canvas = await waitForComponentPreview(page);
	const summary = canvas.getByTestId('push-notifications-include-chat-title');
	const preview = canvas.getByTestId('push-notifications-include-preview');
	await expect(summary).toBeVisible();
	await expect(summary).toContainText('Show the chat title');
	await expect(summary).toContainText('Apple and Google cannot read it');
	await expect(preview).toContainText('Apple and Google cannot read it');
	await expect(preview).toBeVisible();
	await expect(preview).toContainText('Show the answer text');
	await expect(preview).toContainText('On by default');
	await expect(preview.locator('input[type="checkbox"]')).toBeChecked();
	await expect(summary.locator('input[type="checkbox"]')).toBeChecked();
	await preview.click();
	await expect.poll(() => bodies).toEqual([{ includeAnswerText: false }]);
	await summary.click();
	await expect.poll(() => bodies).toEqual([{ includeAnswerText: false }, { includeChatTitle: false }]);
	await page.screenshot({ path: test.info().outputPath('push-switches.png') });
});

// contract-test: direct surface=gui.web assertions=notifications.content.privacy-boundary
test('email content setting says plainly that content travels as plain text and stays off by default', async ({ page }) => {
	await page.goto(`${base}&email=1`);
	const canvas = await waitForComponentPreview(page);
	const content = canvas.getByTestId('email-notifications-include-content');
	await expect(content).toContainText('Show reply content in emails');
	await expect(content).toContainText('Off by default');
	await expect(content).toContainText('plain text through the email provider');
	await expect(content).toContainText('stays in your mailbox');
	await expect(content.locator('input[type="checkbox"]')).not.toBeChecked();
	await page.screenshot({ path: test.info().outputPath('email-content.png') });
});

// contract-test: direct surface=gui.web assertions=notifications.content.privacy-boundary
test('a warning appears only when email and push are both off', async ({ page }) => {
	await page.goto(base);
	let canvas = await waitForComponentPreview(page);
	await expect(canvas.getByTestId('notifications-missed-warning')).toContainText('You may miss important replies');
	await page.screenshot({ path: test.info().outputPath('missed-warning.png') });
	await page.goto(`${base}&email=1`);
	canvas = await waitForComponentPreview(page);
	await expect(canvas.getByTestId('notifications-missed-warning')).toHaveCount(0);
	await page.goto(`${base}&push=1`);
	canvas = await waitForComponentPreview(page);
	await expect(canvas.getByTestId('notifications-missed-warning')).toHaveCount(0);
});
