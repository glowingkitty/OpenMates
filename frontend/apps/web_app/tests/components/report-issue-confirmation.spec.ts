/**
 * Focused, account-free proof for the submitted Report Issue confirmation.
 * It verifies the user-authored summary, retained short ID, copy feedback, and
 * narrow/wide layout without exercising the backend submission flow.
 */
import { expect, test } from '../helpers/cookie-audit';

// playwright-account: not_required reason=isolated_component_preview

const SUMMARY_VALUES = [
	'The confirmation page did not show what I submitted.',
	'I opened Report Issue, completed each description field, and submitted the form.',
	'The confirmation should summarize the report I just sent.',
	'Only the issue ID and a thank-you message were shown.'
];

test.describe('Report Issue confirmation component preview', () => {
	// contract-test: direct surface=gui.web assertions=issue-reporting.submission.confirmed-and-durable,settings-ui.composition.canonical-and-accessible,settings-ui.localization.visible-content-resolves
	test('shows the submitted report summary responsively and keeps the issue ID copyable', async ({
		page
	}) => {
		for (const preview of [
			{ width: '390', theme: 'dark', background: '#171717' },
			{ width: '560', theme: 'light', background: '#f3f3f3' }
		]) {
			const params = new URLSearchParams({ ...preview, chrome: '0' });
			await page.goto(`/dev/preview/settings/SettingsReportIssueConfirmation?${params}`, {
				waitUntil: 'networkidle'
			});

			const confirmation = page.getByTestId('report-issue-confirmation');
			const summary = page.getByTestId('report-issue-summary');
			await expect(confirmation).toBeVisible();
			await expect(summary).toBeVisible();
			await expect(summary).toHaveAccessibleName('Report summary');
			for (const value of SUMMARY_VALUES) {
				await expect(summary).toContainText(value);
			}
			await expect(page.getByTestId('report-issue-id-value')).toHaveText('V829F');
			await expect(page.getByTestId('report-issue-submit-another')).toBeVisible();

			const layout = await confirmation.evaluate((element) => ({
				clientWidth: element.clientWidth,
				scrollWidth: element.scrollWidth
			}));
			expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
		}

		const copyButton = page.getByTestId('report-issue-copy-id');
		await copyButton.click();
		await expect(copyButton).toContainText('Copied!');
	});
});
