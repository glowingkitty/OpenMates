// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

for (const width of [390, 820]) {
  // contract-test: direct surface=gui.web assertions=teams.chat.sender-identity-layout
  test(`Team human and assistant messages show distinct senders at ${width}px`, async ({ page }) => {
    test.setTimeout(60_000); // Cold local preview compilation may outlast Playwright's default 30s.
    await page.setViewportSize({ width: Math.max(1280, width + 80), height: 900 });
    const positions: Record<string, { left: number; right: number }> = {};
    for (const variant of ['teamOwnHuman', 'teamRemoteHuman', 'teamRemoteWithAvatar', 'teamAssistant']) {
      const params = new URLSearchParams({ chrome: '0', width: String(width), variant,
        props: JSON.stringify({ containerWidth: width }) });
      await page.goto(`/dev/preview/ChatMessage?${params}`);
      const canvas = await waitForComponentPreview(page);
      const message = canvas.locator('.chat-message');
      const lane = message.locator('[class*="message-align-"]');
      const bounds = await lane.boundingBox();
      expect(bounds).not.toBeNull();
      positions[variant] = { left: bounds!.x, right: bounds!.x + bounds!.width };
      if (variant === 'teamOwnHuman') {
        await expect(lane).toHaveClass(/message-align-right/);
        const viewportBounds = await canvas.getByTestId('component-preview-viewport').boundingBox();
        expect(viewportBounds).not.toBeNull();
        expect(bounds!.x + bounds!.width).toBeGreaterThanOrEqual(
          viewportBounds!.x + viewportBounds!.width - 24
        );
        await expect(message.getByTestId('user-message-content')).toContainText('Alexanderplatz');
        await expect(message.getByTestId('remote-human-name')).toHaveCount(0);
      } else if (variant === 'teamRemoteHuman' || variant === 'teamRemoteWithAvatar') {
        await expect(lane).toHaveClass(/message-align-left/);
        await expect(message.getByTestId('remote-human-name')).toHaveText('Sam');
        await expect(message.getByTestId('remote-human-profile')).toHaveAttribute('aria-label', 'Sam');
        const profileBounds = await message.getByTestId('remote-human-profile').boundingBox();
        expect(profileBounds).not.toBeNull();
        expect(profileBounds!.x + profileBounds!.width).toBeLessThan(bounds!.x);
        await expect(message.getByTestId('mate-message-content')).toContainText(
          variant === 'teamRemoteHuman' ? 'Berlin volunteers' : 'profile image'
        );
        await expect(message.getByTestId('mate-profile')).toHaveCount(0);
        await expect(message.getByTestId('chat-mate-name')).toHaveCount(0);
        if (variant === 'teamRemoteWithAvatar') {
          await expect(message.getByTestId('remote-human-avatar-image')).toBeVisible();
        } else {
          await expect(message.getByTestId('remote-human-avatar-image')).toHaveCount(0);
          await expect(message.getByTestId('remote-human-profile')).toContainText('S');
        }
      } else {
        await expect(message.getByTestId('chat-mate-name')).toHaveText('Sophia');
        await expect(message.getByTestId('mate-profile')).toBeVisible();
        await expect(message.getByTestId('remote-human-name')).toHaveCount(0);
      }
    }
    expect(positions.teamAssistant.left).toBeLessThan(positions.teamOwnHuman.left);
  });
}
