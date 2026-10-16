import { expect, type Page, type TestInfo } from '@playwright/test';

/** A restored settings route can appear before its asynchronous data is ready. */
export async function waitForSettingsView(
	page: Page,
	testInfo: TestInfo,
	view: string,
	readyTestId: string
): Promise<void> {
	const menu = page.getByTestId('settings-menu');
	const ready = page.getByTestId(readyTestId);
	try {
		await expect(menu).toHaveAttribute('data-active-view', view, { timeout: 30_000 });
		await expect(ready).toBeVisible({ timeout: 30_000 });
	} catch (error) {
		await testInfo.attach('settings-readiness', {
			body: JSON.stringify({
				expectedView: view,
				activeView: await menu.getAttribute('data-active-view').catch(() => null),
				readyTestId,
				readyElementCount: await ready.count()
			}),
			contentType: 'application/json'
		});
		throw error;
	}
}
