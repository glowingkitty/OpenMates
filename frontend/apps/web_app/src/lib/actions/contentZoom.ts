// One gesture controller for rendered images, including HTML inserted by embed renderers.
// Custom drawing surfaces can opt in with data-content-zoom if they own no gestures.
import { getContentZoomSurface, type ZoomPoint as Point } from '@repo/ui/actions/contentZoomSurface';

interface View {
  image: HTMLElement | SVGElement;
  scale: number;
  offset: Point;
  fittedSize: Point;
}

interface TouchGesture {
  image: View['image'];
  start: Point;
  point: Point;
  distance: number;
  consumed: boolean;
}

const imageSelector = [
  'img:not([alt=""]):not([aria-hidden="true"])',
  '[data-testid="result-card-media"] img',
  'img.result-primary-media',
  '[data-content-zoom]',
  '[data-content-zoom-surface]',
].join(', ');
const tapInterval = 300;
const tapSlop = 24;
const maxScale = 4;
const origin = { x: 0, y: 0 };

function imageAt(target: EventTarget | null): View['image'] | null {
  if (!(target instanceof Element)) return null;
  const image = target.closest('[data-content-zoom-includes-images]') ?? target.closest(imageSelector);
  if (!(image instanceof HTMLElement || image instanceof SVGElement)) return null;
  if (getContentZoomSurface(image) && target.closest('a, button, input, select, textarea')) return null;
  return image;
}

function pointAt(contact: Touch | MouseEvent): Point {
  return { x: contact.clientX, y: contact.clientY };
}

function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function fittedSize(image: View['image'], width: number, height: number): Point {
  if (image instanceof HTMLImageElement && image.naturalWidth && image.naturalHeight) {
    const style = getComputedStyle(image);
    if (style.objectPosition === '50% 50%' && ['contain', 'scale-down'].includes(style.objectFit)) {
      const fit = Math.min(width / image.naturalWidth, height / image.naturalHeight,
        style.objectFit === 'scale-down' ? 1 : Infinity);
      return { x: image.naturalWidth * fit, y: image.naturalHeight * fit };
    }
  }
  return { x: width, y: height };
}

function clampOffset(offset: number, size: number, fitted: number, scale: number): number {
  const center = size * (1 - scale) / 2;
  const limit = Math.max(0, (fitted * scale - size) / 2);
  return clamp(offset, center - limit, center + limit);
}

