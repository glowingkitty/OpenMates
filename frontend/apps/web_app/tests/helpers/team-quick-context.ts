/**
 * Drive the Teams quick-access controls in product browser flows.
 * Choosing a Team and entering its workspace are separate actions.
 * These helpers preserve that distinction while waiting for the real controls.
 * Personal workspace is reached by turning Team mode off.
 */
import { expect, type Page } from '@playwright/test';

export async function selectTeamInQuickPicker(page: Page, teamId: string, name?: string): Promise<void> {
	const picker = page.getByTestId('team-quick-context-dropdown');
	await expect(picker).toBeVisible({ timeout: 30_000 });
	await picker.click();
	await expect(picker).toHaveAttribute('aria-expanded', 'true');
	await expect(page.getByTestId('team-context-menu')).toBeVisible();
	const option = page.getByTestId(`team-context-option-${teamId}`);
	if (!(await option.isVisible().catch(() => false))) await page.getByTestId('team-context-show-more').click();
	await option.click();
	if (name) await expect(picker).toContainText(name, { timeout: 30_000 });
}

export async function setTeamMode(page: Page, enabled: boolean): Promise<void> {
	const toggle = page.getByTestId('settings-teams-item').getByTestId('toggle-container');
	const input = toggle.locator('input[type="checkbox"]');
	await expect(toggle).toBeVisible({ timeout: 30_000 });
	if ((await input.isChecked()) !== enabled) {
		await expect(input).toBeEnabled({ timeout: 30_000 });
		await toggle.click();
	}
	if (enabled) await expect(input).toBeChecked();
	else await expect(input).not.toBeChecked();
}
