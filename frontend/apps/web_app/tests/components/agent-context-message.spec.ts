import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/AgentContextMessage?chrome=0&theme=light&background=%23dbeafe';

// contract-test: supporting surface=gui.web assertions=app-memories.transparency.loaded-set,app-memories.definition.context-documents
test('counts whole guides and expands exact bodies with keyboard on mobile', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${PREVIEW}&width=350`);
  await waitForComponentPreview(page);
  const card = page.getByTestId('agent-context-message');
  const details = page.getByTestId('loaded-memories-details');
  await expect(details.locator('summary')).toHaveText('Loaded 2 memories.');
  await expect(page.getByTestId('applied-memory-body').first()).toBeHidden();
  await details.locator('summary').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('applied-memory')).toHaveCount(2);
  await expect(page.getByTestId('applied-memory-body').first()).toHaveText('- Preserve task cancellation.\n- Release resources with context managers.');
  await expect(page.getByTestId('applied-rule-revision').first()).toContainText('b'.repeat(64));
  await expect(card).toContainText('App-provided');
  await expect(card).toContainText('Project');
  await expect(card).not.toContainText('[T:');
  expect(await card.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await testInfo.attach('loaded-rule-guides-mobile', { body: await card.screenshot(), contentType: 'image/png' });
  await details.locator('summary').click();
  await expect(page.getByTestId('applied-memory-body').first()).toBeHidden();
});

// contract-test: supporting surface=gui.web assertions=chats.direction.reviewed-correction
test('shows the truthful sent notice and exact delivered correction only on expansion', async ({ page }, testInfo) => {
  await page.goto(`${PREVIEW}&variant=correction&width=700`);
  await waitForComponentPreview(page);
  const details = page.getByTestId('direction-correction-details');
  await expect(details.locator('summary')).toHaveText('Chat is drifting too far away from the goals. Correction instruction was sent.');
  await expect(page.getByTestId('direction-correction-instruction')).toBeHidden();
  await details.locator('summary').click();
  await expect(page.getByTestId('direction-correction-instruction')).toHaveText('Return to the approved signup accessibility fix. Keep the related screen-reader discovery; leave the unrelated dashboard redesign for a separate task.');
  await testInfo.attach('delivered-correction-expanded', { body: await details.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=focus-modes.project-authoring-click,workflows.project.update-authoring
test('starts authoring only after a click and prevents repeated submissions', async ({ page }) => {
  await page.addInitScript(() => {
    window.addEventListener('agent-context-preview-authoring', (event) => {
      const root = document.documentElement;
      root.dataset.authoringCalls = String(Number(root.dataset.authoringCalls ?? 0) + 1);
      root.dataset.authoringRecommendation = (event as CustomEvent<{ recommendation_id: string }>).detail.recommendation_id;
    });
  });
  await page.goto(`${PREVIEW}&variant=recommendations&width=350`);
  await waitForComponentPreview(page);
  await expect(page.locator('html')).not.toHaveAttribute('data-authoring-calls');
  const button = page.getByTestId('project-authoring-action').first();
  await button.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('html')).toHaveAttribute('data-authoring-calls', '1');
  await expect(page.locator('html')).toHaveAttribute('data-authoring-recommendation', 'preview-create');
  await expect(button).toBeDisabled();
  await expect(button).toHaveText('Started');
  await expect(page.getByTestId('project-authoring-action').last()).toHaveText('Update Workflow');
});

// contract-test: supporting surface=gui.web assertions=focus-modes.project-authoring-click
test('keeps failed authoring actionable and reports failure without claiming a job started', async ({ page }) => {
  await page.goto(`${PREVIEW}&variant=error&width=350`);
  await waitForComponentPreview(page);
  await page.getByTestId('project-authoring-action').click();
  await expect(page.getByRole('alert')).toHaveText('Could not start this update. Please try again.');
  await expect(page.getByTestId('project-authoring-action')).toBeEnabled();
});

// contract-test: supporting surface=gui.web assertions=focus-modes.project-authoring-persistence,projects.focus.default-owned
test('shows the authored draft and saves only after its explicit review button', async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    window.addEventListener('agent-context-preview-save', (event) => {
      document.documentElement.dataset.savedJob = (event as CustomEvent<string>).detail;
    });
  });
  await page.goto(`${PREVIEW}&variant=draft&width=350`);
  await waitForComponentPreview(page);
  await expect(page.locator('html')).not.toHaveAttribute('data-saved-job');
  await expect(page.getByTestId('project-authoring-job')).toContainText('Draft ready for review and saving.');
  const draft = page.getByTestId('project-authoring-draft');
  await draft.locator('summary').click();
  await expect(draft.locator('pre')).toContainText('Keep the approved goal and investigate its failing dependency first.');
  await testInfo.attach('authoring-draft-review', { body: await page.getByTestId('agent-context-message').screenshot(), contentType: 'image/png' });
  await page.getByTestId('project-authoring-save').click();
  await expect(page.locator('html')).toHaveAttribute('data-saved-job', 'preview-job');
  await expect(page.getByTestId('project-authoring-save')).toBeDisabled();
});

// contract-test: supporting surface=gui.web assertions=focus-modes.project-authoring-click
test('shows the exact clarification question without starting more work', async ({ page }) => {
  await page.goto(`${PREVIEW}&variant=clarification&width=350`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('project-authoring-question')).toHaveText('Which repository should this Focus cover?');
  await expect(page.getByTestId('project-authoring-save')).toHaveCount(0);
  await expect(page.locator('html')).not.toHaveAttribute('data-authoring-calls');
});

// contract-test: supporting surface=gui.web assertions=app-memories.compatibility.legacy-documents
test('renders historical Rule receipts as Memories without rewriting their contents', async ({ page }) => {
  await page.goto(`${PREVIEW}&variant=legacy&width=350`);
  await waitForComponentPreview(page);
  const details = page.getByTestId('loaded-rules-details');
  await expect(details.locator('summary')).toHaveText('Loaded 2 memories.');
  await details.locator('summary').click();
  await expect(page.getByTestId('applied-rule-body').first()).toHaveText('- Preserve task cancellation.\n- Release resources with context managers.');
});
