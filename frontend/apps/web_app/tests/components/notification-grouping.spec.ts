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
				// The one-time "Sounds are on" notice would add its own card on the first error.
				localStorage.setItem('openmates_event_sound_notice_shown', 'true');
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


		// contract-test: supporting surface=gui.web assertions=notifications.delivery.foreground-chat-suppression
		test('a chat notice for the chat the user just left through New Chat is not dismissed at once', async ({ page }) => {
			await openStack(page);
			const cards = page.getByTestId('notification-stack-item');
			const chatNotice = { type: 'chat_message', chatId: 'left-chat', chatTitle: 'Recipe app', title: 'Recipe app', message: '✅ Added a recipe list', duration: 0 };
			await test.step('The user is in the chat, then starts a new one (hash cleared without an event)', async () => {
				await page.evaluate(() => { window.location.hash = 'chat-id=left-chat'; });
				await page.evaluate(() => history.replaceState(null, '', location.pathname + location.search));
			});
			await test.step('A card for the chat just left is shown', async () => {
				await inject(page, [chatNotice]);
				await expect(cards).toHaveCount(1);
				await expect(cards.first()).toContainText('Added a recipe list');
				await page.waitForTimeout(1000);
				await expect(cards).toHaveCount(1);
				await test.info().attach('chat-notice-after-new-chat', { body: await page.screenshot(), contentType: 'image/png' });
			});
		});

		// contract-test: supporting surface=gui.web assertions=notifications.web.stacked-deck,pii.composer.detect-redact-exclude
		test('a persistent recovery notification keeps its retry action through upward swipes', async ({ page }) => {
			await openStack(page);
			const cards = page.getByTestId('notification-stack-item');
			await inject(page, [{
				...error, title: 'Message needs privacy retry', dismissible: false,
				actionLabel: 'Retry message', actionEventName: ACTION_EVENT,
			}]);
			const recovery = cards.first();
			await expect(recovery).toContainText('Message needs privacy retry');
			await expect(recovery.getByTestId('notification-dismiss')).toHaveCount(0);
			await expect(recovery.getByTestId('notification-action')).toBeVisible();
			const swipeUp = async () => {
				await cards.first().evaluate(async (element) => {
					await Promise.allSettled(element.getAnimations().map((animation) => animation.finished));
				});
				const bounds = await cards.first().getByTestId('notification').boundingBox();
				expect(bounds).not.toBeNull();
				const x = bounds!.x + bounds!.width / 2;
				const y = bounds!.y + 25;
				await page.mouse.move(x, y);
				await page.mouse.down();
				await page.mouse.move(x, y - 90, { steps: 5 });
				await page.mouse.up();
			};
			await test.step('Recovery remains available after a dismissal gesture', async () => {
				await swipeUp();
				await expect(cards).toHaveCount(1);
				await expect(recovery).toHaveAttribute('data-motion-state', 'entered');
				await expect(recovery.getByTestId('notification-action')).toBeVisible();
			});
			await test.step('Ordinary notifications retain their default swipe dismissal', async () => {
				await inject(page, [{ type: 'info', title: 'Ordinary notification', message: 'Can be dismissed', duration: 0 }]);
				await expect(cards).toHaveCount(2);
				await expect(cards.first()).toContainText('Ordinary notification');
				await expect(cards.first().getByTestId('notification-dismiss')).toBeVisible();
				await swipeUp();
				await expect(cards).toHaveCount(1);
				await expect(cards.first()).toContainText('Message needs privacy retry');
				await expect(cards.first().getByTestId('notification-action')).toBeVisible();
			});
		});

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
		test('identical chat text joins one card while another chat title stays separate', async ({
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
				{ ...chat, chatId: 'chat-two' },
				{ ...chat, chatId: 'chat-three', chatTitle: 'Garden plans' }
			]);
			await inject(page, [
				{ ...chat, chatId: 'chat-one' },
				{ ...chat, chatId: 'chat-two' }
			]);
			await expect(cards).toHaveCount(2);
			await expect(cards.first().getByTestId('notification-repeat-count')).toHaveCount(0);
			await cards.first().getByTestId('notification-dismiss').click();
			await expect(cards).toHaveCount(1);
			await expectCount(cards.first(), 4);
			// The first trigger keeps its destination.
			await expect(cards.first().getByTestId('chat-notification')).toHaveAttribute(
				'data-chat-id',
				'chat-one'
			);
			await expectHeaderFits(cards.first());
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

		// contract-test: direct surface=gui.web assertions=notifications.web.duplicate-grouping,notifications.web.duplicate-lifecycle
		test('the same warning fired 10 times under different keys is one ×10 card that one close removes', async ({
			page
		}, testInfo) => {
			await openStack(page);
			const cards = page.getByTestId('notification-stack-item');
			// The test hook takes a few notifications per event, so fire them one by one.
			for (let index = 0; index < 10; index += 1) {
				await inject(page, [
					{
						type: 'warning',
						title: 'Saved result',
						message: 'A saved result has a conflicting revision. Review the chat before saving changes again.',
						duration: 0,
						dedupeKey: `embed-write-conflict:embed-${index}`
					}
				]);
			}
			await expect(cards).toHaveCount(1);
			await expectCount(cards.first(), 10);
			await expectHeaderFits(cards.first());
			await testInfo.attach(`warning-x10-${profile.name.replace(' ', '-')}`, {
				body: await cards.first().screenshot(),
				contentType: 'image/png'
			});
			await cards.first().getByTestId('notification-dismiss').click();
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

// contract-test: supporting surface=gui.web assertions=live-collab.offline.merge-on-reconnect
test('the private copy warning keeps the download action visible on a phone', async ({ page }, testInfo) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto('/dev/preview/Notification?variant=privateCopy&theme=light&background=%23dbeafe&width=390&chrome=0');
	await waitForComponentPreview(page);
	await expect(page.getByText('Access was removed. You can download a private copy of your unsent edits.')).toBeVisible();
	const download = page.getByRole('button', { name: 'Download private copy', exact: true });
	await expect(download).toBeInViewport();
	await testInfo.attach('private-copy-warning-phone', { body: await page.screenshot(), contentType: 'image/png' });
	const invoked = page.evaluate(() => new Promise<void>((resolve) => {
		window.addEventListener('openmates:preview-private-copy', () => resolve(), { once: true });
	}));
	await download.click();
	await invoked;
});
