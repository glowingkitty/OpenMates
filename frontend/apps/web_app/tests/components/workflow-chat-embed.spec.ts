// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};
import type { Page, Route } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
const { expect, test } = require('../helpers/cookie-audit');

async function preview(page: Page): Promise<void> {
  await page.goto('/dev/preview/embeds/workflows/WorkflowEmbedFullscreen?variant=snapshot&theme=light&width=900&chrome=0', { waitUntil:'domcontentloaded' });
  await waitForComponentPreview(page);
}

test.describe('Chat-owned workflow embed', () => {
  // contract-test: direct surface=gui.web assertions=workflows-ui.chat-owned,workflows.chat.embedded-lifecycle
  test('keeps the readable graph snapshot when live detail is unavailable', async ({ page }: { page: Page }) => {
    await page.route('**/v1/workflows/workflow-chat-preview', async (route: Route) => route.fulfill({ status:503, json:{ detail:'Unavailable' } }));
    await preview(page);
    await expect(page.getByTestId('workflow-chat-graph')).toBeVisible();
    await expect(page.locator('[data-branch="option:outdoors"]')).toContainText('Go outdoors');
    await expect(page.locator('[data-branch="option:indoors"]')).toContainText('Stay indoors');
    await expect(page.locator('.snapshot-note')).toContainText('saved with this chat');
    await expect(page.getByTestId('workflow-chat-save-reusable')).toBeDisabled();
    await expect(page.getByTestId('workflow-chat-open')).toHaveAttribute('href', /workflow-id=workflow-chat-preview/);
    await expect(page.getByTestId('workflow-chat-runs')).toHaveAttribute('href', /workflow-tab=runs/);
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.chat-owned,workflows.chat.embedded-lifecycle
  test('saves a fresh disabled reusable copy through the owner-scoped endpoint', async ({ page }: { page: Page }) => {
    let posted: Record<string, unknown> | undefined;
    await page.route('**/v1/workflows/workflow-chat-preview', async (route: Route) => route.fulfill({ json:{ workflow:{
      id:'workflow-chat-preview', title:'Today’s activities', description:'A one-time workflow saved with this chat.',
      lifecycle:'chat_embed', enabled:false, graph:{ version:2, trigger_node_id:'start', nodes:[{ id:'start', type:'manual_trigger', config:{} }], edges:[] },
    } } }));
    await page.route('**/v1/workflows/workflow-chat-preview/save-as-reusable', async (route: Route) => {
      posted = route.request().postDataJSON();
      await route.fulfill({ json:{ workflow:{ id:'workflow-copy-preview', title:'Today’s activities', lifecycle:'persisted', enabled:false,
        graph:{ version:2, trigger_node_id:'start', nodes:[{ id:'start', type:'manual_trigger', config:{} }], edges:[] } } } });
    });
    await preview(page);
    const save = page.getByTestId('workflow-chat-save-reusable');
    await expect(save).toBeEnabled();
    await save.click();
    await expect(page.getByTestId('workflow-chat-saved-copy')).toHaveAttribute('href', /workflow-id=workflow-copy-preview/);
    expect(posted?.idempotency_key).toMatch(/^[0-9a-f-]{36}$/);
  });
});
