/**
 * Mobile in-app notification contract coverage.
 *
 * Uses the deterministic first-visit language suggestion to verify the shared
 * notification card's viewport insets, duration indicator, and auto-dismiss.
 * Runs against the deployed dev app through scripts/tests.py.
 */
import { expect, test } from './helpers/cookie-audit';

// contract-test: direct surface=gui.web assertions=notifications.web.mobile-insets,notifications.web.timed-dismissal
test('mobile notification stays inset and auto-dismisses with visible progress', async ({ browser }) => {
	const context = await browser.newContext({ locale: 'de-DE', viewport: { width: 390, height: 844 } });
	const page = await context.newPage();

	await page.goto('/');
	const notification = page.getByTestId('notification').filter({ hasText: 'Language Detected' });
	await expect(notification).toBeVisible({ timeout: 15000 });
	const stackItem = page.getByTestId('notification-stack-item').filter({ has: notification });
	await stackItem.evaluate(async (element) => {
		await Promise.allSettled(element.getAnimations().map((animation) => animation.finished));
	});
	const exitingState = stackItem.evaluate((element: HTMLElement) =>
		new Promise<{ inert: boolean; ariaHidden: string | null; pointerEvents: string } | null>((resolve) => {
			const timeout = window.setTimeout(() => {
				observer.disconnect();
				resolve(null);
			}, 8000);
			const observer = new MutationObserver(() => {
				if (element.dataset.motionState !== 'exiting') return;
				window.clearTimeout(timeout);
				observer.disconnect();
				resolve({
					inert: element.inert,
					ariaHidden: element.getAttribute('aria-hidden'),
					pointerEvents: getComputedStyle(element).pointerEvents
				});
			});
			observer.observe(element, { attributes: true });
		})
	);

	const notificationBox = await notification.boundingBox();
	expect(notificationBox, 'mobile notification should be measurable').not.toBeNull();
	expect(notificationBox!.x, 'mobile notification inline-start inset').toBeCloseTo(10, 0);
	expect(390 - notificationBox!.x - notificationBox!.width, 'mobile notification inline-end inset').toBeCloseTo(10, 0);
	expect(notificationBox!.y, 'mobile notification top inset').toBeCloseTo(10, 0);

	const progress = notification.getByTestId('notification-progress');
	await expect(progress).toBeVisible();
	await expect(progress).toHaveAttribute('data-duration-ms', '7000');
	expect(await exitingState, 'auto-dismiss should enter an inert outro state').toEqual({
		inert: true,
		ariaHidden: 'true',
		pointerEvents: 'none'
	});
	await expect(notification).not.toBeVisible({ timeout: 2000 });
	await expect(stackItem).toHaveCount(0);

	await context.close();
});
