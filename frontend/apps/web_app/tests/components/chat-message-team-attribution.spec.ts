// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';

for (const width of [390, 820]) {
  // contract-test: direct surface=gui.web assertions=teams.chat.sender-identity-layout
  test(`Team human and assistant messages show distinct senders at ${width}px`, async ({ page }) => {
    test.setTimeout(60_000); // Cold local preview compilation may outlast Playwright's default 30s.
    await page.setViewportSize({ width: Math.max(1280, width + 80), height: 900 });
    const positions: Record<string, { left: number; right: number }> = {};
    const avatarMetrics: Record<string, { width: number; height: number; x: number; y: number; shadow: string }> = {};
    const nameStyles: Record<string, { backgroundImage: string; fontSize: string; fontWeight: string }> = {};
    for (const variant of ['teamOwnHuman', 'teamRemoteHuman', 'teamRemoteWithAvatar', 'teamAssistant']) {
      const params = new URLSearchParams({ chrome: '0', width: String(width), variant,
        props: JSON.stringify({ containerWidth: width }) });
      await page.goto(`/dev/preview/ChatMessage?${params}`);
      const canvas = await waitForComponentPreview(page);
      const message = canvas.locator('.chat-message');
      // ReadOnlyMessage parses asynchronously. Measure the completed message,
      // after its text and avatar motion settle, rather than its empty shell.
      const contentId = variant === 'teamOwnHuman' ? 'user-message-content' : 'mate-message-content';
      const contentText = variant === 'teamOwnHuman' ? 'Alexanderplatz'
        : variant === 'teamRemoteHuman' ? 'Berlin volunteers'
        : variant === 'teamRemoteWithAvatar' ? 'profile image' : 'Alex proposed checking';
      await expect(message.getByTestId(contentId)).toContainText(contentText);
      await page.mouse.move(0, 0);
      if (variant !== 'teamOwnHuman') {
        await waitForComponentMotion(message.getByTestId(
          variant === 'teamAssistant' ? 'mate-profile' : 'remote-human-profile'
        ));
      }
      const messageBounds = await message.boundingBox();
      expect(messageBounds).not.toBeNull();
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
        if (width > 500) expect(profileBounds!.x + profileBounds!.width).toBeLessThan(bounds!.x);
        else expect(profileBounds!.y + profileBounds!.height).toBeLessThan(bounds!.y);
        avatarMetrics[variant] = {
          width: profileBounds!.width, height: profileBounds!.height,
          x: profileBounds!.x - messageBounds!.x, y: profileBounds!.y - messageBounds!.y,
          shadow: await message.getByTestId('remote-human-profile').evaluate((element) => getComputedStyle(element).boxShadow),
        };
        expect(await message.getByTestId('remote-human-profile').evaluate((element) => getComputedStyle(element, '::before').content)).toBe('none');
        expect(await message.getByTestId('remote-human-profile').evaluate((element) => getComputedStyle(element, '::after').content)).toBe('none');
        await expect(message.getByTestId('mate-message-content')).toContainText(
          variant === 'teamRemoteHuman' ? 'Berlin volunteers' : 'profile image'
        );
        await expect(message.getByTestId('mate-profile')).toHaveCount(0);
        await expect(message.getByTestId('chat-mate-name')).toHaveCount(0);
        await expect(message.getByTestId('remote-human-name')).toHaveClass(/chat-mate-name-link/);
        nameStyles[variant] = await message.getByTestId('remote-human-name').evaluate((element) => {
          const style = getComputedStyle(element);
          return { backgroundImage: style.backgroundImage, fontSize: style.fontSize, fontWeight: style.fontWeight };
        });
        await message.getByTestId('remote-human-name').click();
        await expect(page.locator('html')).toHaveAttribute('data-preview-settings-deep-link', 'teams/preview-team/members/member-preview');
        await message.getByTestId('remote-human-profile').click();
        await expect(page.locator('html')).toHaveAttribute('data-preview-settings-deep-link', 'teams/preview-team/members/member-preview');
        if (variant === 'teamRemoteWithAvatar') {
          await expect(message.getByTestId('remote-human-avatar-image')).toBeVisible();
        } else {
          await expect(message.getByTestId('remote-human-avatar-image')).toHaveCount(0);
          await expect(message.getByTestId('remote-human-profile')).toContainText('S');
        }
      } else {
        await expect(message.getByTestId('chat-mate-name')).toHaveText('Sophia');
        nameStyles[variant] = await message.getByTestId('chat-mate-name').evaluate((element) => {
          const style = getComputedStyle(element);
          return { backgroundImage: style.backgroundImage, fontSize: style.fontSize, fontWeight: style.fontWeight };
        });
        await expect(message.getByTestId('mate-profile')).toBeVisible();
        await expect(message.getByTestId('remote-human-name')).toHaveCount(0);
        const mateAvatar = await message.getByTestId('mate-profile').boundingBox();
        expect(mateAvatar).not.toBeNull();
        avatarMetrics[variant] = {
          width: mateAvatar!.width, height: mateAvatar!.height,
          x: mateAvatar!.x - messageBounds!.x, y: mateAvatar!.y - messageBounds!.y,
          shadow: await message.getByTestId('mate-profile').evaluate((element) => getComputedStyle(element).boxShadow),
        };
      }
    }
    expect(positions.teamAssistant.left).toBeLessThan(positions.teamOwnHuman.left);
    for (const variant of ['teamRemoteHuman', 'teamRemoteWithAvatar']) {
      expect(avatarMetrics[variant].width).toBe(avatarMetrics.teamAssistant.width);
      expect(avatarMetrics[variant].height).toBe(avatarMetrics.teamAssistant.height);
      expect(avatarMetrics[variant].shadow).toBe(avatarMetrics.teamAssistant.shadow);
      // Capture mode centers each variant vertically; compare avatar placement inside its message.
      expect(Math.abs(avatarMetrics[variant].x - avatarMetrics.teamAssistant.x)).toBeLessThanOrEqual(1);
      expect(Math.abs(avatarMetrics[variant].y - avatarMetrics.teamAssistant.y)).toBeLessThanOrEqual(1);
      expect(nameStyles[variant]).toEqual(nameStyles.teamAssistant);
    }
  });
}

// contract-test: direct surface=gui.web assertions=teams.chat.sender-identity-layout
test('@openmates uses Mate mention highlighting and opens Mates settings', async ({ page }) => {
  await page.goto('/dev/preview/ChatMessage?chrome=0&variant=teamOpenMatesMention');
  const canvas = await waitForComponentPreview(page);
  const mention = canvas.locator('.mate-mention[data-name="openmates"]');
  await expect(mention).toHaveText('@openmates');
  await expect(mention).toHaveCSS('cursor', 'pointer');
  await expect(mention).toHaveCSS('background-image', /linear-gradient/);
  await mention.click();
  await expect(page.locator('html')).toHaveAttribute('data-preview-settings-deep-link', 'mates');
});
