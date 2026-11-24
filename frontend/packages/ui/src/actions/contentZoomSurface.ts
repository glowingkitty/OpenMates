// Viewers with their own zoom controls share the app's gesture detection and
// keep a single scale and pan position for touch and on-screen controls.
export interface ZoomPoint {
  x: number;
  y: number;
}

interface ContentZoomSurface {
  toggle(point: ZoomPoint): void;
  pinch?(from: ZoomPoint, to: ZoomPoint, factor: number): void;
  includesImages?: boolean;
}

const surfaces = new WeakMap<Element, ContentZoomSurface>();

export function getContentZoomSurface(node: Element): ContentZoomSurface | undefined {
  return surfaces.get(node);
}

export function contentZoomSurface(node: HTMLElement, surface: ContentZoomSurface | null) {
  function update(next: ContentZoomSurface | null) {
    if (next) surfaces.set(node, next);
    else surfaces.delete(node);
    node.toggleAttribute('data-content-zoom-surface', !!next);
    node.toggleAttribute('data-content-zoom-includes-images', next?.includesImages === true);
  }

  update(surface);
  return { update, destroy: () => update(null) };
}
