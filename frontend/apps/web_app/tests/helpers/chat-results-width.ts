import { expect, type Locator } from '@playwright/test';

/** Measure the actual message lane, including avatar space and bubble padding. */
export async function expectChatResultsFullWidth(results: Locator) {
  const geometry = await results.evaluate((view) => {
    const alignment = view.closest<HTMLElement>('.message-align-left')!;
    const row = alignment.closest<HTMLElement>('.chat-message')!;
    const bubble = alignment.querySelector<HTMLElement>('.mate-message-content')!;
    const rowStyle = getComputedStyle(row);
    const rowBox = row.getBoundingClientRect();
    const bubbleStyle = getComputedStyle(bubble);
    const bubbleBox = bubble.getBoundingClientRect();
    const viewBox = view.getBoundingClientRect();
    const siblings = Array.from(row.children).filter((child) => child !== alignment);
    const avatarSpace = rowStyle.flexDirection === 'column' ? 0 :
      siblings.reduce((total, sibling) => {
        const style = getComputedStyle(sibling);
        return total + sibling.getBoundingClientRect().width +
          parseFloat(style.marginLeft) + parseFloat(style.marginRight);
      }, 0) + parseFloat(rowStyle.columnGap) * siblings.length;
    return {
      laneWidth: rowBox.width - avatarSpace,
      alignmentWidth: alignment.getBoundingClientRect().width,
      contentWidth: bubble.clientWidth - parseFloat(bubbleStyle.paddingLeft) - parseFloat(bubbleStyle.paddingRight),
      viewWidth: viewBox.width,
      viewRight: viewBox.right,
      bubbleRight: bubbleBox.right,
      pageOverflows: document.documentElement.scrollWidth > window.innerWidth + 1,
    };
  });

  expect(Math.abs(geometry.alignmentWidth - geometry.laneWidth), JSON.stringify(geometry)).toBeLessThanOrEqual(2);
  expect(Math.abs(geometry.viewWidth - geometry.contentWidth), JSON.stringify(geometry)).toBeLessThanOrEqual(2);
  expect(geometry.viewRight).toBeLessThanOrEqual(geometry.bubbleRight);
  expect(geometry.pageOverflows, 'results must stay within the viewport').toBe(false);
}
