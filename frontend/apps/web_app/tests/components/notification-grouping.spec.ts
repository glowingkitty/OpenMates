// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import type { Page, Locator } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';

const ADD_EVENT = 'openmates:e2e:add-notifications';
const ACTION_EVENT = 'openmates:e2e:notification-action';
const error = {
	type: 'error',
	title: 'Failed to save changes',
	message: 'Please try again.',
	duration: 0
};

async function inject(page: Page, notifications: Record<string, unknown>[]) {
	await page.evaluate(
		({ eventName, notifications }) => {
			window.dispatchEvent(new CustomEvent(eventName, { detail: { notifications } }));
		},
		{ eventName: ADD_EVENT, notifications }
	);
}

async function expectCount(card: Locator, count: number) {
	await expect(card.getByTestId('notification-repeat-count')).toHaveText(`×${count}`);
	await expect(
		card.getByRole('img', { name: `Triggered ${count} times`, exact: true })
	).toBeVisible();
}

async function expectHeaderFits(card: Locator) {
	const geometry = await card.evaluate((element) => {
		const header = element.querySelector('.notification-header')!;
		const count = header
			.querySelector('[data-testid="notification-repeat-count"]')!
			.getBoundingClientRect();
		const dismiss = header
			.querySelector('[data-testid="notification-dismiss"]')!
			.getBoundingClientRect();
		const bounds = element.getBoundingClientRect();
		return {
			left: bounds.left,
			right: bounds.right,
			countRight: count.right,
			dismissLeft: dismiss.left,
			dismissRight: dismiss.right,
			overflow: element.scrollWidth - element.clientWidth,
			viewport: innerWidth
		};
	});
	expect(geometry.left).toBeGreaterThanOrEqual(0);
	expect(geometry.right).toBeLessThanOrEqual(geometry.viewport);
	expect(geometry.countRight).toBeLessThanOrEqual(geometry.dismissLeft);
	expect(geometry.dismissRight).toBeLessThanOrEqual(geometry.right);
	expect(geometry.overflow).toBeLessThanOrEqual(1);
}

const proofProfile = process.env.PLAYWRIGHT_PROOF_VIDEO_PROFILE;
const profiles = [
	{ name: 'laptop light', width: 1365, height: 768, theme: 'light' },
	{ name: 'phone dark', width: 390, height: 844, theme: 'dark' }
].filter(
	(profile) =>
		!proofProfile || profile.name.startsWith(proofProfile === 'web-phone' ? 'phone' : 'laptop')
);

