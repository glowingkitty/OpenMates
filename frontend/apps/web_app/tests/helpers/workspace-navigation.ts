import { expect, type Page } from '@playwright/test';
import { waitForChatReady } from './chat-test-helpers';

/** The workflow home renders before auth restoration and feature loading finish. */
export async function waitForWorkflowWorkspaceReady(page: Page, timeout = 30_000): Promise<void> {
  const started = Date.now();
  const budget = () => Math.max(1_000, timeout - (Date.now() - started));
  const workspace = page.getByTestId('workflows-page');
  const composer = page.getByTestId('workflow-input-composer');
  try {
    await expect(workspace, 'Workflow authentication must settle before owner actions')
      .toHaveAttribute('data-authenticated', 'true', { timeout: budget() });
    // The composer is rendered only after auth and feature initialization settle.
    await expect(composer, 'The authenticated workflow workspace must be ready before creating a copy')
      .toBeVisible({ timeout: budget() });
  } catch (error) {
    const state = {
      authenticated: await workspace.getAttribute('data-authenticated').catch(() => null),
      composerVisible: await composer.isVisible().catch(() => false),
      featureDisabled: await page.getByTestId('workflows-feature-disabled').isVisible().catch(() => false),
    };
    throw new Error(`Workflow workspace not ready: ${JSON.stringify(state)}. Original: ${String(error)}`);
  }
}

/** Reopen a known chat after an app editor; the Chat tab links to the workspace root. */
export async function returnToChatWorkspace(page: Page, chatUrl: string): Promise<void> {
  await page.goto(chatUrl, { waitUntil: 'domcontentloaded' });
  await waitForChatReady(page);
  await expect(page, 'The existing chat must reopen before the wiki question').toHaveURL(chatUrl);
}

/** Reload an existing chat without waiting for unrelated iframe or asset load events. */
export async function reloadChatWorkspace(
  page: Page,
  chatUrl: string,
  logCheckpoint: (message: string) => void = () => {},
): Promise<void> {
  logCheckpoint('Chat workspace reload started.');
  await page.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 });
  logCheckpoint('Chat workspace DOM content loaded.');
  await waitForChatReady(page);
  logCheckpoint('Chat workspace ready after reload.');
  await expect.poll(() => page.url() === chatUrl, {
    message: 'The existing chat URL must be restored after reload',
  }).toBe(true);
  logCheckpoint('Existing chat URL verified after reload.');
}