export function installContentZoom(): () => void {
  const listeners = new AbortController();
  const options = { capture: true, passive: false, signal: listeners.signal } as const;
  let view: View | null = null;
  let gesture: TouchGesture | null = null;
  let lastTap: { image: View['image']; time: number; point: Point } | null = null;
  let delayedClick: number | undefined;
  let suppressClick: View['image'] | null = null;
  let mouseDrag: Point | null = null;

  const sourceObserver = new MutationObserver(reset);
  const sizeObserver = new ResizeObserver(entries => {
    if (view && entries.some(entry => entry.target === view?.image)) {
      // ResizeObserver also delivers an initial observation.
      const { image, scale } = view;
      const box = image.getBoundingClientRect();
      if (Math.abs(box.width / scale - width) > 1 || Math.abs(box.height / scale - height) > 1) reset();
    }
  });
  let width = 0;
  let height = 0;

  function reset() {
    if (!view) return;
    const { image } = view;
    image.removeAttribute('data-content-zoomed');
    for (const property of ['--content-zoom-scale', '--content-zoom-offset', '--content-zoom-clip']) {
      image.style.removeProperty(property);
    }
    sourceObserver.disconnect();
    sizeObserver.disconnect();
    view = null;
    mouseDrag = null;
  }

  function transform(image: View['image'], from: Point, to: Point, factor: number) {
    if (view?.image !== image) reset();
    const scale = view?.scale ?? 1;
    const nextScale = clamp(scale * factor, 1, maxScale);
    if (nextScale === 1) {
      reset();
      return;
    }

    const box = image.getBoundingClientRect();
    const offset = view?.offset ?? origin;
    width = box.width / scale;
    height = box.height / scale;
    if (!width || !height) return;

    const fitted = view?.fittedSize ?? fittedSize(image, width, height);
    const ratio = nextScale / scale;
    const x = clampOffset(offset.x + to.x - from.x + (from.x - box.left) * (1 - ratio), width, fitted.x, nextScale);
    const y = clampOffset(offset.y + to.y - from.y + (from.y - box.top) * (1 - ratio), height, fitted.y, nextScale);
    const clip = [-y, width * (nextScale - 1) + x, height * (nextScale - 1) + y, -x]
      .map(edge => `${Math.max(0, edge / nextScale)}px`).join(' ');

    if (!view) {
      sourceObserver.observe(image, { attributes: true, attributeFilter: ['src', 'srcset', 'data-view'] });
      sizeObserver.observe(image);
    }
    view = { image, scale: nextScale, offset: { x, y }, fittedSize: fitted };
    image.setAttribute('data-content-zoomed', '');
    image.style.setProperty('--content-zoom-scale', String(nextScale));
    image.style.setProperty('--content-zoom-offset', `${x}px ${y}px`);
    image.style.setProperty('--content-zoom-clip', `inset(${clip})`);
  }

  function toggleZoom(image: View['image'], point: Point) {
    const surface = getContentZoomSurface(image);
    if (surface) {
      const box = image.getBoundingClientRect();
      surface.toggle({ x: point.x - box.left, y: point.y - box.top });
    } else if (view?.image === image) reset();
    else transform(image, point, point, 2);
  }

  function updatePinch(event: TouchEvent, active: TouchGesture) {
    const [a, b] = Array.from(event.touches, pointAt);
    if (!a || !b) return;
    event.preventDefault();
    const point = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    const gap = distance(a, b);
    const surface = getContentZoomSurface(active.image);
    if (!surface) event.stopPropagation();
    if (active.distance > 0 && gap > 0) {
      const factor = gap / active.distance;
      if (surface?.pinch) {
        const box = active.image.getBoundingClientRect();
        surface.pinch(
          { x: active.point.x - box.left, y: active.point.y - box.top },
          { x: point.x - box.left, y: point.y - box.top },
          factor,
        );
      } else if (!surface) transform(active.image, active.point, point, factor);
    }
    active.point = point;
    active.distance = gap;
    active.consumed = true;
    lastTap = null;
    window.clearTimeout(delayedClick);
  }

  document.addEventListener('touchstart', event => {
    if (event.touches.length === 1 || !gesture) {
      suppressClick = null;
      const image = imageAt(event.target);
      if (!image) {
        lastTap = null;
        return;
      }
      const point = pointAt(event.touches[0]);
      gesture = { image, start: point, point, distance: 0, consumed: false };
    }
    if (event.touches.length === 2) updatePinch(event, gesture);
  }, options);

  document.addEventListener('touchmove', event => {
    if (event.touches.length > 1) {
      // Safari can allow viewport zoom even when a viewport scale limit is set.
      event.preventDefault();
      if (gesture && event.touches.length === 2) updatePinch(event, gesture);
      return;
    }
    if (!gesture || !event.touches.length) return;
    const point = pointAt(event.touches[0]);
    if (view?.image === gesture.image && (gesture.consumed || distance(gesture.start, point) > 4)) {
      event.preventDefault();
      event.stopPropagation();
      transform(gesture.image, gesture.point, point, 1);
      gesture.consumed = true;
    }
    gesture.point = point;
  }, options);

  document.addEventListener('touchend', event => {
    if (!gesture) return;
    const { image, start, point, consumed } = gesture;
    if (event.touches.length) {
      gesture.distance = 0;
      gesture.point = pointAt(event.touches[0]);
      return;
    }
    gesture = null;
    if (consumed) {
      event.preventDefault();
      suppressClick = image;
      return;
    }
    if (distance(start, point) > tapSlop) {
      lastTap = null;
      return;
    }
    const time = performance.now();
    if (lastTap?.image === image && time - lastTap.time <= tapInterval && distance(lastTap.point, point) <= tapSlop) {
      window.clearTimeout(delayedClick);
      event.preventDefault();
      suppressClick = image;
      toggleZoom(image, point);
      lastTap = null;
    } else {
      lastTap = { image, time, point };
    }
  }, options);

  document.addEventListener('touchcancel', () => {
    gesture = null;
    lastTap = null;
  }, options);

  for (const type of ['gesturestart', 'gesturechange']) {
    document.addEventListener(type, event => event.preventDefault(), options);
  }

  document.addEventListener('click', event => {
    const image = imageAt(event.target);
    if (!image || !event.isTrusted || event.detail === 0) return;
    if (suppressClick === image) {
      suppressClick = null;
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    // Preserve a single tap's image-link or preview action after checking
    // whether the user intended to double-tap the image.
    const target = event.target;
    if (lastTap?.image === image && performance.now() - lastTap.time <= tapInterval &&
        target instanceof HTMLElement && target.closest('a, button, [data-testid="embed-preview"]')) {
      event.preventDefault();
      event.stopImmediatePropagation();
      window.clearTimeout(delayedClick);
      delayedClick = window.setTimeout(() => {
        lastTap = null;
        if (target.isConnected) target.click();
      }, tapInterval);
    }
  }, options);

  document.addEventListener('wheel', event => {
    if (!event.ctrlKey) return;
    const image = imageAt(event.target);
    if (!image) return;
    event.preventDefault();
    if (getContentZoomSurface(image)) return;
    const point = pointAt(event);
    transform(image, point, point, Math.exp(-event.deltaY / 100));
  }, options);

  document.addEventListener('dblclick', event => {
    const image = imageAt(event.target);
    if (!image || (event.target instanceof Element && event.target.closest('button, a, [data-testid="embed-preview"]'))) return;
    event.preventDefault();
    toggleZoom(image, pointAt(event));
  }, options);
  document.addEventListener('mousedown', event => {
    suppressClick = null;
    if (event.button !== 0 || !view || imageAt(event.target) !== view.image) return;
    event.preventDefault();
    mouseDrag = pointAt(event);
  }, options);
  document.addEventListener('mousemove', event => {
    if (!mouseDrag || !view || !(event.buttons & 1)) return;
    const point = pointAt(event);
    transform(view.image, mouseDrag, point, 1);
    mouseDrag = point;
    suppressClick = view.image;
  }, options);
  document.addEventListener('mouseup', () => { mouseDrag = null; }, options);

  return () => {
    listeners.abort();
    window.clearTimeout(delayedClick);
    reset();
  };
}
