// frontend/packages/ui/src/components/embeds/containedMedia.ts
// Where the visible picture sits inside a media element drawn with
// `object-fit: contain`. Overlays such as the "AI generated" badge use it to
// stay on the picture instead of the letterbox bars beside it. Shared by image
// and video embeds; the element box alone does not say where the picture is.

/** Gap between the element box and the visible picture on each side, in CSS pixels. */
export interface ContainedInset {
  x: number;
  y: number;
}

/**
 * Inset of a picture of `natural` size drawn with `object-fit: contain` in a
 * box of `box` size. Null when either size is still unknown (not loaded yet).
 */
export function containedInset(
  box: { width: number; height: number },
  natural: { width: number; height: number },
): ContainedInset | null {
  if (box.width <= 0 || box.height <= 0 || natural.width <= 0 || natural.height <= 0) return null;
  const scale = Math.min(box.width / natural.width, box.height / natural.height);
  return {
    x: Math.max(0, (box.width - natural.width * scale) / 2),
    y: Math.max(0, (box.height - natural.height * scale) / 2),
  };
}

function naturalSize(element: HTMLImageElement | HTMLVideoElement): { width: number; height: number } {
  return element instanceof HTMLVideoElement
    ? { width: element.videoWidth, height: element.videoHeight }
    : { width: element.naturalWidth, height: element.naturalHeight };
}

/** Visible picture of a media element, in CSS pixels relative to its offset parent. */
export interface ContainedFrame {
  top: number;
  left: number;
  width: number;
  height: number;
}

/**
 * Where the visible picture of `element` sits inside its offset parent (the
 * nearest positioned ancestor), for overlays placed in that parent when the
 * media element does not fill it. Null while `inset` is unknown.
 */
export function containedFrame(element: HTMLElement, inset: ContainedInset | null): ContainedFrame | null {
  if (!inset) return null;
  return {
    top: element.offsetTop + inset.y,
    left: element.offsetLeft + inset.x,
    width: Math.max(0, element.clientWidth - 2 * inset.x),
    height: Math.max(0, element.clientHeight - 2 * inset.y),
  };
}

/**
 * Svelte action for an `<img>` or `<video>`: reports the picture inset (and the
 * element, for `containedFrame`) on load and whenever the element is resized.
 * Null until the media size is known.
 */
export function trackContainedInset(
  element: HTMLImageElement | HTMLVideoElement,
  onInset: (inset: ContainedInset | null, element: HTMLImageElement | HTMLVideoElement) => void,
) {
  let report = onInset;
  const measure = () =>
    report(containedInset({ width: element.clientWidth, height: element.clientHeight }, naturalSize(element)), element);
  const loadEvent = element instanceof HTMLVideoElement ? 'loadedmetadata' : 'load';
  element.addEventListener(loadEvent, measure);
  const observer = new ResizeObserver(measure);
  observer.observe(element);
  measure();
  return {
    update(next: (inset: ContainedInset | null, element: HTMLImageElement | HTMLVideoElement) => void) {
      report = next;
    },
    destroy() {
      element.removeEventListener(loadEvent, measure);
      observer.disconnect();
    },
  };
}
