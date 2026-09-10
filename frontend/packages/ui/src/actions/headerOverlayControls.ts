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
const INITIALIZING_ATTRIBUTE = 'data-header-overlay-initializing';

export function headerOverlayControls(node: HTMLElement) {
  const surface = node.closest<HTMLElement>('.chat-side, .fullscreen-container');
  if (!surface) return {};

  let frame: number | null = null;
  let header: HTMLElement | null = null;
  let initialFrame: number | null = null;
  const initialized = new WeakSet<HTMLElement>();
  const initializing = new Set<HTMLElement>();
  const resizeObserver = new ResizeObserver(measure);

  function measure() {
    const nextHeader = surface!.querySelector<HTMLElement>(HEADER_SELECTOR);
    if (nextHeader !== header) {
      if (header) resizeObserver.unobserve(header);
      header = nextHeader;
      if (header) resizeObserver.observe(header);
    }
    const banner = header?.getBoundingClientRect();
    const viewport = surface!.getBoundingClientRect();
    for (const control of Array.from(node.querySelectorAll<HTMLElement>(CONTROL_SELECTOR))) {
      if (!initialized.has(control)) {
        initialized.add(control);
        initializing.add(control);
        control.setAttribute(INITIALIZING_ATTRIBUTE, '');
      }
      const bounds = control.getBoundingClientRect();
      const overlaps = !control.closest('[data-header-overlay-disabled]') && !!banner && banner.width > 0 && banner.height > 0 &&
        bounds.bottom > Math.max(banner.top, viewport.top) &&
        bounds.top < Math.min(banner.bottom, viewport.bottom) &&
        bounds.right > Math.max(banner.left, viewport.left) &&
        bounds.left < Math.min(banner.right, viewport.right);
      control.toggleAttribute(OVERLAY_ATTRIBUTE, overlaps);
    }
    if (initializing.size && initialFrame === null) {
      initialFrame = requestAnimationFrame(() => {
        // Include siblings mounted in the same update before committing the first style.
        measure();
        for (const control of Array.from(initializing)) {
          // Flush the final non-animated style before enabling future scroll transitions.
          void getComputedStyle(control).backgroundColor;
          for (const child of Array.from(control.querySelectorAll('.top-button, .action-label'))) {
            void getComputedStyle(child).filter;
          }
          control.removeAttribute(INITIALIZING_ATTRIBUTE);
        }
        initializing.clear();
        initialFrame = null;
      });
    }
  }

  function schedule() {
    if (frame === null) frame = requestAnimationFrame(() => {
      frame = null;
      measure();
    });
  }

  // Mount changes must be styled before paint, not deferred until the next frame.
  const mutations = new MutationObserver(measure);
  mutations.observe(surface, { childList: true, subtree: true });
  resizeObserver.observe(surface);
  resizeObserver.observe(node);
  surface.addEventListener('scroll', schedule, { capture: true, passive: true });
  window.addEventListener('resize', schedule);
  measure();

  return {
    destroy() {
      if (frame !== null) cancelAnimationFrame(frame);
      if (initialFrame !== null) cancelAnimationFrame(initialFrame);
      for (const control of Array.from(initializing)) control.removeAttribute(INITIALIZING_ATTRIBUTE);
      initializing.clear();
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
