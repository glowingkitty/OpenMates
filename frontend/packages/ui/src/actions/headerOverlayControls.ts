/**
 * Switch floating chat/embed controls while they overlap their own header.
 * Measure actual bounds instead of assuming a fixed header height or scroll offset.
 * Scroll capture covers the nested chat and embed scrollers; observers cover
 * responsive headers, async mounting, and controls added after initial render.
 * Styling is shared in icons.css and removed when controls leave the banner.
 */
const HEADER_SELECTOR = '.chat-header-banner, .embed-header > .header-inner';
const CONTROL_SELECTOR = '.new-chat-button-wrapper, .button-wrapper';
const OVERLAY_ATTRIBUTE = 'data-header-overlay';

export function headerOverlayControls(node: HTMLElement) {
  const surface = node.closest<HTMLElement>('.chat-side, .fullscreen-container');
  if (!surface) return {};

  let frame: number | null = null;
  let header: HTMLElement | null = null;
  const resizeObserver = new ResizeObserver(schedule);

  function measure() {
    frame = null;
    const nextHeader = surface!.querySelector<HTMLElement>(HEADER_SELECTOR);
    if (nextHeader !== header) {
      if (header) resizeObserver.unobserve(header);
      header = nextHeader;
      if (header) resizeObserver.observe(header);
    }
    const banner = header?.getBoundingClientRect();
    const viewport = surface!.getBoundingClientRect();
    for (const control of Array.from(node.querySelectorAll<HTMLElement>(CONTROL_SELECTOR))) {
      const bounds = control.getBoundingClientRect();
      const overlaps = !control.closest('[data-header-overlay-disabled]') && !!banner && banner.width > 0 && banner.height > 0 &&
        bounds.bottom > Math.max(banner.top, viewport.top) &&
        bounds.top < Math.min(banner.bottom, viewport.bottom) &&
        bounds.right > Math.max(banner.left, viewport.left) &&
        bounds.left < Math.min(banner.right, viewport.right);
      control.toggleAttribute(OVERLAY_ATTRIBUTE, overlaps);
    }
  }

  function schedule() {
    if (frame === null) frame = requestAnimationFrame(measure);
  }

  const mutations = new MutationObserver(schedule);
  mutations.observe(surface, { childList: true, subtree: true });
  resizeObserver.observe(surface);
  resizeObserver.observe(node);
  surface.addEventListener('scroll', schedule, { capture: true, passive: true });
  window.addEventListener('resize', schedule);
  schedule();

  return {
    destroy() {
      if (frame !== null) cancelAnimationFrame(frame);
      mutations.disconnect();
      resizeObserver.disconnect();
      surface.removeEventListener('scroll', schedule, true);
      window.removeEventListener('resize', schedule);
      for (const control of Array.from(node.querySelectorAll(`[${OVERLAY_ATTRIBUTE}]`))) {
        control.removeAttribute(OVERLAY_ATTRIBUTE);
      }
    },
  };
}
