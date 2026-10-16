import {expect, test} from '../helpers/cookie-audit';
import {waitForComponentPreview} from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
test('Team @ suggestion fits phone width and selects the exact token with the keyboard', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await page.addInitScript(() => window.addEventListener('preview-mention-selected', event => {
    (window as unknown as {selectedMention: unknown}).selectedMention = (event as CustomEvent).detail;
  }));
  await page.goto('/dev/preview/enter_message/MentionDropdown?chrome=0&theme=light&background=%23dbeafe&width=350&variant=team');
  await waitForComponentPreview(page);
  const dropdown = page.getByTestId('mention-dropdown');
  const row = page.getByRole('option', {name: /OpenMates/});
  await expect(row).toBeVisible();
  await expect(row.locator('.result-subtitle')).toHaveText('Ask OpenMates to help');
  await expect(row.locator('.icon_ai')).toBeVisible();
  const box = await dropdown.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  await dropdown.focus();
  await page.keyboard.press('Enter');
  await expect.poll(() => page.evaluate(() => (window as unknown as {selectedMention?: {mentionSyntax: string}}).selectedMention?.mentionSyntax)).toBe('@openmates');
});

// contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
test('Team OpenMates search result is clickable at laptop width', async ({page}) => {
  await page.setViewportSize({width: 1280, height: 800});
  await page.addInitScript(() => window.addEventListener('preview-mention-selected', event => {
    (window as unknown as {selectedMention: unknown}).selectedMention = (event as CustomEvent).detail;
  }));
  await page.goto('/dev/preview/enter_message/MentionDropdown?chrome=0&theme=light&background=%23dbeafe&width=600&variant=teamSearch');
  await waitForComponentPreview(page);
  const row = page.getByRole('option', {name: /OpenMates/});
  await expect(row).toBeVisible();
  await row.hover();
  await expect(row.locator('.row-settings-button')).toBeVisible();
  await row.click();
  await expect.poll(() => page.evaluate(() => (window as unknown as {selectedMention?: {mentionSyntax: string}}).selectedMention?.mentionSyntax)).toBe('@openmates');
});

// contract-test: supporting surface=gui.web assertions=teams.chat.sender-identity-layout
test('OpenMates suggestion settings button opens the Mates settings root', async ({page}) => {
  await page.setViewportSize({width: 1280, height: 800});
  await page.addInitScript(() => window.addEventListener('preview-mention-settings', event => {
    (window as unknown as {mentionSettingsPath: unknown}).mentionSettingsPath = (event as CustomEvent).detail;
  }));
  await page.goto('/dev/preview/enter_message/MentionDropdown?chrome=0&theme=light&background=%23dbeafe&width=600&variant=team');
  await waitForComponentPreview(page);
  const row = page.getByRole('option', {name: /OpenMates/});
  await row.hover();
  await row.getByRole('button', {name: /settings/i}).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as {mentionSettingsPath?: string}).mentionSettingsPath)).toBe('mates');
});
