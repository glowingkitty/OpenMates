// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import type { Page } from '@playwright/test';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';

const ADD_EVENT = 'openmates:e2e:add-notifications';
type CueRecord = { cue: string; outcome: string };

async function recordCues(page: Page) {
	await page.addInitScript(() => {
		sessionStorage.setItem(
			'openmates_e2e_log_forwarding',
			JSON.stringify({ runId: 'event-sounds', token: 'local-e2e' })
		);
		const target = window as Window & { __eventCues?: CueRecord[] };
		target.__eventCues = [];
		window.addEventListener('openmates:event-cue', (event) => {
			target.__eventCues!.push((event as CustomEvent<CueRecord>).detail);
		});
	});
}

async function cues(page: Page): Promise<CueRecord[]> {
	return page.evaluate(
		() => (window as Window & { __eventCues?: CueRecord[] }).__eventCues ?? []
	);
}

async function inject(page: Page, notification: Record<string, unknown>) {
	await page.evaluate(
		({ eventName, notification }) => {
			window.dispatchEvent(
				new CustomEvent(eventName, { detail: { notifications: [notification] } })
			);
		},
		{ eventName: ADD_EVENT, notification }
	);
}

const profiles = [
	{ name: 'laptop light', width: 1365, height: 768, theme: 'light' },
	{ name: 'phone dark', width: 390, height: 844, theme: 'dark' }
];

for (const profile of profiles) {
	test.describe(profile.name, () => {
		test.use({ viewport: { width: profile.width, height: profile.height } });
		const preview = (component: string) =>
			`/dev/preview/${component}?theme=${profile.theme}&background=%23dbeafe&width=${profile.width}&chrome=0`;

		// contract-test: direct surface=gui.web assertions=notifications.sounds.important-events,notifications.sounds.quiet-window,notifications.sounds.first-cue-opt-out,notifications.sounds.silent-mode
		test('an error sounds once, later events in the quiet window are dropped, and the notice turns sounds off', async ({ page }, testInfo) => {
			await recordCues(page);
			await page.goto(preview('NotificationStack'));
			await waitForComponentPreview(page);
			await page.waitForFunction(
				() => sessionStorage.getItem('openmates_e2e_notification_stack_ready') === 'true'
			);

			// Before any user gesture the browser keeps audio locked: nothing sounds.
			await inject(page, { type: 'error', title: 'Could not load', message: 'First attempt.' });
			await expect.poll(() => cues(page)).toEqual([{ cue: 'error', outcome: 'audio_locked' }]);
			await expect(page.getByTestId('notification').filter({ hasText: 'Sounds are on' })).toHaveCount(0);

			await page.mouse.click(5, 5);
			await inject(page, { type: 'error', title: 'Failed to save changes', message: 'Please try again.' });
			await expect.poll(async () => (await cues(page)).at(-1)).toEqual({ cue: 'error', outcome: 'played' });

			const notice = page.getByTestId('notification').filter({ hasText: 'Sounds are on' });
			await expect(notice).toBeVisible();
			const turnOff = notice.getByTestId('notification-action');
			await expect(turnOff).toHaveText('Turn off sounds');
			const box = (await notice.boundingBox())!;
			expect(box.x).toBeGreaterThanOrEqual(0);
			expect(box.x + box.width).toBeLessThanOrEqual(profile.width);
			await waitForComponentMotion(page.getByTestId('notification-stack-item').first());
			await testInfo.attach(`first-sound-notice-${profile.width}`, {
				body: await page.screenshot(),
				contentType: 'image/png'
			});

			// A second event right after the sound is dropped, not queued.
			await inject(page, { type: 'chat_message', title: 'New message', message: 'Hello there', chatId: 'preview-chat', chatTitle: 'Preview' });
			await expect.poll(async () => (await cues(page)).at(-1)).toEqual({ cue: 'notification', outcome: 'quiet_window' });
			await page.waitForTimeout(1500);
			expect((await cues(page)).filter((entry) => entry.outcome === 'played')).toHaveLength(1);

			// The newer chat card sits in front of the notice; dismiss it to reach the notice again.
			await page.getByTestId('chat-notification').getByTestId('notification-dismiss').click();
			await expect(page.getByTestId('chat-notification')).toHaveCount(0);
			await turnOff.click();
			await expect(notice).toBeHidden();
			expect(await page.evaluate(() => localStorage.getItem('openmates_silent_mode'))).toBe('true');
			await inject(page, { type: 'error', title: 'Another failure', message: 'Still broken.' });
			await expect.poll(async () => (await cues(page)).at(-1)).toEqual({ cue: 'error', outcome: 'silent_mode' });

			// The notice is one-time: it does not come back after sounds are turned on again.
			await page.evaluate(() => localStorage.removeItem('openmates_silent_mode'));
			await page.reload();
			await waitForComponentPreview(page);
			await page.waitForFunction(
				() => sessionStorage.getItem('openmates_e2e_notification_stack_ready') === 'true'
			);
			await page.mouse.click(5, 5);
			await inject(page, { type: 'error', title: 'Failed again', message: 'Please retry.' });
			await expect.poll(async () => (await cues(page)).at(-1)).toEqual({ cue: 'error', outcome: 'played' });
			await expect(page.getByTestId('notification').filter({ hasText: 'Sounds are on' })).toHaveCount(0);
		});

		// contract-test: direct surface=gui.web assertions=notifications.sounds.silent-mode
		test('the silent mode toggle in notification settings switches sounds off and on', async ({ page }, testInfo) => {
			await recordCues(page);
			await page.goto(preview('settings/SettingsNotifications'));
			const canvas = await waitForComponentPreview(page);
			const row = page.getByTestId('silent-mode');
			await expect(row).toBeVisible();
			await expect(row).toContainText('Silent mode');
			await expect(row).toContainText('Turns off sounds and vibrations on this device');
			const toggle = row.getByRole('checkbox');
			await expect(toggle).not.toBeChecked();
			const overflow = await row.evaluate((element) => element.scrollWidth - element.clientWidth);
			expect(overflow).toBeLessThanOrEqual(1);
			await testInfo.attach(`silent-mode-off-${profile.width}`, {
				body: await canvas.screenshot(),
				contentType: 'image/png'
			});

			await row.getByTestId('toggle-container').click();
			await expect(toggle).toBeChecked();
			expect(await page.evaluate(() => localStorage.getItem('openmates_silent_mode'))).toBe('true');
			await testInfo.attach(`silent-mode-on-${profile.width}`, {
				body: await canvas.screenshot(),
				contentType: 'image/png'
			});

			await page.reload();
			await waitForComponentPreview(page);
			await expect(page.getByTestId('silent-mode').getByRole('checkbox')).toBeChecked();
			await page.getByTestId('silent-mode').getByTestId('toggle-container').click();
			await expect(page.getByTestId('silent-mode').getByRole('checkbox')).not.toBeChecked();
			expect(await page.evaluate(() => localStorage.getItem('openmates_silent_mode'))).toBeNull();
		});
	});
}
