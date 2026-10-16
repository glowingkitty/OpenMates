// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

for (const width of [390, 820]) {
  for (const theme of ['light', 'dark']) {
    // contract-test: direct surface=gui.web assertions=video-call.chat.assistant-identity
    test(`OpenMates fallback identity at ${width}px in ${theme}`, async ({ page }) => {
      test.setTimeout(60_000);
      await page.setViewportSize({ width: 1280, height: 900 });
      for (const variant of ['assistant', 'openmatesOfficial']) {
        const params = new URLSearchParams({ chrome: '0', variant, theme,
          background: '#dbeafe', width: String(width), props: JSON.stringify({ containerWidth: width }) });
        await page.goto(`/dev/preview/ChatMessage?${params}`);
        const canvas = await waitForComponentPreview(page);
        const message = canvas.locator('.chat-message');
        await expect(message.getByTestId('chat-mate-name')).toHaveText('OpenMates');
        await expect(message.getByTestId('chat-mate-name')).not.toHaveJSProperty('tagName', 'BUTTON');
        const logo = message.getByRole('img', { name: 'OpenMates', exact: true });
        await expect(logo).toBeVisible();
        await expect(logo).toHaveAttribute('src', '/favicon.svg');
        await expect(logo).toHaveJSProperty('complete', true);
        await expect.poll(() => logo.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
        await expect(message.locator('.mate-profile-link')).toHaveCount(0);
        await expect(message.getByTestId('mate-profile')).toHaveCount(0);
        const bounds = await logo.boundingBox();
        expect(bounds).not.toBeNull();
        expect(bounds!.width).toBe(width <= 500 ? 25 : 60);
        expect(bounds!.height).toBe(bounds!.width);
        await expect(message.getByTestId('mate-message-content')).toContainText(
          variant === 'assistant' ? 'Svelte 5 runes' : 'A reply from OpenMates.'
        );
        expect(await message.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
      }
    });
  }
}

// contract-test: supporting surface=gui.web assertions=video-call.chat.assistant-identity,teams.chat.sender-identity-layout
test('Explicit senders, mates, imported providers and team humans retain their identity', async ({ page }) => {
  test.setTimeout(60_000);
  for (const [variant, name] of [
    ['teamAssistant', 'Sophia'], ['namedAssistant', 'Casey'], ['importedChatGPT', 'ChatGPT'],
    ['teamRemoteHuman', 'Sam'],
  ]) {
    const params = new URLSearchParams({ chrome: '0', theme: 'light', background: '#dbeafe', width: '820', variant });
    await page.goto(`/dev/preview/ChatMessage?${params}`);
    const canvas = await waitForComponentPreview(page);
    const message = canvas.locator('.chat-message');
    await expect(message.getByTestId(variant === 'teamRemoteHuman' ? 'remote-human-name' : 'chat-mate-name')).toHaveText(name);
    if (variant === 'teamAssistant') {
      await expect(message.locator('button.mate-profile-link')).toBeVisible();
      await expect(message.getByTestId('mate-profile')).toHaveClass(/general_knowledge/);
      await message.locator('button.mate-profile-link').click();
      await expect(page.locator('html')).toHaveAttribute('data-preview-settings-deep-link', 'mates/general_knowledge');
    } else if (variant === 'importedChatGPT') {
      await expect(message.getByTestId('imported-provider-profile')).toHaveAttribute('aria-label', 'ChatGPT');
      await expect(message.getByTestId('openmates-profile')).toHaveCount(0);
    } else if (variant === 'teamRemoteHuman') {
      await expect(message.getByTestId('remote-human-profile')).toHaveAttribute('aria-label', 'Sam');
      await expect(message.getByTestId('openmates-profile')).toHaveCount(0);
      await expect(message.getByTestId('chat-mate-name')).toHaveCount(0);
    }
  }
});
