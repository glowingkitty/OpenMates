// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

for (const width of [350, 740]) {
  // contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
  test(`Team AI reminder fits ${width}px and opens Mates settings`, async ({ page }) => {
    await page.setViewportSize({ width: width + 40, height: 844 });
    await page.goto(`/dev/preview/teams/TeamChatReminder?chrome=0&theme=light&background=%23dbeafe&width=${width}`);
    await waitForComponentPreview(page);
    const reminder = page.getByTestId('team-chat-ai-reminder');
    await expect(reminder).toContainText('Mention @openmates or a specific Mate');
    const link = reminder.getByRole('button', { name: '@openmates' });
    await expect(link).toHaveCSS('background-image', /linear-gradient/);
    const geometry = await reminder.evaluate(element => ({ width: element.clientWidth, scrollWidth: element.scrollWidth }));
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width + 1);
    await link.focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('html')).toHaveAttribute('data-team-reminder-settings-path', 'mates');
  });
}
