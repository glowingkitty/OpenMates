// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const url = 'https://example.test/article';

for (const change of ['edit', 'restore', 'switch'] as const) {
  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,message-input.send.ownership
  test(`preserves the current draft when URL metadata arrives after ${change}`, async ({ page }) => {
    let releaseMetadata!: () => void;
    const metadataGate = new Promise<void>(resolve => { releaseMetadata = resolve; });
    let requests = 0;
    await page.route('**/api/v1/metadata?**', async route => {
      requests += 1;
      await metadataGate;
      await route.fulfill({ json: { type: 'website', url, title: 'Synthetic article' } });
    });
    await page.goto('/dev/preview/enter_message/MessageInputFocusFixture?chrome=0&theme=light&background=%23dbeafe&width=680&variant=imageDraft');
    await waitForComponentPreview(page);
    const fixture = page.getByTestId('composer-focus-fixture');
    await expect(fixture).toHaveAttribute('data-ready', 'true');
    const editor = page.getByTestId('message-editor').locator('.ProseMirror');
    await editor.fill(`${url} `);
    await expect.poll(() => requests).toBe(1);

    if (change === 'edit') {
      // A second delimiter used to start another conversion while the first
      // request held serialization frozen at the old URL-only source.
      await editor.press('End');
      await editor.pressSequentially(' Keep this new sentence.');
      const reparsed = page.waitForEvent('console', {
        predicate: message => message.text().includes('[MessageInput] Processing closed URLs:'),
      });
      await editor.press('Space');
      await reparsed;
      await expect(editor).toContainText('Keep this new sentence.');
    } else {
      if (change === 'restore') {
        // Resume a retained draft after a transient clear. An occupied, focused
        // draft correctly rejects a passive same-chat restore.
        await editor.fill('');
        await expect(editor).toHaveText(/^\s*$/);
      }
      await page.evaluate(event => window.dispatchEvent(new Event(event)),
        change === 'restore' ? 'fixtureRestoreDraft' : 'fixtureSwitchEmptyDraft');
      if (change === 'restore') {
        await expect(editor).toContainText('Unsent multiline');
        await expect(editor.getByTestId('embed-preview')).toHaveCount(1);
      } else {
        await expect(fixture).toHaveAttribute('data-switched', 'true');
      }
    }

    const discarded = page.waitForEvent('console', {
      predicate: message => message.text().includes('[MessageInput] Discarding stale URL conversion'),
    });
    releaseMetadata();
    await discarded;
    await test.step('The latest draft survives the delayed conversion intact', async () => {
      if (change === 'edit') {
        await expect(editor).toHaveText(`${url}  Keep this new sentence.`);
        await expect(editor.getByTestId('embed-preview')).toHaveCount(0);
      } else if (change === 'restore') {
        await expect(editor).toContainText('Unsent multiline');
        await expect(editor).toContainText('second line');
        await expect(editor.getByTestId('embed-preview')).toHaveCount(1);
        await expect(editor.locator('[data-embed-id="synthetic-finished-image"]')).toBeVisible();
        await expect(editor).not.toContainText(url);
      } else {
        await expect(editor).toHaveText(/^\s*$/);
        await expect(editor.getByTestId('embed-preview')).toHaveCount(0);
      }
      await expect(editor).not.toContainText(/embed_id|```|Synthetic article/);
      expect(requests).toBe(1);
    });
  });
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
test('converts a closed URL when its source draft is unchanged', async ({ page }) => {
  await page.route('**/api/v1/metadata?**', route => route.fulfill({
    json: { type: 'website', url, title: 'Synthetic article' },
  }));
  await page.goto('/dev/preview/enter_message/MessageInputFocusFixture?chrome=0&theme=light&background=%23dbeafe&width=680');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('composer-focus-fixture')).toHaveAttribute('data-ready', 'true');
  const editor = page.getByTestId('message-editor').locator('.ProseMirror');
  await page.getByTestId('message-field').click({ position: { x: 8, y: 8 } });
  await expect(editor).toBeVisible();
  await expect(editor).toBeFocused();
  await editor.fill(`${url} `);
  await expect(editor.getByTestId('embed-preview')).toHaveCount(1);
  await expect(editor).toContainText('Synthetic article');
  await expect(editor).not.toContainText(/embed_id|```/);
});
