import { expect, test } from './helpers/cookie-audit';

// playwright-account: not_required reason=mocked_public_status_api

// contract-test: tooling
test('status page uses the daily result when present', async ({ page }) => {
	await page.route('**/v1/status', async (route) => {
		await route.fulfill({
			contentType: 'application/json',
			body: JSON.stringify({
				status: 'operational', last_updated: new Date().toISOString(), uptime_pct: 99.8,
				groups: [], tests: { total: 10, passed: 8, failed: 2, last_run: null, categories: [] },
				incidents: [],
				daily_tests: {
					date: '2026-09-28', status: 'blocked', finalization: 'final',
					areas: {
						unit: { executed: 6772, passed: 6600, failed: 172, skipped: 5 },
						sdk_cli: { executed: 71, passed: 70, failed: 1, skipped: 0 },
						web_e2e: { executed: 0, passed: 0, failed: 0, skipped: 0 },
					},
					apple_e2e: { status: 'not_scheduled', counts: { executed: 0, passed: 0, failed: 0, skipped: 0 } },
					selected_specs: null, admitted_specs: 0, held_specs: null,
					signup: { executed: [], held: [], live_email: { status: 'failed' } },
				},
			}),
		});
	});
	await page.goto('/status', { waitUntil: 'domcontentloaded' });
	const digest = page.getByTestId('daily-test-digest');
	await expect(digest).toContainText('6,772 run · 172 failed');
	await expect(digest).toContainText('No scheduled native run');
	await expect(page.getByText('8/10 passing')).toHaveCount(0);
});
