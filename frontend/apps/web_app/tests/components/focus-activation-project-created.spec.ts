/**
 * Component proof for the assistant-created Project activation card.
 * Two separate rows: creation (with Undo) and focus (activated, no countdown).
 * Undo uses the preview's injected handler; production wiring needs the core Worker binding.
 */
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const BASE = '/dev/preview/embeds/focus_mode/FocusModeActivationEmbed';

async function attachShot(testInfo: import('@playwright/test').TestInfo, name: string, locator: import('@playwright/test').Locator) {
    await testInfo.attach(name, { body: await locator.screenshot(), contentType: 'image/png' });
}

test.describe('Project created activation card', () => {
    // contract-test: direct surface=gui.web assertions=projects.focus.inferred-consent
    test('shows creation row with Undo, then the active focus row, and undoes', async ({ page }, testInfo) => {
        await page.goto(`${BASE}?chrome=0&variant=projectCreated`);
        await waitForComponentPreview(page);
        const card = page.getByTestId('project-created-card');
        await expect(card).toBeVisible();
        const created = page.getByTestId('project-created-row');
        const focus = page.getByTestId('project-focus-row');
        await expect(created).toContainText('Created project');
        await expect(page.getByTestId('project-created-name')).toHaveText('Garden notes');
        await expect(focus).toContainText('Work on');
        await expect(focus).toContainText('Garden notes');
        await expect(page.getByTestId('focus-status-value')).toHaveText('Focus activated');
        const [a, b] = await Promise.all([created.boundingBox(), focus.boundingBox()]);
        expect(a!.y + a!.height).toBeLessThanOrEqual(b!.y + 1);
        await expect(page.getByTestId('focus-progress-bar')).toHaveCount(0);
        await expect(page.getByTestId('focus-reject-hint')).toHaveCount(0);
        await expect(page.getByTestId('project-focus-grant-access')).toHaveCount(0);
        await expect(page.getByTestId('project-focus-decline-access')).toHaveCount(0);
        await attachShot(testInfo, 'focus-activation-project-created', card);

        await page.getByTestId('project-created-undo').click();
        await expect(page.getByTestId('project-created-status')).toHaveText('Project creation undone');
        await expect(page.getByTestId('project-created-undo')).toHaveCount(0);
        await expect(focus).toHaveAttribute('data-state', 'inactive');
        await expect(page.getByTestId('focus-status-value')).not.toHaveText('Focus activated');
        await attachShot(testInfo, 'focus-activation-project-created-undone', card);
    });

    // contract-test: direct surface=gui.web assertions=projects.focus.inferred-consent
    test('undone variant renders undone state on reload', async ({ page }) => {
        await page.goto(`${BASE}?chrome=0&variant=projectCreatedUndone`);
        await waitForComponentPreview(page);
        await expect(page.getByTestId('project-created-status')).toHaveText('Project creation undone');
        await expect(page.getByTestId('project-focus-row')).toHaveAttribute('data-state', 'inactive');
        await expect(page.getByTestId('project-created-undo')).toHaveCount(0);
    });

    // contract-test: supporting surface=gui.web assertions=projects.focus.inferred-consent
    test('fits a 393px phone width', async ({ page }, testInfo) => {
        await page.setViewportSize({ width: 393, height: 800 });
        await page.goto(`${BASE}?chrome=0&width=393&variant=projectCreated`);
        await waitForComponentPreview(page);
        const card = page.getByTestId('project-created-card');
        await expect(page.getByTestId('project-created-undo')).toBeVisible();
        await attachShot(testInfo, 'focus-activation-project-created-393', card);
    });
});
