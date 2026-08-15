/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Stacked global notification contract coverage.
 *
 * Uses the existing E2E debug session gate to inject local notification-store
 * entries on the deployed app, then verifies the shared stack depth, inert back
 * cards, and front-card dismissal promotion on phone and laptop proof profiles.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const E2E_ADD_NOTIFICATIONS_EVENT = 'openmates:e2e:add-notifications';
const E2E_LOG_FORWARDING_SESSION_KEY = 'openmates_e2e_log_forwarding';

// contract-test: direct surface=gui.web assertions=notifications.web.stacked-deck
test('global notifications stack behind the front card and promote on dismiss', async ({ page }) => {
	test.setTimeout(60000);

	await page.addInitScript((key: string) => {
		sessionStorage.setItem(key, JSON.stringify({ runId: 'notification-stack', token: 'local-e2e' }));
	}, E2E_LOG_FORWARDING_SESSION_KEY);
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	await page.waitForFunction((key: string) => Boolean(sessionStorage.getItem(key)), E2E_LOG_FORWARDING_SESSION_KEY, {
		timeout: 10000
	});

	const stack = page.getByTestId('notification-stack');
	const items = page.getByTestId('notification-stack-item');
	for (let attempt = 0; attempt < 8; attempt += 1) {
		await page.evaluate((eventName: string) => {
			window.dispatchEvent(
				new CustomEvent(eventName, {
					detail: {
						notifications: [
							{
								type: 'info',
								title: 'First stacked notification',
								message: 'This front notification stays readable and interactive.',
								duration: 0
							},
							{
								type: 'success',
								title: 'Second stacked notification',
								message: 'This notification waits behind the front card.',
								duration: 0
							},
							{
								type: 'warning',
								title: 'Third stacked notification',
								message: 'Only a slim strip remains visible at the back.',
								duration: 0
							}
						]
					}
				})
			);
		}, E2E_ADD_NOTIFICATIONS_EVENT);
		if (await stack.isVisible({ timeout: 500 }).catch(() => false)) break;
	}
	await expect(stack).toBeVisible({ timeout: 10000 });
	await expect(items).toHaveCount(3);
	await expect(items.nth(0)).toContainText('First stacked notification');
	await expect(items.nth(1)).toContainText('Second stacked notification');
	await expect(items.nth(2)).toContainText('Third stacked notification');

	await page.waitForTimeout(500);
	const stackMetrics = await items.evaluateAll((elements: HTMLElement[]) =>
		elements.map((element) => {
			const styles = window.getComputedStyle(element);
			const rect = element.getBoundingClientRect();
			const matrix = new DOMMatrixReadOnly(styles.transform);
			return {
				depth: element.dataset.stackDepth,
				top: rect.top,
				opacity: Number(styles.opacity),
				pointerEvents: styles.pointerEvents,
				transitionDuration: styles.transitionDuration,
				transitionProperty: styles.transitionProperty,
				scale: Number(matrix.a.toFixed(3)),
				ariaHidden: element.getAttribute('aria-hidden'),
				inert: element.inert
			};
		})
	);

	expect(stackMetrics[0].depth).toBe('0');
	expect(stackMetrics[0].opacity).toBeCloseTo(1, 2);
	expect(stackMetrics[0].pointerEvents).toBe('auto');
	expect(stackMetrics[0].transitionProperty).toContain('transform');
	expect(stackMetrics[0].transitionProperty).toContain('opacity');
	expect(stackMetrics[0].transitionDuration).not.toBe('0s');
	expect(stackMetrics[1].depth).toBe('1');
	expect(stackMetrics[1].ariaHidden).toBe('true');
	expect(stackMetrics[1].inert).toBe(true);
	expect(stackMetrics[1].opacity).toBeLessThan(stackMetrics[0].opacity);
	expect(stackMetrics[1].scale).toBeCloseTo(0.955, 2);
	expect(stackMetrics[1].top).toBeLessThan(stackMetrics[0].top);
	expect(stackMetrics[2].depth).toBe('2');
	expect(stackMetrics[2].ariaHidden).toBe('true');
	expect(stackMetrics[2].inert).toBe(true);
	expect(stackMetrics[2].opacity).toBeLessThan(stackMetrics[1].opacity);
	expect(stackMetrics[2].scale).toBeCloseTo(0.91, 2);
	expect(stackMetrics[2].top).toBeLessThan(stackMetrics[1].top);

	await items.nth(0).getByTestId('notification-dismiss').click();
	await expect(items).toHaveCount(2, { timeout: 2000 });
	await expect(items.nth(0)).toContainText('Second stacked notification');
	await expect(items.nth(0)).toHaveAttribute('data-stack-depth', '0');
	await expect(items.nth(1)).toContainText('Third stacked notification');
});
