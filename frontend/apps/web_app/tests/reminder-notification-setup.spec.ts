/* eslint-disable @typescript-eslint/no-require-imports -- Shared Playwright helpers use CommonJS. */
export {};

import type { Page } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');

const credentials = getTestAccount();
const settingsPath = '/#settings/notifications/chat';

function masterToggle(page: Page) {
	return page.getByTestId('email-section').getByTestId('email-notifications-master')
		.locator('input[type="checkbox"]');
}

async function openSettings(page: Page) {
	const snapshot = page.waitForEvent('console', {
		predicate: (message) => message.text().includes('email_notification_settings_snapshot received'),
		timeout: 30_000
	});
	if (new URL(page.url()).hash.split('&')[0] === '#settings/notifications/chat') {
		await page.reload({ waitUntil: 'domcontentloaded' });
	} else {
		await page.goto(getE2EDebugUrl(settingsPath), { waitUntil: 'domcontentloaded' });
	}
	await snapshot;
	await expect(masterToggle(page)).toBeEnabled();
}

async function setEnabled(page: Page, enabled: boolean) {
	const checkbox = masterToggle(page);
	if (await checkbox.isChecked() !== enabled) {
		const ack = page.waitForEvent('console', {
			predicate: (message) => message.text().includes('email_notification_settings_ack received'),
			timeout: 30_000
		});
		await checkbox.locator('..').click();
		await ack;
	}
	await expect(checkbox).toHaveJSProperty('checked', enabled);
}

// contract-test: supporting surface=gui.web assertions=notifications.settings.ack-persisted,notifications.surface.semantic-parity
test('reminder setup respects saved email settings and its activation action opens the working settings page', async ({ page }: { page: Page }) => {
	skipWithoutCredentials(test, credentials.email, credentials.password, credentials.otpKey);
	test.setTimeout(150_000);
	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	const activationEvents: Array<{ action_deep_link?: string }> = [];
	page.on('websocket', (socket) => socket.on('framereceived', (frame) => {
		try {
			const message = JSON.parse(String(frame.payload));
			if (message.type === 'user_notification' && message.payload?.dedupe_key === 'activate-email-notifications') {
				activationEvents.push(message.payload);
			}
		} catch { /* Other frames do not affect reminder setup. */ }
	}));
	await loginToTestAccount(page, undefined, undefined, { waitForEditor: false, credentials });
	await openSettings(page);
	const originallyEnabled = await masterToggle(page).isChecked();
	const reminders = new Set<string>();
	const activationToast = page.getByTestId('notification').filter({ hasText: 'Activate email notifications now' });
	let failure: unknown;

	async function createReminder() {
		const response = await page.request.post(`${apiUrl}/v1/apps/reminder/skills/set-reminder`, {
			data: {
				prompt: 'Notification setup regression', trigger_type: 'specific', timezone: 'UTC',
				trigger_datetime: new Date(Date.now() + 7 * 24 * 3600 * 1000).toISOString(),
				target_type: 'new_chat', new_chat_title: 'Notification setup regression', response_type: 'simple'
			}
		});
		expect(response.ok(), await response.text()).toBe(true);
		const result = await response.json();
		const data = result.data || result;
		expect(data.success).toBe(true);
		expect(data.reminder_id).toBeTruthy();
		reminders.add(data.reminder_id);
		return data;
	}

	async function cancelReminder(id: string) {
		const response = await page.request.delete(`${apiUrl}/v1/settings/reminders/${id}`);
		expect(response.ok(), await response.text()).toBe(true);
		reminders.delete(id);
	}

	try {
		await setEnabled(page, true);
		// A fresh page reads acknowledged server state before creating the reminder.
		await openSettings(page);
		await expect(masterToggle(page)).toBeChecked();
		const enabledReminder = await createReminder();
		expect(enabledReminder.email_notification_warning).toBeNull();
		expect(activationEvents).toHaveLength(0);
		await expect(activationToast).toHaveCount(0);
		await cancelReminder(enabledReminder.reminder_id);

		await setEnabled(page, false);
		await page.getByTestId('icon-button-close').click();
		const disabledReminder = await createReminder();
		expect(disabledReminder.email_notification_warning).toContain('Set up email notifications');
		await expect(activationToast).toBeVisible();
		await expect.poll(() => activationEvents.length).toBe(1);
		expect(activationEvents[0].action_deep_link).toBe('notifications/chat');
		await activationToast.getByRole('button', { name: /go to settings/i }).click();
		const settings = page.locator('[data-testid="settings-menu"].visible');
		await expect(settings).toHaveAttribute('data-active-view', 'notifications/chat');
		await expect(settings.getByTestId('email-section')).toBeVisible();
		await expect(masterToggle(page)).not.toBeChecked();
		await cancelReminder(disabledReminder.reminder_id);
	} catch (error) {
		failure = error;
	}
	try {
		for (const id of reminders) await cancelReminder(id);
		await openSettings(page);
		await setEnabled(page, originallyEnabled);
	} catch (error) {
		if (failure) console.warn('Reminder setup cleanup also failed:', error);
		else failure = error;
	}
	if (failure) throw failure;
});
