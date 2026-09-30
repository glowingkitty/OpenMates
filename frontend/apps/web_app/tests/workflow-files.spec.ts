/* eslint-disable @typescript-eslint/no-require-imports -- Existing browser test helpers expose CommonJS exports. */
export {};
import type { Page, Response } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { stringify } = require('yaml');

function apiUrl(): string {
  const url = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
  return url.hostname === 'localhost' ? 'http://localhost:8000' : `${url.protocol}//${url.hostname.replace(/^app\./, 'api.')}`;
}

function portableWorkflow(title: string) {
  return {
    format: 'openmates-workflow', format_version: 1,
    workflow: {
      title, description: 'A portable daily report', run_content_retention: 'last_5',
      graph: {
        version: 2, trigger_node_id: 'step_1',
        nodes: [
          { id: 'step_1', type: 'schedule_trigger', config: { schedule: { type: 'daily', time: '09:00', timezone: 'Europe/Berlin' } } },
          { id: 'step_2', type: 'send_chat_message', config: { title: 'Imported daily report', message: 'A static daily report', destination_required: true } },
        ],
        edges: [{ from: 'step_1', to: 'step_2' }],
      },
    },
    binding_requirements: [{ type: 'schedule', node_id: 'step_1' }, { type: 'chat_destination', node_id: 'step_2' }],
  };
}

