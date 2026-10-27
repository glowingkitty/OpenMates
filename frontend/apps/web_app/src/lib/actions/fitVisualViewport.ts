import { isDesktop } from '@repo/ui/utils/platform';

/** Keep the fixed app shell inside the area left visible by a mobile keyboard. */
export function fitVisualViewport(node: HTMLElement) {
  const viewport = window.visualViewport;
  if (!viewport || isDesktop()) return;

  let frame: number | undefined;
  const original = { top: node.style.top, height: node.style.height, bottom: node.style.bottom };
  const update = () => {
    frame = undefined;
    // Pinch zoom is user-owned; retain the layout established before zooming.
    if (Math.abs(viewport.scale - 1) > 0.01 || viewport.height <= 0) return;
    node.style.top = `${viewport.offsetTop}px`;
    node.style.height = `${viewport.height}px`;
    node.style.bottom = 'auto';
  };
  const schedule = () => {
    if (frame === undefined) frame = requestAnimationFrame(update);
  };
  update();
  viewport.addEventListener('resize', schedule);
  viewport.addEventListener('scroll', schedule);
  window.addEventListener('resize', schedule);
  window.addEventListener('pageshow', schedule);

  return {
    destroy() {
      if (frame !== undefined) cancelAnimationFrame(frame);
      viewport.removeEventListener('resize', schedule);
      viewport.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
      window.removeEventListener('pageshow', schedule);
      Object.assign(node.style, original);
    },
  };
}
