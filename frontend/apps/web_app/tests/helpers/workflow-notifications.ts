// contract-test-file: infrastructure
/**
 * Locator for Workflow route errors.
 *
 * The Workflows route reports failures through the notification stack, so
 * specs target error notifications instead of a route-local container.
 */
import type { Locator, Page } from '@playwright/test';

export function workflowErrorNotifications(page: Page, text?: string | RegExp): Locator {
	const errors = page.getByTestId('notification').locator('xpath=self::*[contains(@class, "notification-error")]');
	return text === undefined ? errors : errors.filter({ hasText: text });
}