for (const selected of profiles) {
	const profile = {
		...selected,
		width: Number(process.env.PLAYWRIGHT_VIDEO_WIDTH || selected.width),
		height: Number(process.env.PLAYWRIGHT_VIDEO_HEIGHT || selected.height)
	};
	test.describe(profile.name, () => {
		test.use({ viewport: { width: profile.width, height: profile.height } });
		const preview = (component: string, extra = '') =>
			`/dev/preview/${component}?theme=${profile.theme}&background=%23dbeafe&width=${profile.width}&chrome=0${extra}`;

		async function openStack(page: Page) {
			await page.addInitScript(() => {
				sessionStorage.setItem(
					'openmates_e2e_log_forwarding',
					JSON.stringify({ runId: 'notification-grouping', token: 'local-e2e' })
				);
			});
			await page.goto(preview('NotificationStack'));
			await waitForComponentPreview(page);
			await page.waitForFunction(
				() => sessionStorage.getItem('openmates_e2e_notification_stack_ready') === 'true'
			);
		}

		// contract-test: direct surface=gui.web assertions=notifications.web.duplicate-grouping,notifications.web.duplicate-lifecycle,notifications.web.stacked-deck
		test('repeated errors update one card, retain its place, and dismiss once', async ({
			page
		}) => {
			await openStack(page);
			const cards = page.getByTestId('notification-stack-item');
			await inject(page, [error]);
			await expect(cards).toHaveCount(1);
			await expect(cards.getByTestId('notification-repeat-count')).toHaveCount(0);
			const original = await cards.first().elementHandle();

			await test.step('Five triggers share one accessible error card', async () => {
				await inject(page, [error, error]);
				await inject(page, [error, error]);
				await expect(cards).toHaveCount(1);
				await expectCount(cards.first(), 5);
				expect(await original!.evaluate((element) => element.isConnected)).toBe(true);
				await expectHeaderFits(cards.first());
			});

			await test.step('A repeated older error stays behind a newer distinct card', async () => {
				await inject(page, [
					{ type: 'info', title: 'Download ready', message: 'Your file is ready.', duration: 0 }
				]);
				await inject(page, [error]);
				await expect(cards).toHaveCount(2);
				await expect(cards.first()).toContainText('Download ready');
				await expect(cards.nth(1).getByTestId('notification-repeat-count')).toHaveText('×6');
				await expect(cards.nth(1)).toHaveAttribute('aria-hidden', 'true');
				await cards.first().getByTestId('notification-dismiss').click();
				await expect(cards).toHaveCount(1);
				await expectCount(cards.first(), 6);
				await expectHeaderFits(cards.first());
			});

			await test.step('One keyboard dismissal clears the group and a later error starts fresh', async () => {
				const dismiss = cards.first().getByTestId('notification-dismiss');
				await dismiss.hover();
				await dismiss.focus();
				await expect(dismiss).toBeFocused();
				await dismiss.press('Enter');
				await expect(cards).toHaveCount(0);
				await inject(page, [error]);
				await expect(cards).toHaveCount(1);
				await expect(cards.getByTestId('notification-repeat-count')).toHaveCount(0);
				await cards.first().getByTestId('notification-dismiss').click();
				await expect(cards).toHaveCount(0);
			});
		});

		// contract-test: direct surface=gui.web assertions=notifications.web.duplicate-grouping,notifications.web.duplicate-lifecycle
		test('chat targets stay separate and one action handles a repeated keyed group', async ({
			page
		}) => {
			await openStack(page);
			const cards = page.getByTestId('notification-stack-item');
			const chat = {
				type: 'chat_message',
				chatTitle: 'Updates',
				message: 'Your results are ready.',
				duration: 0
			};
			await inject(page, [
				{ ...chat, chatId: 'chat-one' },
				{ ...chat, chatId: 'chat-two' }
			]);
			await inject(page, [
				{ ...chat, chatId: 'chat-one' },
				{ ...chat, chatId: 'chat-two' }
			]);
			await expect(cards).toHaveCount(2);
			await expectCount(cards.first(), 2);
			await expect(cards.first().getByTestId('chat-notification')).toHaveAttribute(
				'data-chat-id',
				'chat-two'
			);
			await expectHeaderFits(cards.first());
			await cards.first().getByTestId('notification-dismiss').click();
			await expect(cards).toHaveCount(1);
			await expectCount(cards.first(), 2);
			await expect(cards.first().getByTestId('chat-notification')).toHaveAttribute(
				'data-chat-id',
				'chat-one'
			);
			await cards.first().getByTestId('notification-dismiss').click();
			await expect(cards).toHaveCount(0);

			await page.evaluate((eventName) => {
				document.body.dataset.notificationActions = '0';
				window.addEventListener(eventName, () => {
					document.body.dataset.notificationActions = String(
						Number(document.body.dataset.notificationActions) + 1
					);
				});
			}, ACTION_EVENT);
			const actionable = {
				...error,
				dedupeKey: 'retry-save',
				actionLabel: 'Retry',
				actionEventName: ACTION_EVENT
			};
			await inject(page, [actionable, actionable, actionable]);
			await expect(cards).toHaveCount(1);
			await expectCount(cards.first(), 3);
			await cards.first().getByTestId('notification-action').click();
			await expect(page.locator('body')).toHaveAttribute('data-notification-actions', '1');
			await expect(cards).toHaveCount(0);
		});

		// contract-test: direct surface=gui.web assertions=notifications.web.duplicate-grouping
		test('standard, chat, and count previews keep the counter readable', async ({ page }) => {
			for (const component of ['Notification', 'ChatMessageNotification']) {
				await page.goto(preview(component));
				await waitForComponentPreview(page);
				await expect(page.getByTestId('notification-repeat-count')).toHaveCount(0);
				await page.goto(preview(component, '&variant=repeated'));
				await waitForComponentPreview(page);
				const card = page.getByTestId(
					component === 'Notification' ? 'notification' : 'chat-notification'
				);
				await expectCount(card, 5);
				await expectHeaderFits(card);
			}
			await page.goto(preview('NotificationRepeatCount', '&variant=many'));
			await waitForComponentPreview(page);
			await expect(page.getByTestId('notification-repeat-count')).toHaveText('×1000');
			await expect(
				page.getByRole('img', { name: 'Triggered 1000 times', exact: true })
			).toBeVisible();
		});
	});
}
