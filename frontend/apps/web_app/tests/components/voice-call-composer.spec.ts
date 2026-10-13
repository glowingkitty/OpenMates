// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

function preview(width: number, variant?: string): string {
  return `/dev/preview/enter_message/MessageInput?${new URLSearchParams({
    chrome: '0', theme: 'light', background: '#dbeafe', width: String(width),
    ...(variant ? { variant } : {}),
  })}`;
}

test.describe('Voice call composer entry surface', () => {
  for (const { viewport, component } of [
    { viewport: 1280, component: 680 },
    { viewport: 390, component: 330 },
  ]) {
    // contract-test: supporting surface=gui.web assertions=video-call.chat.typed-input,message-input.layout.responsive-parity
    test(`keeps the native editor visible and focusable at ${viewport}px`, async ({ page }) => {
      await page.setViewportSize({ width: viewport, height: 844 });
      for (const variant of [undefined, 'inlineCompact']) {
        await page.goto(preview(component, variant));
        await waitForComponentPreview(page);
        const field = page.getByTestId('message-field');
        const editorHost = page.getByTestId('message-editor');
        const editor = editorHost.locator('[contenteditable="true"]');
        await expect(field).toBeVisible();
        await expect(editorHost).toBeVisible();
        await expect(editor).toBeVisible();
        const geometry = await field.evaluate((element) => {
          const field = element.getBoundingClientRect();
          const editor = element.querySelector('[contenteditable="true"]')!.getBoundingClientRect();
          return {
            fieldWidth: field.width, fieldHeight: field.height,
            editorWidth: editor.width, editorHeight: editor.height,
            fieldRight: field.right, editorRight: editor.right,
            background: getComputedStyle(element).backgroundColor,
          };
        });
        expect(geometry.fieldWidth).toBeGreaterThan(200);
        expect(geometry.fieldHeight).toBeGreaterThanOrEqual(44);
        expect(geometry.editorWidth).toBeGreaterThan(180);
        expect(geometry.editorHeight).toBeGreaterThan(0);
        expect(geometry.fieldRight).toBeLessThanOrEqual(viewport + 1);
        expect(geometry.editorRight).toBeLessThanOrEqual(viewport + 1);
        expect(geometry.background).not.toBe('rgba(0, 0, 0, 0)');
        await editor.click();
        await expect(editor).toBeFocused();
        await page.keyboard.insertText('Typed call text');
        await expect(editor).toContainText('Typed call text');
      }
    });
  }
});
