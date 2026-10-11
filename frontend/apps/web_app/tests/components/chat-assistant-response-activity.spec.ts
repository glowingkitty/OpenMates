// playwright-account: not_required reason=isolated_component_preview
// Contract for the accepted Thinking container and source-position activity rows.
// Uses static local preview data so CI never invokes AI or a shared chat runtime.
// Covers desktop, phone width, collapse controls, model flag, and reduced motion.
// Videos are captured by the component CI profile and uploaded from its receipt.
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

function preview(variant: string, width = 820) {
  return `/dev/preview/ChatMessage?${new URLSearchParams({
    variant, theme: 'light', background: '#dbeafe', width: String(width), chrome: '0',
  })}`;
}

test.describe('Assistant response activity', () => {
  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.response-container-glow,chat-processing-feedback.accessible-responsive,chat-processing-feedback.selected-mate-identity
  test('starts with a real assistant Thinking container and a bottom glow', async ({ page }) => {
    await page.goto(preview('responseThinking'));
    await waitForComponentPreview(page);
    const response = page.getByTestId('mate-message-content');
    await expect(response).toBeVisible();
    await expect(response.getByTestId('assistant-transient-thinking')).toContainText('Thinking');
    const thinkingGlyph = response.getByTestId('assistant-status-ai-glyph');
    const glyphStyle = await thinkingGlyph.evaluate((node) => {
      const style = getComputedStyle(node);
      const tokenProbe = document.createElement('span');
      tokenProbe.style.background = 'var(--color-primary-start)';
      document.body.append(tokenProbe);
      const expectedBackground = getComputedStyle(tokenProbe).backgroundColor;
      tokenProbe.remove();
      return { mask: style.maskImage, background: style.backgroundColor, expectedBackground };
    });
    expect(glyphStyle.mask).toContain('data:image/svg+xml');
    expect(glyphStyle.background).toBe(glyphStyle.expectedBackground);
    const labelColor = await response.getByTestId('assistant-transient-thinking')
      .evaluate((node) => getComputedStyle(node).color);
    expect(labelColor).toBe(glyphStyle.background);
    await expect(response.getByTestId('assistant-response-status')).toHaveCount(0);
    const activeModel = page.getByTestId('generated-by-container');
    await expect(activeModel.getByTestId('using-model')).toHaveText(/^Using .+ 🇪🇺$/);
    await expect(activeModel.getByTestId('generated-by')).toHaveCount(0);
    await expect(activeModel.getByTestId('generated-by-cost')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Report bad answer' })).toHaveCount(0);
    await expect(response).toHaveClass(/assistant-response-active/);
    const nameBox = (await response.getByTestId('chat-mate-name').boundingBox())!;
    const thinkingBox = (await response.getByTestId('assistant-transient-thinking').boundingBox())!;
    const responseBox = (await response.boundingBox())!;
    expect(Math.abs(nameBox.y + nameBox.height / 2 - thinkingBox.y - thinkingBox.height / 2)).toBeLessThan(6);
    expect(responseBox.width).toBeGreaterThan(500);
    expect(responseBox.height).toBeLessThan(70);
    const glow = await response.evaluate((node) => {
      const style = getComputedStyle(node, '::after');
      return { backgroundImage: style.backgroundImage, filter: style.filter, height: style.height };
    });
    expect(glow.backgroundImage).toContain('linear-gradient');
    expect(glow.filter).toContain('blur');
    expect(Number.parseFloat(glow.height)).toBeGreaterThan(10);
    const tail = await response.evaluate((node) => {
      const bubble = getComputedStyle(node);
      const pointer = getComputedStyle(node, '::before');
      return { bubbleColor: bubble.backgroundColor, pointerColor: pointer.backgroundColor,
        mask: pointer.maskImage, clip: pointer.clipPath, left: pointer.left };
    });
    expect(tail.pointerColor).toBe(tail.bubbleColor);
    expect(tail.mask).toBe('none');
    expect(tail.clip).toContain('polygon');
    expect(Number.parseFloat(tail.left)).toBeLessThan(0);
    const bubbleBox = (await response.boundingBox())!;
    const modelBox = (await page.getByTestId('generated-by-container').boundingBox())!;
    expect(Math.abs(modelBox.x + modelBox.width / 2 - bubbleBox.x - bubbleBox.width / 2)).toBeLessThan(14);
    const rainbowFrames = await response.evaluate((node) => {
      const animationName = getComputedStyle(node, '::after').animationName;
      for (const sheet of Array.from(document.styleSheets)) {
        try {
          const rule = Array.from(sheet.cssRules).find((item) =>
            item instanceof CSSKeyframesRule && item.name === animationName) as CSSKeyframesRule | undefined;
          if (rule) return Array.from(rule.cssRules).map((frame) => Number.parseFloat(frame.style.backgroundPosition));
        } catch { /* Ignore unrelated inaccessible stylesheets. */ }
      }
      return [];
    });
    expect(rainbowFrames).toEqual([200, 0]);
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence,chat-processing-feedback.completed-processing-summary,chat-processing-feedback.selected-mate-identity
  test('keeps adjacent calls together and prose between activity groups', async ({ page }) => {
    await page.goto(preview('responseCompleted'));
    await waitForComponentPreview(page);
    const groups = page.getByTestId('assistant-activity-group');
    await expect(groups).toHaveCount(2);
    await expect(groups.first().getByTestId('assistant-activity-toggle')).toHaveAttribute('aria-expanded', 'false');
    await expect(groups.first()).toContainText('Web');
    await expect(groups.first()).toContainText('News');
    await expect(groups.first().locator('.activity-app-icon')).toHaveCount(3);
    await expect(groups.first().getByTestId('assistant-thinking-app-icon')).toHaveCount(1);
    await expect(groups.first().getByTestId('assistant-skill-app-icon')).toHaveCount(2);
    await expect(groups.nth(1).locator('.activity-app-icon')).toHaveCount(1);
    await expect(groups.nth(1).getByTestId('assistant-thinking-app-icon')).toHaveCount(0);
    const iconShape = await groups.first().locator('.activity-app-icon').first().evaluate((node) => {
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return { radius: style.borderRadius, overflow: style.overflow, width: rect.width, height: rect.height };
    });
    expect(iconShape.radius).toBe('50%');
    expect(iconShape.overflow).toBe('hidden');
    expect(Math.abs(iconShape.width - iconShape.height)).toBeLessThan(1);
    const iconSurface = await groups.first().locator('.activity-app-icon .icon').first().evaluate((node) => {
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return { radius: style.borderRadius, width: rect.width, height: rect.height };
    });
    expect(iconSurface.radius).toBe('50%');
    expect(Math.abs(iconSurface.width - iconSurface.height)).toBeLessThan(1);
    expect(iconSurface.width).toBeGreaterThanOrEqual(iconShape.width - 4);
    const stackedIcons = await groups.first().locator('.activity-app-icon').evaluateAll((nodes) =>
      nodes.map((node) => { const rect = node.getBoundingClientRect(); return { x: rect.x, right: rect.right }; }));
    expect(stackedIcons[1].x).toBeGreaterThan(stackedIcons[0].x);
    expect(stackedIcons[1].x).toBeLessThan(stackedIcons[0].right);
    expect((await groups.first().getByTestId('assistant-activity-toggle').boundingBox())!.height).toBeLessThan(48);
    const firstParagraph = page.getByText('I will compare two sources.');
    const middleParagraph = page.getByText('The first comparison is ready.');
    const lastParagraph = page.getByText('The answer keeps both results in source order.');
    await expect(firstParagraph).toBeVisible();
    await expect(middleParagraph).toBeVisible();
    await expect(lastParagraph).toBeVisible();
    const firstGroupY = (await groups.first().boundingBox())!.y;
    const secondGroupY = (await groups.nth(1).boundingBox())!.y;
    expect((await firstParagraph.boundingBox())!.y).toBeLessThan(firstGroupY);
    expect((await middleParagraph.boundingBox())!.y).toBeGreaterThan(firstGroupY);
    expect((await middleParagraph.boundingBox())!.y).toBeLessThan(secondGroupY);
    expect((await lastParagraph.boundingBox())!.y).toBeGreaterThan(secondGroupY);
    await groups.first().getByTestId('assistant-activity-toggle').click();
    await expect(groups.first().getByTestId('assistant-activity-toggle')).toHaveAttribute('aria-expanded', 'true');
    await expect(groups.first().getByTestId('assistant-activity-body')).toBeVisible();
    await expect(groups.first().getByTestId('assistant-response-thinking')).toContainText('Thinking for this response');
    await expect(groups.first().getByTestId('assistant-response-thinking')).toContainText('compare the available sources');
    await expect(groups.nth(1).getByTestId('assistant-response-thinking')).toHaveCount(0);
    const finishedBubble = (await page.getByTestId('mate-message-content').boundingBox())!;
    const finishedModel = (await page.getByTestId('generated-by-container').boundingBox())!;
    expect(finishedModel.x).toBeLessThan(finishedBubble.x + finishedBubble.width / 3);
    await expect(page.getByTestId('generated-by')).toHaveText(/^generated by .+ 🇪🇺$/);
    await expect(page.getByTestId('using-model')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Report bad answer' })).toBeVisible();
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.skill-activity-label,chat-processing-feedback.turn-lifecycle
  test('labels retrieval and action skill IDs without reading user prose', async ({ page }) => {
    await page.goto(preview('responseStreamingReasoning'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('assistant-response-status')).toContainText('Thinking');
    await page.goto(preview('responseStreaming'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('assistant-response-status')).toContainText('Researching');
    await expect(page.getByTestId('using-model')).toHaveText(/^Using .+ 🇪🇺$/);
    await expect(page.getByTestId('generated-by')).toHaveCount(0);
    await expect(page.getByTestId('generated-by-cost')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Report bad answer' })).toHaveCount(0);
    const activeStatusColor = await page.getByTestId('assistant-response-status')
      .evaluate((node) => getComputedStyle(node).color);
    const activeGlyphColor = await page.getByTestId('assistant-response-status').getByTestId('assistant-status-ai-glyph')
      .evaluate((node) => getComputedStyle(node).backgroundColor);
    expect(activeStatusColor).toBe(activeGlyphColor);
    await page.goto(preview('responseWorking'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('assistant-response-status')).toContainText('Working');
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.completed-processing-summary
  test('collapses response-wide thinking even when no app was used', async ({ page }) => {
    await page.goto(preview('responseThinkingOnlyCompleted'));
    await waitForComponentPreview(page);
    const group = page.getByTestId('assistant-activity-group');
    await expect(group).toHaveCount(1);
    await expect(group.getByTestId('assistant-thinking-app-icon')).toHaveCount(1);
    await expect(group.getByTestId('assistant-activity-toggle')).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByText('A concise answer.')).toBeVisible();
    await group.getByTestId('assistant-activity-toggle').click();
    await expect(group.getByTestId('assistant-response-thinking')).toContainText('Thinking for this response');
    await expect(group.getByTestId('assistant-response-thinking')).toContainText('I checked the wording before answering.');
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.completed-processing-summary,chat-processing-feedback.turn-lifecycle
  test('collapses finished adjacent skills while the assistant remains active', async ({ page }) => {
    await page.goto(preview('responseLiveSkillCompletion'));
    await waitForComponentPreview(page);
    const group = page.getByTestId('assistant-activity-group');
    const toggle = group.getByTestId('assistant-activity-toggle');
    await expect(group).toHaveCount(1);
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(group.getByTestId('assistant-activity-body')).toBeVisible();
    await expect(page.getByTestId('mate-message-content')).toHaveClass(/assistant-response-active/);
    await page.evaluate(() => document.dispatchEvent(new Event('preview:finish-second-skill')));
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(group.getByTestId('assistant-activity-body')).toHaveCount(0);
    await expect(page.getByTestId('mate-message-content')).toHaveClass(/assistant-response-active/);
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(group.getByTestId('assistant-activity-body')).toBeVisible();
    await expect(group.getByTestId('assistant-activity-body').getByTestId('embed-preview')).toHaveCount(2);
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.accessible-responsive,chat-processing-feedback.response-container-glow
  test('fits phone width and respects reduced motion', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(preview('responseStreaming', 390));
    await waitForComponentPreview(page);
    const response = page.getByTestId('mate-message-content');
    await expect(response).toBeVisible();
    const box = await response.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
    const animation = await response.evaluate((node) => getComputedStyle(node, '::after').animationName);
    expect(animation).toBe('none');
    await expect(page.getByTestId('assistant-activity-group').last().getByTestId('assistant-activity-toggle')).toHaveAttribute('aria-expanded', 'true');
  });
});
