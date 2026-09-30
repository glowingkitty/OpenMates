// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

import type { Page } from '@playwright/test';

const { expect, test } = require('../helpers/cookie-audit');

function preview(variant: string): string {
  return `/dev/preview/workflows/WorkflowGraphRenderer?${new URLSearchParams({
    variant, theme: 'light', background: '#dbeafe', width: '900', chrome: '0',
  })}`;
}

async function openNewAskAi(page: Page, variant: string): Promise<void> {
  await page.goto(preview(variant), { waitUntil: 'networkidle' });
  await page.getByTestId('workflow-add-step').last().click();
  await page.getByTestId('workflow-step-ask-ai').click();
  await expect(page.getByTestId('workflow-ask-ai-input')).toBeVisible();
}

test.describe('Workflow Ask AI editor', () => {
  test.beforeEach(async ({ page }: { page: Page }) => {
    await page.route('**/v1/workflows/ai-authoring/hints', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ verdict: 'allowed', suggested_references: ['$nodes.events.output.results'] }),
    }));
  });
  // contract-test: direct surface=gui.web assertions=workflows-ui.mvp.ask-ai,workflows.composition.earlier-action-reference
  test('selects a source before its fields and replaces a highlighted @ query with one variable', async ({ page }: { page: Page }) => {
    await openNewAskAi(page, 'eventsSearch');
    const source = page.getByTestId('workflow-variable-sources').locator('[data-source-node-id="events"]');
    const fields = page.getByTestId('workflow-ai-suggestions');
    const editor = page.getByTestId('workflow-message-template');

    await expect(source).toBeVisible();
    await expect(fields).toHaveCount(0);
    await source.click();
    await expect(fields.locator('[data-variable-reference="$nodes.events.output.results"]')).toBeVisible();
    await fields.getByRole('button', { name: /Show all/i }).click();
    await expect(fields.locator('[data-variable-reference^="$nodes.events.output.results."]')).toHaveCount(0);

    await editor.fill('Keep this lead @events.search.res');
    await expect(editor.locator('.workflow-mention-query')).toHaveText('@events.search.res');
    await expect(source).toBeVisible();
    await fields.locator('[data-variable-reference="$nodes.events.output.results"]').click();
    await expect(editor).toHaveText('Keep this lead @events.search.results');
    await expect(editor.locator('.generic-mention')).toHaveCount(1);
    await expect(editor.locator('.generic-mention-label')).toHaveText('@events.search.results');
    await expect(editor.locator('.workflow-mention-icon')).toBeVisible();
    expect(await editor.locator('.workflow-mention-icon').evaluate(element => (element as HTMLElement).style.getPropertyValue('--workflow-mention-icon'))).toContain('--icon-url-event');
    const sourceMask = await source.locator('.source-icon').evaluate(element => getComputedStyle(element).maskImage);
    expect(await editor.locator('.workflow-mention-icon').evaluate(element => getComputedStyle(element).maskImage)).toBe(sourceMask);
    await expect(page.getByTestId('workflow-node-save')).toBeEnabled();
    await page.getByTestId('workflow-node-expanded').screenshot({ animations:'disabled', path: test.info().outputPath('ask-ai-selected-source.png') });
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.mvp.ask-ai,chats.streaming.progressive-presentation
  test('keeps the chat model selection and renders cumulative test SSE as a chat answer', async ({ page }: { page: Page }) => {
    await page.addInitScript(() => {
      type TestWindow = Window & {
        __workflowAskTestRequest?: Record<string, unknown>;
        __workflowAskSend?: (event: Record<string, unknown>) => void;
      };
      const testWindow = window as TestWindow;
      const originalFetch = window.fetch.bind(window);
      window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
        if (!/\/v1\/workflows\/preview-workflow\/steps\/ask\/test(?:\?|$)/.test(url)) return originalFetch(input, init);
        testWindow.__workflowAskTestRequest = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
        const encoder = new TextEncoder();
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            testWindow.__workflowAskSend = (event) => {
              controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
              if (event.type === 'completed' || event.type === 'error') controller.close();
            };
            testWindow.__workflowAskSend({ type: 'processing', run_id: 'ask-test-run' });
          },
        });
        return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
      };
    });

    await page.goto(preview('askAiTestable'), { waitUntil: 'networkidle' });
    const ask = page.locator('[data-node-id="ask"]');
    await ask.getByTestId('workflow-node-summary').click();
    const model = ask.getByTestId('workflow-ask-ai-model');
    const input = ask.getByTestId('workflow-ask-ai-input');
    const modelTrigger = model.getByTestId('composer-model-selector');
    const [inputBox, modelBox] = await Promise.all([input.boundingBox(), model.boundingBox()]);
    expect(inputBox && modelBox && Math.abs(modelBox.x - inputBox.x) <= 1
      && modelBox.y >= inputBox.y + inputBox.height).toBe(true);
    await expect(ask.getByRole('button', { name:'Next step', exact:true }).locator('span')).toBeVisible();
    await expect(modelTrigger).toContainText(/Auto/i);
    await modelTrigger.click();
    const menuBox = await model.getByTestId('composer-model-selector-menu').boundingBox();
    expect(menuBox && menuBox.x >= 0 && menuBox.x + menuBox.width <= page.viewportSize()!.width).toBe(true);
    await model.getByTestId('composer-model-provider-openai').click();
    await model.getByTestId('composer-model-row').filter({ hasText: 'GPT-6.1 Sol' }).getByTestId('composer-model-toggle').click();
    await expect(modelTrigger).toContainText('GPT-6.1 Sol');

    await ask.getByTestId('workflow-test-action').click();
    await expect(ask.getByTestId('workflow-ask-ai-processing')).toBeVisible();
    await expect.poll(() => page.evaluate(() => {
      const body = (window as Window & { __workflowAskTestRequest?: { node?: { config?: { input?: { model?: string } } } } }).__workflowAskTestRequest;
      return body?.node?.config?.input?.model;
    })).toBe('openai/gpt-6.1-sol');
    const send = (event: Record<string, unknown>) => page.evaluate((payload) => {
      (window as Window & { __workflowAskSend?: (value: Record<string, unknown>) => void }).__workflowAskSend?.(payload);
    }, event);
    await send({ type: 'chunk', content: '## Monday\n' });
    const answer = ask.getByTestId('workflow-ask-ai-test-body');
    await expect(answer.locator('h2')).toHaveText('Monday');
    await send({ type: 'chunk', content: '## Monday\n- Mild and clear' });
    await expect(answer.locator('li')).toHaveText('Mild and clear');
    await send({ type: 'completed', run: {
      id: 'ask-test-run', workflow_id: 'preview-workflow', version_id: 'preview-version',
      trigger_type: 'step_test', status: 'completed',
      node_runs: [{ node_id: 'ask', status: 'completed', output_summary: {
        answer: '**Monday:** Mild and clear. [Forecast](https://example.com/forecast).',
      } }],
    } });
    await expect(ask.getByTestId('workflow-ask-ai-processing')).toHaveCount(0);
    await expect(ask.getByTestId('workflow-ask-ai-test-sender')).toHaveText('OpenMates');
    await expect(answer.locator('strong')).toContainText('Monday:');
    await expect(answer.locator('a[href="https://example.com/forecast"]')).toHaveText('Forecast');
    await expect(answer).not.toContainText('## Monday');
    await ask.getByTestId('workflow-node-expanded').screenshot({ animations:'disabled', path: test.info().outputPath('ask-ai-stream-completed.png') });
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.mvp.ask-ai,workflows-ui.responsive-accessible-reachable
  test('keeps the picker and model menu reachable by keyboard on a phone', async ({ page }: { page: Page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(preview('askAiTestable'), { waitUntil: 'networkidle' });
    const ask = page.locator('[data-node-id="ask"]');
    await ask.getByTestId('workflow-node-summary').click();
    const sources = ask.getByTestId('workflow-variable-sources');
    const scroller = ask.getByTestId('workflow-variable-source-scroll');
    const sourceButtons = scroller.locator('[data-source-node-id]');
    const [firstSource, secondSource] = await Promise.all([sourceButtons.nth(0).boundingBox(), sourceButtons.nth(1).boundingBox()]);
    expect(Math.abs(firstSource!.y - secondSource!.y)).toBeLessThanOrEqual(1);
    expect(await scroller.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true);
    expect(await scroller.evaluate(element => getComputedStyle(element).maskImage)).toContain('linear-gradient');
    expect(await sourceButtons.first().evaluate(element => getComputedStyle(element).whiteSpace)).toBe('nowrap');
    expect(await sourceButtons.first().evaluate(element => getComputedStyle(element).textAlign)).toBe('left');
    const backlink = ask.getByRole('button', { name:'Next step', exact:true });
    await expect(backlink.locator('span')).toBeHidden();
    const [backBox, deleteBox] = await Promise.all([backlink.boundingBox(), ask.getByTestId('workflow-node-delete').boundingBox()]);
    expect(deleteBox!.x - backBox!.x).toBeLessThan(60);
    const events = sources.locator('[data-source-node-id="events"]');
    await events.focus();
    await page.keyboard.press('Enter');
    await expect(events).toHaveAttribute('aria-pressed', 'true');
    await expect(ask.getByTestId('workflow-ai-suggestions').locator('[data-variable-reference="$nodes.events.output.results"]')).toBeVisible();
    const model = ask.getByTestId('workflow-ask-ai-model');
    const [inputBox, modelBox] = await Promise.all([ask.getByTestId('workflow-ask-ai-input').boundingBox(), model.boundingBox()]);
    expect(modelBox!.y).toBeGreaterThanOrEqual(inputBox!.y + inputBox!.height);
    expect(Math.abs(modelBox!.x - inputBox!.x)).toBeLessThanOrEqual(1);
    await model.getByTestId('composer-model-selector').focus();
    await page.keyboard.press('ArrowDown');
    const menu = model.getByTestId('composer-model-selector-menu');
    await expect(menu).toBeVisible();
    const menuBox = await menu.boundingBox();
    expect(menuBox && menuBox.x >= 0 && menuBox.x + menuBox.width <= 390).toBe(true);
    await page.keyboard.press('Escape');
    await expect(menu).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    await ask.getByTestId('workflow-node-expanded').screenshot({ animations:'disabled', path: test.info().outputPath('ask-ai-phone.png') });
  });
});
