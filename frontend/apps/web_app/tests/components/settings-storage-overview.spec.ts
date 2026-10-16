import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const overview = {
	total_bytes: 1_610_612_736, total_files: 1, free_bytes: 1_073_741_824,
	logical_s3_bytes: 1_073_741_824, billable_gb: 1, credits_per_gb_per_week: 3,
	weekly_cost_credits: 3, next_billing_date: 1_791_082_800, last_billed_at: null,
	measurement_at: 1_791_072_000,
	metering_source_version: 'logical-s3-v1',
	metering_policy_version: 'personal-storage-1gb-3credits-week-v1',
	metering_categories: { chat_pages: 536_870_912, chat_oversized: 134_217_728,
		cold_chat_graphs: 134_217_728, sealed_recovery: 134_217_728, embed_versions: 134_217_728 },
	breakdown: [{ category: 'other', bytes_used: 536_870_912, file_count: 1 }]
};
const emptyNotice = { episode_id: null, warning_count: 0, deadline_at: null, manual_review: false,
	units: [], has_more: false, next_after_unit_id: null };
const unit = { unit_id: 'a'.repeat(64), kind: 'upload', resource_id: 'upload-resource-001',
	oldest_at: 1_700_000_000, bytes: 536_870_912 };
const notice = { ...emptyNotice, episode_id: 'notice-001', warning_count: 3,
	deadline_at: 1_791_936_000, units: [unit], has_more: true, next_after_unit_id: unit.unit_id };
const preview = '/dev/preview/settings/account/SettingsStorage?theme=light&background=%23dbeafe&width=390&chrome=0';

async function routeOverview(page: import('@playwright/test').Page) {
	await page.route('**/v1/settings/storage', route => route.fulfill({ json: overview }));
}

// contract-test: direct surface=gui.web assertions=billing.storage.logical-usage,billing.storage.weekly-quote,billing.storage.disclosures,billing.storage.personal-expiry-selection,billing.storage.expiry-invoice-closure
// contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible,settings-ui.localization.visible-content-resolves
test('storage preview shows logical categories, measured price and fixed affected units with explicit pagination', async ({ page }) => {
	await routeOverview(page);
	let pages = 0;
	await page.route('**/v1/settings/storage/notice?**', async route => {
		pages++;
		const after = new URL(route.request().url()).searchParams.get('after_unit_id');
		await route.fulfill({ json: after ? { ...notice, has_more: false, next_after_unit_id: null,
			units: [{ ...unit, unit_id: 'b'.repeat(64), kind: 'cold_chat', resource_id: 'chat-resource-002' }] } : notice });
	});
	await page.goto(preview);
	const canvas = await waitForComponentPreview(page);
	for (const label of ['Saved chat history', 'Large chat messages', 'Older chat archives', 'Outputs waiting to sync', 'Artifact history', 'Measured at']) {
		await expect(canvas.getByText(label, { exact: true })).toBeVisible();
	}
	await expect(canvas.getByTestId('storage-pricing-policy')).toContainText('Each started GiB');
	await expect(canvas.getByTestId('storage-pricing-policy')).toContainText('Sundays at 03:00 UTC');
	await expect(canvas).toContainText('1.5 GiB');
	await expect(canvas).toContainText('UTC');
	await expect(canvas.getByTestId('storage-active-notice')).toContainText('four weekly warning emails');
	await expect(canvas.getByTestId('storage-active-notice')).toContainText('waived on expiry');
	await expect(canvas.getByText(unit.unit_id, { exact: true })).toBeVisible();
	await expect(canvas.getByText(unit.resource_id, { exact: true })).toBeVisible();
	await expect(canvas.getByText('512.0 MiB', { exact: true }).last()).toBeVisible();
	const more = canvas.getByRole('button', { name: 'Show more affected units' });
	await more.focus();
	await expect(more).toBeFocused();
	await more.press('Enter');
	await expect(canvas.getByText('b'.repeat(64), { exact: true })).toBeVisible();
	await expect(canvas.getByText(unit.unit_id, { exact: true })).toHaveCount(1);
	await expect(more).toHaveCount(0);
	expect(pages).toBe(2);
	const layout = await canvas.locator('.settings-page-container').evaluate(element => ({ client: element.clientWidth, scroll: element.scrollWidth }));
	expect(layout.scroll).toBeLessThanOrEqual(layout.client + 1);
});

// contract-test: direct surface=gui.web assertions=billing.storage.disclosures
test('storage preview retries a notice error and shows no active notice without inventing affected units', async ({ page }) => {
	await routeOverview(page);
	let fail = true;
	await page.route('**/v1/settings/storage/notice?**', route => fail
		? route.fulfill({ status: 503, json: { detail: 'Unavailable' } })
		: route.fulfill({ json: emptyNotice }));
	await page.goto(preview);
	const canvas = await waitForComponentPreview(page);
	await expect(canvas.getByText('Could not load the affected storage units. Please try again.')).toBeVisible();
	fail = false;
	await canvas.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(canvas.getByTestId('storage-notice-empty')).toBeVisible();
	await expect(canvas.getByTestId('storage-active-notice')).toHaveCount(0);
	await expect(canvas.getByText('Storage unit ID', { exact: true })).toHaveCount(0);
});
