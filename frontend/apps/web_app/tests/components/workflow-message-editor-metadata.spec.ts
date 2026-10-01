// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};
import type { Page } from '@playwright/test';
const { expect, test } = require('../helpers/cookie-audit');

for (const [width, theme] of [[390, 'dark'], [1024, 'light']] as const) {
  // contract-test: direct surface=gui.web assertions=workflows-ui.editor.inline-action-variables,workflows-ui.responsive-accessible-reachable
  test(`late output schemas hydrate a saved pill without losing the draft, caret or undo at ${width}px`, async ({ page }: { page: Page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(`/dev/preview/workflows/WorkflowMessageEditorMetadataFixture?${new URLSearchParams({ theme, width: String(width), background: theme === 'dark' ? '#171717' : '#dbeafe', chrome: '0' })}`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true', { timeout: 30_000 });
    const fixture = page.getByTestId('workflow-editor-metadata-fixture');
    const input = page.getByTestId('workflow-message-template');
    const pill = input.locator('[data-mention-type="workflow_output"]');
    await expect(pill).toHaveText('@Events · Results');
    await input.evaluate((element: HTMLElement) => { element.dataset.previewIdentity = 'original'; });
    await input.click();
    await input.press('ControlOrMeta+End');
    await page.keyboard.insertText(' Note.');
    await expect(fixture).toHaveAttribute('data-template', 'Summarize: {{steps.events.results}} Note.');
    const changes = await fixture.getAttribute('data-change-count');
    const caret = await page.evaluate(() => ({ text: window.getSelection()?.anchorNode?.textContent, offset: window.getSelection()?.anchorOffset }));
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('workflow-preview-output-metadata', { detail: [
      { reference: '$nodes.events.output.results', nodeId: 'events', appId: 'events', skillId: 'search', label: 'Events · Results', schema: { type: 'array' } },
    ] })));
    await expect(pill).toHaveText('@events.search.results');
    await expect(pill).toHaveAttribute('title', 'Events · Results');
    await expect(pill.locator('.workflow-mention-icon')).toBeVisible();
    await expect(input).toHaveAttribute('data-preview-identity', 'original');
    await expect(input).toBeFocused();
    await expect(fixture).toHaveAttribute('data-change-count', changes!);
    await expect(fixture).toHaveAttribute('data-template', 'Summarize: {{steps.events.results}} Note.');
    expect(await page.evaluate(() => ({ text: window.getSelection()?.anchorNode?.textContent, offset: window.getSelection()?.anchorOffset }))).toEqual(caret);
    await fixture.screenshot({ path: test.info().outputPath(`workflow-pill-metadata-${width}-${theme}.png`) });
    await input.press('ControlOrMeta+z');
    await expect(fixture).toHaveAttribute('data-template', 'Summarize: {{steps.events.results}}');
    await expect(pill).toHaveText('@events.search.results');
    await input.press('ControlOrMeta+Shift+z');
    await expect(fixture).toHaveAttribute('data-template', 'Summarize: {{steps.events.results}} Note.');
  });
}
