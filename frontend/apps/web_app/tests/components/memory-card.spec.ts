import {expect, test} from '../helpers/cookie-audit';
import {waitForComponentPreview} from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
for (const visibility of ['private', 'public'] as const) {
    // contract-test: supporting surface=gui.web assertions=app-memories.discovery.visibility-cards
    test(`renders and activates a ${visibility} Memory in the shared card`, async ({page}, testInfo) => {
        await page.setViewportSize({width: 390, height: 844});
        await page.addInitScript(() => window.addEventListener('preview-memory-card-selected', event => {
            (window as unknown as {selectedMemoryApp: string}).selectedMemoryApp = (event as CustomEvent).detail;
        }));
        await page.goto(`/dev/preview/settings/AppStoreCard?chrome=0&theme=light&background=%23dbeafe&width=350${visibility === 'public' ? '&variant=public' : ''}`);
        await waitForComponentPreview(page);
        const card = page.getByTestId('app-store-card');
        const badge = card.getByTestId('memory-card-visibility');
        await expect(badge).toHaveText(visibility === 'public' ? 'Public' : 'Private');
        const icon = badge.locator('.icon');
        const expectedIcon = visibility === 'public' ? 'web' : 'lock';
        const iconStyle = await icon.evaluate((element, expectedIcon) => {
            const style = getComputedStyle(element);
            return {color: style.backgroundColor, mask: style.maskImage,
                expectedMask: style.getPropertyValue(`--icon-url-${expectedIcon}`).trim()};
        }, expectedIcon);
        expect(iconStyle.color).toBe('rgb(255, 255, 255)');
        await expect(icon).toHaveClass(new RegExp(`\\bicon_${expectedIcon}\\b`));
        expect(iconStyle.expectedMask).not.toBe('');
        expect(iconStyle.mask).toBe(iconStyle.expectedMask);
        await expect(icon).toHaveAttribute('aria-hidden', 'true');
        const geometry = await card.evaluate(element => {
            const badge = element.querySelector('[data-testid="memory-card-visibility"]')!;
            const description = element.querySelector('[data-testid="app-card-description"]')!;
            const title = element.querySelector('[data-testid="app-card-name"]')!;
            const bounds = element.getBoundingClientRect();
            return {width: bounds.width, height: bounds.height, left: badge.getBoundingClientRect().left - bounds.left,
                top: badge.getBoundingClientRect().top - bounds.top,
                separated: badge.getBoundingClientRect().bottom < title.getBoundingClientRect().top,
                sameColor: getComputedStyle(badge).color === getComputedStyle(description).color,
                descriptionHeight: description.getBoundingClientRect().height,
                descriptionLineHeight: parseFloat(getComputedStyle(description).lineHeight),
                fits: title.getBoundingClientRect().bottom <= description.getBoundingClientRect().top
                    && description.getBoundingClientRect().bottom <= bounds.bottom};
        });
        const {descriptionHeight, descriptionLineHeight, ...layout} = geometry;
        expect(descriptionHeight).toBeGreaterThanOrEqual(2 * descriptionLineHeight - 0.5);
        expect(layout).toEqual({width: 223, height: 129, left: 16, top: 10, separated: true, sameColor: true, fits: true});
        await expect(card).toBeInViewport();
        await card.hover();
        await card.focus();
        await expect(card).toBeFocused();
        await page.keyboard.press('Enter');
        await expect.poll(() => page.evaluate(() => (window as unknown as {selectedMemoryApp?: string}).selectedMemoryApp)).toBe('design');
        await testInfo.attach(`${visibility}-memory-card-phone`, {body: await page.screenshot(), contentType: 'image/png'});
    });
}
