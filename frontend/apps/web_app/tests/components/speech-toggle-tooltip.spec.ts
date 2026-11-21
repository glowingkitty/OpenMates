// playwright-account: not_required reason=isolated_component_preview
// The "Speak responses" tooltip opens only on real pointer movement or keyboard focus.
// A click closes it, and a button that slides under a resting pointer (the composer
// re-layout after Send in a call) never opens it, so it cannot linger in product videos.
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (width: number) =>
  `/dev/preview/enter_message/ActionButtons?${new URLSearchParams({ chrome: '0', theme: 'light', background: '#dbeafe', width: String(width) })}`;

test.describe('Speech toggle tooltip', () => {
  // contract-test: supporting surface=gui.web assertions=video-call.chat.typed-input
  test('opens on pointer movement, closes on click and stays closed under a resting pointer', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(preview(680));
    await waitForComponentPreview(page);
    const speech = page.getByTestId('assistant-speech-toggle');
    const tooltip = page.getByRole('tooltip');
    await expect(speech).toBeVisible();

    await speech.hover();
    await expect(tooltip).toBeVisible({ timeout: 3_000 });
    await testInfo.attach('speech-tooltip-hover', { body: await page.screenshot(), contentType: 'image/png' });

    await speech.click();
    await expect(tooltip).toHaveCount(0);
    // The pointer rests on the button after the click: the tooltip does not come back.
    await page.waitForTimeout(1_500);
    await expect(tooltip).toHaveCount(0);
    await testInfo.attach('speech-tooltip-after-click', { body: await page.screenshot(), contentType: 'image/png' });

    // Leave, then park the pointer beside the button and slide the button under it.
    await page.mouse.move(5, 5);
    const box = (await speech.boundingBox())!;
    const restX = box.x + box.width / 2;
    // 40px below the button centre: outside it now, on its centre once it moves 40px down.
    const restY = box.y + box.height / 2 + 40;
    await page.mouse.move(restX, restY);
    await speech.evaluate((node, offset) => { (node as HTMLElement).style.transform = `translateY(${offset}px)`; }, 40);
    await page.waitForTimeout(1_500);
    await expect(tooltip).toHaveCount(0);
    await testInfo.attach('speech-tooltip-slid-under-pointer', { body: await page.screenshot(), contentType: 'image/png' });

    // Real movement over the moved button opens it again.
    await page.mouse.move(restX + 3, restY + 2);
    await expect(tooltip).toBeVisible({ timeout: 3_000 });
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.typed-input
  test('keyboard focus opens it and touch layouts never show it', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(preview(680));
    await waitForComponentPreview(page);
    const speech = page.getByTestId('assistant-speech-toggle');
    // Programmatic focus (as after a click) is not keyboard focus.
    await speech.evaluate((node) => (node as HTMLElement).focus({ focusVisible: false } as FocusOptions));
    await page.waitForTimeout(1_500);
    await expect(page.getByRole('tooltip')).toHaveCount(0);
    await speech.evaluate((node) => (node as HTMLElement).blur());
    await page.keyboard.press('Tab');
    for (let i = 0; i < 12 && !(await speech.evaluate((node) => node === document.activeElement)); i++) await page.keyboard.press('Tab');
    await expect(speech).toBeFocused();
    await expect(page.getByRole('tooltip')).toBeVisible({ timeout: 3_000 });
    await testInfo.attach('speech-tooltip-keyboard-focus', { body: await page.screenshot(), contentType: 'image/png' });
  });
});
