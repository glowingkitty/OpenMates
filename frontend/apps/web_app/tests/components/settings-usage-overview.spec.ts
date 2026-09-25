import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const today = new Date().toISOString().slice(0, 10);

const completeUsageDay = {
	date: today,
	total_credits: 38,
	items: [
		{
			type: 'incognito',
			chat_id: 'incognito',
			api_key_hash: null,
			app_id: 'ai',
			skill_id: 'ask',
			total_credits: 3,
			entry_count: 1,
			updated_at: 8
		},
		{
			type: 'app',
			chat_id: null,
			api_key_hash: null,
			app_id: 'audio',
			skill_id: 'transcribe',
			usage_type: 'realtime_transcription_interrupted',
			started_minutes: 1,
			total_credits: 8,
			entry_count: 1,
			updated_at: 7
		},
		{
			type: 'api_key',
			chat_id: null,
			api_key_hash: 'api-hash',
			app_id: 'web',
			skill_id: 'search',
			total_credits: 3,
			entry_count: 1,
			updated_at: 6
		},
		{
			type: 'device',
			chat_id: null,
			api_key_hash: 'cli:device-hash',
			app_id: 'code',
			skill_id: 'run',
			total_credits: 4,
			entry_count: 1,
			updated_at: 5
		},
		{
			type: 'workflow',
			chat_id: null,
			api_key_hash: null,
			app_id: 'weather',
			skill_id: 'forecast',
			total_credits: 7,
			entry_count: 1,
			updated_at: 4
		},
		{
			type: 'workflow_test',
			chat_id: null,
			api_key_hash: null,
			app_id: 'web',
			skill_id: 'search',
			total_credits: 5,
			entry_count: 1,
			updated_at: 3
		},
		{
			type: 'benchmark',
			chat_id: null,
			api_key_hash: null,
			app_id: 'ai',
			skill_id: 'ask',
			total_credits: 6,
			entry_count: 1,
			updated_at: 2
		},
		{
			type: 'unattributed',
			chat_id: null,
			api_key_hash: null,
			app_id: 'ai',
			skill_id: 'ask',
			total_credits: 2,
			entry_count: 1,
			updated_at: 1
		}
	]
};

test.describe('Usage overview component preview', () => {
	// contract-test: direct surface=gui.web assertions=billing.usage.landing-complete,settings-ui.composition.canonical-and-accessible,settings-ui.localization.visible-content-resolves
	test('shows every charged context once with concise descriptions and a reconciled total', async ({
		page
	}) => {
		await page.route('**/v1/settings/usage/daily-overview**', async (route) => {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					days: [completeUsageDay],
					requested_days: 7,
					total_days: 1,
					has_more_days: false
				})
			});
		});

		await page.goto(
			'/dev/preview/settings/SettingsUsage?theme=light&background=%23dbeafe&width=768&chrome=0'
		);
		await waitForComponentPreview(page);

		await expect(page.getByTestId('usage-overview-day-heading')).toContainText(/38\s*credits/i);
		await expect(page.getByTestId('usage-overview-chat-row')).toHaveCount(1);
		await expect(page.getByTestId('usage-overview-app-row')).toContainText(/audio/i);
		await expect(page.getByTestId('usage-overview-app-row')).toContainText(
			/interrupted recording/i
		);
		await expect(page.getByTestId('usage-overview-app-row')).toContainText(/1 started minute/i);
		await expect(page.getByTestId('usage-overview-api-device-row')).toHaveCount(2);
		await expect(page.getByTestId('usage-overview-workflow-row')).toHaveCount(2);
		await expect(page.getByTestId('usage-overview-other-row')).toHaveCount(2);
		await expect(page.getByTestId('usage-overview-other-row').last()).toContainText(
			/original context unavailable/i
		);

		const panel = page.locator('.tab-content-panel');
		const layout = await panel.evaluate((element) => ({
			clientWidth: element.clientWidth,
			scrollWidth: element.scrollWidth
		}));
		expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
	});
});
