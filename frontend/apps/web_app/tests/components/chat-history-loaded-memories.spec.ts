import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: direct surface=gui.web assertions=app-memories.transparency.loaded-set,chat-processing-feedback.completed-processing-summary
test('attaches an identified memory receipt to its assistant activity and hides the receipt row', async ({ page }) => {
  await page.goto('/dev/preview/ChatHistory?variant=loadedMemoryAttached&theme=light&width=680&chrome=0');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('message-system')).toHaveCount(0);
  const assistant = page.getByTestId('message-assistant');
  await expect(assistant).toHaveCount(1);
  await assistant.getByTestId('assistant-activity-toggle').click();
  await expect(assistant.getByTestId('loaded-memory-pill')).toHaveText('Flowchart');
  await expect(assistant.getByTestId('applied-memory-body')).toBeHidden();
  await assistant.getByTestId('loaded-memory-pill').click();
  await expect(assistant.getByTestId('applied-memory-body')).toHaveText('- Make the direction of the flow clear.');
});

// contract-test: direct surface=gui.web assertions=app-memories.transparency.loaded-set
test('keeps an unmatched receipt visible as a memory activity group', async ({ page }) => {
  await page.goto('/dev/preview/ChatHistory?variant=loadedMemoryOrphan&theme=light&width=680&chrome=0');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('message-system')).toHaveCount(1);
  const receipt = page.getByTestId('message-system');
  await receipt.getByTestId('assistant-activity-toggle').click();
  await expect(receipt.getByTestId('loaded-memory-pill')).toHaveText('Flowchart');
});

// contract-test: direct surface=gui.web assertions=app-memories.transparency.loaded-set
test('shows the loaded memory on a pending assistant row', async ({ page }) => {
  await page.goto('/dev/preview/ChatHistory?variant=loadedMemoryPending&theme=light&width=680&chrome=0');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('message-system')).toHaveCount(0);
  const pending = page.getByTestId('pending-assistant-response');
  await expect(pending).toHaveCount(1);
  await expect(pending.getByTestId('assistant-activity-toggle')).toHaveAttribute('aria-expanded', 'true');
  await expect(pending.getByTestId('loaded-memory-pill')).toHaveText('Flowchart');
});

// contract-test: direct surface=gui.web assertions=app-memories.transparency.loaded-set
test('binds a late receipt to its identified later turn', async ({ page }) => {
  await page.goto('/dev/preview/ChatHistory?variant=loadedMemoryOtherTurn&theme=light&width=680&chrome=0');
  await waitForComponentPreview(page);
  const assistants = page.getByTestId('message-assistant');
  await expect(assistants).toHaveCount(2);
  await expect(assistants.first().getByTestId('assistant-activity-group')).toHaveCount(0);
  await assistants.last().getByTestId('assistant-activity-toggle').click();
  await expect(assistants.last().getByTestId('loaded-memory-pill')).toHaveText('Flowchart');
  await expect(page.getByTestId('message-system')).toHaveCount(0);
});
