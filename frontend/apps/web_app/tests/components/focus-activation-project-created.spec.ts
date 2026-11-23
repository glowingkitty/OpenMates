/**
 * Component proof for an assistant-created Project: a chat-history system event
 * "Created <name> project · Undo" (Project name is a link), followed by the regular,
 * already-active focus mode activation embed (no extra rows, no Undo on the embed).
 */
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const EVENT = '/dev/preview/projects/ProjectCreatedEventNotice';
const EMBED = '/dev/preview/embeds/focus_mode/FocusModeActivationEmbed';

async function attachShot(testInfo: import('@playwright/test').TestInfo, name: string, locator: import('@playwright/test').Locator) {
    await testInfo.attach(name, { body: await locator.screenshot(), contentType: 'image/png' });
}

test.describe('Project created system event', () => {
    // contract-test: direct surface=gui.web assertions=projects.creation.assistant-inferred
    test('shows Created <name> project with the name as a link and an Undo text link', async ({ page }, testInfo) => {
        await page.goto(`${EVENT}?chrome=0&width=393`);
        await waitForComponentPreview(page);
        const row = page.getByTestId('project-created-event');
        await expect(row).toHaveAttribute('data-state', 'created');
        await expect(row).toContainText('Created Recipe Manager project');
        await expect(page.getByTestId('project-created-name')).toHaveText('Recipe Manager');
        await expect(page.getByTestId('project-created-undo')).toBeEnabled();
        expect((await row.getByRole('note').boundingBox())!.height).toBeLessThan(80);
        await attachShot(testInfo, 'project-created-event', row);
    });

    // contract-test: direct surface=gui.web assertions=projects.creation.assistant-inferred
    test('shows the undoing, undone and error states', async ({ page }, testInfo) => {
        await page.goto(`${EVENT}?chrome=0&width=393&variant=undoing`);
        await waitForComponentPreview(page);
        await expect(page.getByTestId('project-created-undo')).toBeDisabled();
        await attachShot(testInfo, 'project-created-event-undoing', page.getByTestId('project-created-event'));

        await page.goto(`${EVENT}?chrome=0&width=393&variant=undone`);
        await waitForComponentPreview(page);
        await expect(page.getByTestId('project-created-event')).toHaveAttribute('data-state', 'undone');
        await expect(page.getByTestId('project-created-status')).toHaveText('Project removed');
        await expect(page.getByTestId('project-created-undo')).toHaveCount(0);
        await attachShot(testInfo, 'project-created-event-undone', page.getByTestId('project-created-event'));

        await page.goto(`${EVENT}?chrome=0&width=393&variant=failed`);
        await waitForComponentPreview(page);
        await expect(page.getByTestId('project-created-undo-error')).toHaveText('Could not undo. Please try again.');
        await expect(page.getByTestId('project-created-undo')).toBeEnabled();
        await attachShot(testInfo, 'project-created-event-failed', page.getByTestId('project-created-event'));
    });

    // contract-test: supporting surface=gui.web assertions=projects.creation.assistant-inferred
    test('offers no Undo when the shell cannot run it', async ({ page }) => {
        await page.goto(`${EVENT}?chrome=0&variant=noUndo`);
        await waitForComponentPreview(page);
        await expect(page.getByTestId('project-created-name')).toBeVisible();
        await expect(page.getByTestId('project-created-undo')).toHaveCount(0);
    });
});

test.describe('Focus embed after a created Project', () => {
    // contract-test: direct surface=gui.web assertions=projects.focus.inferred-consent
    test('shows the regular activated focus embed with no created row and no Undo', async ({ page }, testInfo) => {
        await page.goto(`${EMBED}?chrome=0&variant=projectCreated`);
        await waitForComponentPreview(page);
        const bar = page.getByTestId('focus-mode-bar');
        await expect(bar).toBeVisible();
        await expect(bar).toHaveClass(/activated/);
        await expect(page.getByTestId('focus-status-value')).toHaveText('Focus activated');
        await expect(page.getByTestId('project-created-card')).toHaveCount(0);
        await expect(page.getByTestId('project-created-row')).toHaveCount(0);
        await expect(page.getByTestId('project-created-undo')).toHaveCount(0);
        await expect(page.getByTestId('focus-progress-bar')).toHaveCount(0);
        await expect(page.getByTestId('focus-reject-hint')).toHaveCount(0);
        await attachShot(testInfo, 'focus-activation-project-created', bar);
    });
});
