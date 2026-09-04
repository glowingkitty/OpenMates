/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Stacked global notification contract coverage.
 *
 * Uses the existing E2E debug session gate to inject local notification-store
 * entries on the deployed app, then verifies newest-first stack depth, inert
 * back cards, and front-card dismissal promotion on proof profiles.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const E2E_ADD_NOTIFICATIONS_EVENT = 'openmates:e2e:add-notifications';
const E2E_LOG_FORWARDING_SESSION_KEY = 'openmates_e2e_log_forwarding';
const E2E_NOTIFICATION_STACK_READY_KEY = 'openmates_e2e_notification_stack_ready';
const E2E_NOTIFICATION_ACTION_EVENT = 'openmates:e2e:notification-action';
const PROOF_VISIBLE_STATE_MS = 2000;

// contract-test: direct surface=gui.web assertions=notifications.web.stacked-deck
test('global notifications stack behind the front card, show activity, and promote on dismiss', async ({ page }) => {
	test.setTimeout(60000);
	await page.emulateMedia({ reducedMotion: 'no-preference' });

	await page.addInitScript((key: string) => {
		sessionStorage.setItem(key, JSON.stringify({ runId: 'notification-stack', token: 'local-e2e' }));
	}, E2E_LOG_FORWARDING_SESSION_KEY);
	await page.goto(getE2EDebugUrl('/#chat-id=demo-who-develops-openmates'), { waitUntil: 'domcontentloaded' });
	await page.waitForFunction((key: string) => Boolean(sessionStorage.getItem(key)), E2E_LOG_FORWARDING_SESSION_KEY, {
		timeout: 10000
	});
	await page.waitForFunction((key: string) => sessionStorage.getItem(key) === 'true', E2E_NOTIFICATION_STACK_READY_KEY, {
		timeout: 10000
	});

	const stack = page.getByTestId('notification-stack');
	const items = page.getByTestId('notification-stack-item');
	const introTop = await page.evaluate(async (eventName: string) => {
		const motionStarted = new Promise<number | null>((resolve) => {
			const timeout = window.setTimeout(() => {
				observer.disconnect();
				resolve(null);
			}, 5000);
			const inspectMotion = () => {
				const element = document.querySelector<HTMLElement>('[data-testid="notification-stack-item"]');
				if (!element) return;

				observer.disconnect();
				window.clearTimeout(timeout);
				requestAnimationFrame(() => {
					resolve(element.getBoundingClientRect().top);
				});
			};
			const observer = new MutationObserver(inspectMotion);
			observer.observe(document.body, { childList: true, subtree: true });
		});
		window.dispatchEvent(
			new CustomEvent(eventName, {
				detail: {
					notifications: [
						{
							type: 'info',
							title: 'First stacked notification',
							message: 'This oldest notification waits behind newer cards.',
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
							message: 'This newest notification stays readable and interactive.',
							duration: 0,
							isProcessing: true
						}
					]
				}
			})
		);
		return motionStarted;
	}, E2E_ADD_NOTIFICATIONS_EVENT);
	await expect(stack).toBeVisible({ timeout: 10000 });
	await expect(items).toHaveCount(3);
	expect(introTop, 'new notifications should render while moving in from above').not.toBeNull();
	await expect(items.nth(0)).toContainText('Third stacked notification');
	await expect(items.nth(1)).toContainText('Second stacked notification');
	await expect(items.nth(2)).toContainText('First stacked notification');
	await expect(items.nth(0).getByTestId('notification-activity')).toBeVisible();
	await expect(items.nth(0).getByTestId('notification-progress')).toHaveCount(0);

	await items.evaluateAll(async (elements: HTMLElement[]) => {
		await Promise.allSettled(elements.flatMap((element) => element.getAnimations().map((animation) => animation.finished)));
	});
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
	expect(introTop!).toBeLessThan(stackMetrics[0].top);
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

	await page.waitForTimeout(PROOF_VISIBLE_STATE_MS);

	await items.nth(0).getByTestId('notification-dismiss').click();
	const outgoingItem = page.locator('[data-testid="notification-stack-item"][data-motion-state="exiting"]');
	await expect(outgoingItem, 'the outgoing notification should remain mounted while sliding out').toHaveCount(1);
	await expect(outgoingItem).toHaveAttribute('aria-hidden', 'true');
	await expect(outgoingItem).toHaveJSProperty('inert', true);
	await expect(outgoingItem).toHaveCSS('pointer-events', 'none');
	const outroMotion = await outgoingItem.evaluate(async (element: HTMLElement) => {
		const startTop = element.getBoundingClientRect().top;
		await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
		return { startTop, movingTop: element.getBoundingClientRect().top };
	});
	expect(outroMotion.movingTop, 'dismissed notifications should animate out toward the top').toBeLessThan(
		outroMotion.startTop
	);
	await expect(items).toHaveCount(2, { timeout: 2000 });
	await expect(items.nth(0)).toContainText('Second stacked notification');
	await expect(items.nth(0)).toHaveAttribute('data-stack-depth', '0');
	await expect(items.nth(1)).toContainText('First stacked notification');
	await page.waitForTimeout(PROOF_VISIBLE_STATE_MS);

	await page.evaluate((eventName: string) => {
		const e2eWindow = window as typeof window & { __openmatesNotificationActionCount?: number };
		e2eWindow.__openmatesNotificationActionCount = 0;
		window.addEventListener(eventName, () => {
			e2eWindow.__openmatesNotificationActionCount = (e2eWindow.__openmatesNotificationActionCount ?? 0) + 1;
		});
	}, E2E_NOTIFICATION_ACTION_EVENT);
	await page.evaluate(
		({ addEventName, actionEventName }: { addEventName: string; actionEventName: string }) => {
			window.dispatchEvent(
				new CustomEvent(addEventName, {
					detail: {
						notifications: [
							{
								type: 'success',
								title: 'Action notification',
								message: 'This actionable notification dismisses after its primary action fires.',
								duration: 0,
								actionLabel: 'Open chat',
								actionEventName,
								dedupeKey: 'e2e-notification-action-dismisses'
							}
						]
					}
				})
			);
		},
		{ addEventName: E2E_ADD_NOTIFICATIONS_EVENT, actionEventName: E2E_NOTIFICATION_ACTION_EVENT }
	);
	await expect(items).toHaveCount(3);
	await expect(items.nth(0)).toContainText('Action notification');
	await items.nth(0).getByTestId('notification-action').click();
	expect(
		await page.evaluate(() => {
			const e2eWindow = window as typeof window & { __openmatesNotificationActionCount?: number };
			return e2eWindow.__openmatesNotificationActionCount ?? 0;
		})
	).toBe(1);
	await expect(items).toHaveCount(2, { timeout: 2000 });
	await expect(items.nth(0)).toContainText('Second stacked notification');
});