test.describe('Portable Workflow files', () => {
  test.describe.configure({ timeout: 120000 });

  test.beforeEach(async ({ page }: { page: Page }) => {
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, () => {}, async () => {});
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.files.more-export,workflows.portability.definition-roundtrip,workflows.portability.private-content-boundary
  test('exports the saved blank definition from More as a Workflow YAML file', async ({ page }: { page: Page }) => {
    const title = `Portable blank ${Date.now()}`;
    const created = await page.request.post(`${apiUrl()}/v1/workflows`, {
      data: { title, graph: { version: 2, trigger_node_id: null, nodes: [], edges: [] }, enabled: false },
    });
    expect(created.ok()).toBe(true);
    const { workflow } = await created.json();
    try {
      await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
      await page.getByTestId('workflow-landing-card').filter({ hasText: title }).first().click();
      await expect(page.getByTestId('workspace-detail-title')).toHaveText(title);
      await page.getByTestId('workflow-detail-actions').getByRole('button', { name: 'More', exact: true }).click();
      const downloadPromise = page.waitForEvent('download');
      await page.getByTestId('workflow-export').click();
      const download = await downloadPromise;
      expect(download.suggestedFilename()).toMatch(/\.workflow\.yml$/);
      const stream = require('node:fs').readFileSync(await download.path(), 'utf8');
      const parsed = require('yaml').parse(stream);
      expect(parsed.format).toBe('openmates-workflow');
      expect(parsed.workflow.title).toBe(title);
      expect(parsed.workflow.graph.nodes).toEqual([]);
      expect(stream).not.toContain(workflow.id);
      expect(stream).not.toContain(workflow.current_version_id);
    } finally {
      await page.request.delete(`${apiUrl()}/v1/workflows/${workflow.id}`);
    }
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.files.composer-drop-import,workflows.portability.disabled-validated-import
  test('composer file button opens the picker, rejects other extensions and imports a Workflow YAML', async ({ page }: { page: Page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
    const composer = page.getByTestId('workflow-input-composer');
    const input = page.getByTestId('workflow-input-textarea');
    const button = composer.getByTestId('workflow-import-button');
    await expect(input).toHaveAttribute('placeholder', 'Describe new workflow.');
    await expect(page.getByTestId('workflow-import-button')).toHaveCount(1);
    await expect(button).toHaveAccessibleName('Import .workflow.yml');
    await expect(page.getByTestId('workflow-import-input')).toHaveAttribute('accept', '.workflow.yml');
    await input.fill('Keep this unsent workflow description');
    const chooserPromise = page.waitForEvent('filechooser');
    await button.click();
    const chooser = await chooserPromise;
    expect(chooser.isMultiple()).toBe(false);
    const title = `Picked portable ${Date.now()}`;
    const content = Buffer.from(stringify(portableWorkflow(title)));
    let importRequests = 0;
    page.on('request', (request) => {
      if (request.url().endsWith('/v1/workflows/file-import') && request.method() === 'POST') importRequests += 1;
    });
    await chooser.setFiles({ name: 'portable.yaml', mimeType: 'application/yaml', buffer: content });
    await expect(page.getByTestId('workflows-error')).toContainText('Choose an OpenMates .workflow.yml file.');
    await expect(input).toHaveValue('Keep this unsent workflow description');
    expect(importRequests).toBe(0);
    const imported = page.waitForResponse((response: Response) => response.url().endsWith('/v1/workflows/file-import') && response.request().method() === 'POST');
    const nextChooserPromise = page.waitForEvent('filechooser');
    await button.click();
    await (await nextChooserPromise).setFiles({ name: 'portable.workflow.yml', mimeType: 'application/yaml', buffer: content });
    const response = await imported;
    expect(response.ok()).toBe(true);
    const { workflow } = await response.json();
    try {
      await expect(page.getByTestId('workspace-detail-title')).toHaveText(title);
      await expect(page.getByTestId('workflow-enabled-state')).toHaveAttribute('data-enabled', 'false');
      await expect(page.getByTestId('workflow-binding-item')).toHaveCount(2);
    } finally {
      await page.request.delete(`${apiUrl()}/v1/workflows/${workflow.id}`);
    }
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.files.composer-drop-import,workflows.portability.disabled-validated-import
  test('dropping a Workflow YAML opens disabled Template with persisted binding review and preserves typed text on failed import', async ({ page }: { page: Page }) => {
    await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
    await page.getByTestId('workflow-input-textarea').fill('Keep this unsent title');
    await page.getByTestId('workflow-import-dropzone').dispatchEvent('drop', { dataTransfer: await page.evaluateHandle(() => {
      const transfer = new DataTransfer();
      transfer.items.add(new File(['format: openmates-workflow\nformat_version: 900\n'], 'bad.workflow.yml', { type: 'application/yaml' }));
      return transfer;
    }) });
    await expect(page.getByTestId('workflows-error')).toContainText('not supported');
    await expect(page.getByTestId('workflow-input-textarea')).toHaveValue('Keep this unsent title');
    const title = `Dropped portable ${Date.now()}`;
    const document = portableWorkflow(title);
    const responsePromise = page.waitForResponse((response: Response) => response.url().endsWith('/v1/workflows/file-import') && response.request().method() === 'POST');
    const transfer = await page.evaluateHandle(({ filename, content }) => {
      const data = new DataTransfer();
      data.items.add(new File([content], filename, { type: 'application/yaml' }));
      return data;
    }, { filename: `${title}.workflow.yml`, content: stringify(document) });
    await page.getByTestId('workflow-import-dropzone').dispatchEvent('dragover', { dataTransfer: transfer });
    await expect(page.getByTestId('workflow-import-dropzone')).toHaveClass(/dragging/);
    await page.getByTestId('workflow-import-dropzone').dispatchEvent('drop', { dataTransfer: transfer });
    const response = await responsePromise;
    expect(response.ok()).toBe(true);
    const { workflow } = await response.json();
    try {
      await expect(page.getByTestId('workspace-detail-title')).toHaveText(title);
      await expect(page.getByTestId('workflow-tab-template')).toHaveAttribute('aria-selected', 'true');
      await expect(page.getByTestId('workflow-enabled-state')).toHaveAttribute('data-enabled', 'false');
      await expect(page.getByTestId('workflow-binding-item')).toHaveCount(2);
      await expect(page.getByTestId('toggle-workflow')).toBeDisabled();
      await page.reload({ waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('workflow-binding-item')).toHaveCount(2);
      await expect(page.getByTestId('toggle-workflow')).toBeDisabled();
      const confirmation = page.waitForResponse((result: Response) => result.url().endsWith(`/v1/workflows/${workflow.id}/binding-requirements/complete`) && result.request().method() === 'POST');
      await page.getByTestId('workflow-binding-item').first().getByTestId('workflow-binding-confirm').click();
      expect((await confirmation).ok()).toBe(true);
      await expect(page.getByTestId('workflow-binding-item').first()).toContainText('Confirmed');
      await expect(page.getByTestId('toggle-workflow')).toBeDisabled();
    } finally {
      await page.request.delete(`${apiUrl()}/v1/workflows/${workflow.id}`);
    }
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.files.project-upload-import,workflows.portability.disabled-validated-import
  test('Project upload imports a marked YAML and links the new Workflow to its Project', async ({ page }: { page: Page }) => {
    await skipIfFeaturesDisabled(test, page, ['platform:projects']);
    await page.goto(getE2EDebugUrl('/projects'), { waitUntil: 'domcontentloaded' });
    const projectName = `Portable project ${Date.now()}`;
    const createdProject = page.waitForResponse((response: Response) => response.url().endsWith('/v1/projects') && response.request().method() === 'POST');
    await page.getByTestId('project-input-textarea').fill(projectName);
    await page.getByTestId('project-input-submit').click();
    await page.getByTestId('project-write-policy-apply-and-show').check();
    await page.getByTestId('project-write-policy-confirm').click();
    const projectResponse = await createdProject;
    expect(projectResponse.ok()).toBe(true);
    const projectId = (await projectResponse.json()).project.project_id;
    let workflowId: string | null = null;
    try {
      await page.getByTestId('project-tab-folders').click();
      const title = `Project imported ${Date.now()}`;
      const imported = page.waitForResponse((response: Response) => response.url().endsWith('/v1/workflows/file-import') && response.request().method() === 'POST');
      await page.locator('input[type=file]').setInputFiles({ name: 'portable.yaml', mimeType: 'application/yaml', buffer: Buffer.from(stringify(portableWorkflow(title))) });
      const response = await imported;
      expect(response.ok()).toBe(true);
      workflowId = (await response.json()).workflow.id;
      await expect(page.getByTestId('project-browser-list')).toContainText(title);
      await expect(page.getByTestId('project-workflow-item').filter({ hasText: title })).toHaveAttribute('href', `/#workflow-id=${encodeURIComponent(workflowId!)}&workflow-tab=details`);
      await page.locator('input[type=file]').setInputFiles({ name: 'bad.workflow.yml', mimeType: 'application/yaml', buffer: Buffer.from('format: openmates-workflow\nformat_version: 900\n') });
      await expect(page.getByText(/not supported/i).first()).toBeVisible();
      await page.locator('input[type=file]').setInputFiles({ name: 'malformed.yaml', mimeType: 'application/yaml', buffer: Buffer.from('format: openmates-workflow\nworkflow: [\n') });
      await expect(page.getByText(/Invalid workflow YAML/i).first()).toBeVisible();
    } finally {
      if (workflowId) await page.request.delete(`${apiUrl()}/v1/workflows/${workflowId}`);
      await page.request.delete(`${apiUrl()}/v1/projects/${projectId}`);
    }
  });
});
