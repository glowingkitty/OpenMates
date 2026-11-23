/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (the attached screenshot shows the named notice and its counter)
/**
 * Project result notice: named, live, and never replayed.
 *
 * "Your Project result is ready." used to pop up (x4) every time the tab opened, for results
 * saved days earlier, and a result saved while the tab was open only showed up at the next
 * open. The notification list and stream are answered by the test; the Project is real, so
 * its name is decrypted on the device:
 *   1. A stored result from the last hour is announced once, naming the Project.
 *   2. Stored results older than an hour are not announced.
 *   3. A result delivered on the live stream is announced at once, naming the Project (it folds into the same notice, x2).
 *   4. After a reload nothing already announced is announced again.
 */
import type { Page, Route } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { naturalProjectName } = require('./helpers/project-names');

const HOUR_MS = 60 * 60 * 1000;

function readyEvent(id: string, projectId: string, ageMs: number) {
	return {
		id,
		type: 'project.authoring_ready',
		created_at: new Date(Date.now() - ageMs).toISOString(),
		safe_title_key: 'apps.openmates',
		safe_body_key: 'notifications.project_authoring.ready',
		routing: { project_id: projectId, result_kind: 'focus', result_id: `item-${id}`, job_id: `job-${id}` },
		metadata: { status: 'ready' },
		read_at: null,
	};
}

async function createProject(page: Page, name: string): Promise<string> {
	await page.goto(getE2EDebugUrl('/projects'), { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });
	const created = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/v1/projects') && response.ok());
	await page.getByTestId('project-input-textarea').fill(name);
	await page.getByTestId('project-input-submit').click();
	await page.getByTestId('project-write-policy-apply-and-show').check();
	await page.getByTestId('project-write-policy-confirm').click();
	return (await (await created).json()).project.project_id as string;
}

test.describe('Project result notice', () => {
	// contract-test: direct surface=gui.web assertions=notifications.delivery.foreground-chat-suppression
	test('names the Project, shows a live result at once, and never replays old or seen results', async ({ page }: { page: Page }) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:projects']);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
		const projectName = naturalProjectName('Kitchen renovation');
		const projectId = await createProject(page, projectName);

		const stored = [
			readyEvent('stored-recent', projectId, 5 * 60 * 1000),
			readyEvent('stored-old-1', projectId, 2 * 24 * HOUR_MS),
			readyEvent('stored-old-2', projectId, 3 * 24 * HOUR_MS),
			readyEvent('stored-old-3', projectId, 5 * 24 * HOUR_MS),
		];
		const live = readyEvent('live-now', projectId, 0);
		await page.route('**/v1/notifications?*', (route: Route) => route.fulfill({ json: { events: stored } }));
		await page.route('**/v1/notifications', (route: Route) => route.fulfill({ json: { events: stored } }));
		await page.route('**/v1/notifications/stream', (route: Route) => route.fulfill({
			status: 200,
			headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' },
			body: `: connected\n\nevent: notification\ndata: ${JSON.stringify(live)}\n\n`,
		}));

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		// The recent stored result and the live result share one text, so they fold into one notice with a x2 counter.
		const notice = page.getByTestId('notification').filter({ hasText: projectName });
		await expect(notice).toHaveCount(1, { timeout: 30000 });
		await expect(notice.getByTestId('notification-repeat-count')).toContainText('2');
		// The three results from days ago stay silent (they would have made it x5), and the text is never the generic one.
		await expect(page.getByTestId('notification').filter({ hasText: /Your Project result is ready/ })).toHaveCount(0);
		await page.screenshot({ path: test.info().outputPath('named-notices.png') });
		await test.info().attach('named-notices', { path: test.info().outputPath('named-notices.png'), contentType: 'image/png' });

		await page.reload({ waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(8000);
		// The recent stored result and the live result were already announced on this device.
		await expect(page.getByTestId('notification').filter({ hasText: projectName })).toHaveCount(0);
	});
});
