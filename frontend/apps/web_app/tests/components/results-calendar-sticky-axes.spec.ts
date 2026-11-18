import { expect, test, type Locator } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
test.setTimeout(120_000);

// The results calendar scrolls in one box. Scrolling down keeps the week toolbar
// and the day headers in view; scrolling sideways keeps the hour column in view,
// so a scrolled week never turns into an unlabeled empty grid (TASK-3927).
const WIDTHS = { phone: 390, laptop: 1000 } as const;

async function box(locator: Locator) {
  const rect = await locator.boundingBox();
  if (!rect) throw new Error('element has no layout box');
  return rect;
}

for (const [label, width] of Object.entries(WIDTHS)) {
  // contract-test: supporting surface=gui.web assertions=authored-results.presentation.standard-results-view,calendar-event.preview.shared-week-layout
  test(`calendar keeps day headers and hours in view while scrolling (${label})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`/dev/preview/embeds/EmbedsMapView?chrome=0&theme=light&width=${width}`);
    await waitForComponentPreview(page);
    const view = page.getByTestId('embeds-map-view');
    await view.getByTestId('embeds-results-view-tab-calendar').click();
    const calendar = view.getByTestId('embeds-results-view-calendar');
    await expect(calendar).toBeVisible();
    await expect(view.getByTestId('embeds-results-view-calendar-item').first()).toBeVisible();

    // Overlapping entries stay readable side by side instead of shrinking to slivers.
    const itemWidths = await view.getByTestId('embeds-results-view-calendar-item')
      .evaluateAll(items => items.map(item => item.getBoundingClientRect().width));
    expect(Math.min(...itemWidths), 'narrowest calendar entry fits a station name').toBeGreaterThanOrEqual(88);
    // A long entry (an overnight flight) starts with its title, not with empty space: buttons centre
    // their content by default, which pushed the title out of view.
    const titleOffsets = await view.getByTestId('embeds-results-view-calendar-item').evaluateAll(items => items.map(item => {
      const title = item.querySelector('strong');
      return title ? title.getBoundingClientRect().top - item.getBoundingClientRect().top : 0;
    }));
    expect(Math.max(...titleOffsets), 'entry titles sit at the top of their entry').toBeLessThanOrEqual(12);

    const toolbar = calendar.getByTestId('embeds-results-view-calendar-toolbar');
    const header = calendar.getByTestId('embeds-results-view-calendar-day-header').first();
    const hours = calendar.getByTestId('embeds-results-view-calendar-time-column');
    const frame = await box(calendar);
    const headerBefore = await box(header);
    await testInfo.attach(`${label}-calendar-start`, { body: await calendar.screenshot(), contentType: 'image/png' });

    const scroll = await calendar.evaluate((element) => {
      element.scrollTop = 320;
      element.scrollLeft = 240;
      return { top: element.scrollTop, left: element.scrollLeft };
    });
    expect(scroll.top, 'the calendar has hours below the first view').toBeGreaterThan(0);
    await expect.poll(async () => (await box(header)).y).toBeCloseTo(headerBefore.y, 0);

    // The toolbar stays at the top edge, the hour column at the left edge.
    expect((await box(toolbar)).y).toBeCloseTo(frame.y, 0);
    // The toolbar spans the whole box, so no scrolled entry shows beside it.
    expect((await box(toolbar)).width).toBeCloseTo(await calendar.evaluate(element => element.clientWidth), 0);
    expect((await box(hours)).x).toBeCloseTo(frame.x, 0);
    // The hour column is painted over the day columns that scroll beneath it.
    const hourColumn = await box(hours);
    await expect(hours.getByTestId('embeds-results-view-calendar-hour').first()).toBeAttached();
    const onTop = await page.evaluate(({ x, y }) => {
      const element = document.elementFromPoint(x, y);
      return Boolean(element?.closest('[data-testid="embeds-results-view-calendar-time-column"]'));
    }, { x: hourColumn.x + hourColumn.width / 2, y: frame.y + frame.height / 2 });
    expect(onTop, 'hour labels are painted over the days that scroll beneath them').toBe(true);
    if (scroll.left > 0) {
      const headerAfter = await box(header);
      expect(headerAfter.x, 'days move sideways while the hour column stays').toBeLessThan(headerBefore.x);
    }
    await testInfo.attach(`${label}-calendar-scrolled`, { body: await calendar.screenshot(), contentType: 'image/png' });
  });
}
