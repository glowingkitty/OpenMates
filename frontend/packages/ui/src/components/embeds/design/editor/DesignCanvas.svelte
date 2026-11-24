<!-- figma-visual-proof: not-required. Original OpenMates preview with browser proof. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { center, insideLayer, resizeFromCorner, type DesignLayer, type DesignPage, type Point } from './designDocument';
  import { decodeImages, designPath, drawDesignPage, type DecodedImages } from './designRenderer';
  import { corners, drawSelection, handlePoint, worldPoint, zoomFrom, type Viewport } from './designViewport';

  interface Props {
    page: DesignPage;
    editing: boolean;
    selection: DesignLayer | null;
    onSelect: (id: string | null) => void;
    onCommit: (layer: DesignLayer) => void;
    onDoubleClick: (id: string) => void;
    zoom: number;
  }

  let { page, editing, selection, onSelect, onCommit, onDoubleClick, zoom = $bindable(1) }: Props = $props();
  let element: HTMLCanvasElement;
  let width = $state(0);
  let height = $state(0);
  let view = $state.raw<Viewport>({ x: 0, y: 0, scale: 1 });
  let draft = $state.raw<DesignLayer | null>(null);
  let images = $state.raw<DecodedImages>(new Map());
  let decodedPage = $state<string | null>(null);
  let accent = '#4867cd';
  const backgroundShadow = 'rgba(23, 35, 66, 0.23)';

  type Drag = { id: number; start: Point; moved: boolean } & (
    | { mode: 'pan'; origin: Viewport; clearSelection: boolean }
    | { mode: 'move' | 'rotate'; layer: DesignLayer }
    | { mode: 'resize'; layer: DesignLayer; corner: Point }
  );
  let drag: Drag | null = null;
  let pinch: { view: Viewport; midpoint: Point; distance: number } | null = null;
  const touches = new Map<number, Point>();

  function fitted(w: number, h: number, pageWidth: number, pageHeight: number): Viewport {
    const scale = Math.max(0.1, Math.min((w - 62) / pageWidth, (h - 116) / pageHeight, 1));
    return { scale, x: (w - pageWidth * scale) / 2, y: (h - 46 - pageHeight * scale) / 2 };
  }

  function setView(next: Viewport) {
    view = next;
    zoom = next.scale;
  }

  export function fit() {
    setView(fitted(width, height, page.width, page.height));
  }

  export function adjustZoom(factor: number) {
    const midpoint = { x: width / 2, y: (height - 46) / 2 };
    setView(zoomFrom(view, midpoint, midpoint, view.scale * factor));
  }

  $effect(() => {
    const next = fitted(width, height, page.width, page.height);
    if (width && height) setView(next);
  });

  $effect(() => {
    const id = page.id;
    const layers = page.layers;
    const imageLayers = layers.filter((layer) => layer.kind === 'image');
    if (!imageLayers.length) {
      images = new Map();
      decodedPage = id;
      return;
    }
    let live = true;
    // Retain decoded images when editing geometry. Decode only newly referenced assets.
    void decodeImages(imageLayers, imagesForPage).then((decoded) => {
      if (!live) return;
      imagesForPage = decoded;
      images = decoded;
      decodedPage = id;
    });
    return () => { live = false; };
  });
  let imagesForPage: DecodedImages = new Map();

  onMount(() => {
    const styles = getComputedStyle(element);
    accent = styles.getPropertyValue('--color-primary-end').trim() || accent;
  });

  $effect(() => {
    const design = page;
    const pictures = images;
    const currentDraft = draft;
    const selected = editing && selection && !selection.hidden && !selection.locked ? currentDraft ?? selection : null;
    const currentView = view;
    const w = width;
    const h = height;
    const ready = decodedPage === design.id;
    if (!w || !h) return;
    const frame = requestAnimationFrame(() => {
      const ctx = element.getContext('2d');
      if (!ctx) return;
      const density = Math.min(window.devicePixelRatio || 1, 2);
      const pixelWidth = Math.round(w * density);
      const pixelHeight = Math.round(h * density);
      if (element.width !== pixelWidth) element.width = pixelWidth;
      if (element.height !== pixelHeight) element.height = pixelHeight;
      ctx.setTransform(density, 0, 0, density, 0, 0);
      ctx.clearRect(0, 0, w, h);
      ctx.save();
      ctx.shadowColor = backgroundShadow;
      ctx.shadowBlur = 22 * density;
      ctx.shadowOffsetY = 6 * density;
      ctx.fillStyle = design.background;
      ctx.fillRect(currentView.x, currentView.y, design.width * currentView.scale, design.height * currentView.scale);
      ctx.restore();
      ctx.save();
      ctx.translate(currentView.x, currentView.y);
      ctx.scale(currentView.scale, currentView.scale);
      drawDesignPage(ctx, design, pictures, currentDraft);
      ctx.restore();
      if (selected) drawSelection(ctx, selected, currentView, accent);
      if (ready && element.dataset.paintedPage !== design.id) {
        element.dataset.paintedPage = design.id;
        performance.mark('design-page-painted');
      }
    });
    return () => cancelAnimationFrame(frame);
  });

  function local(event: PointerEvent | WheelEvent | MouseEvent): Point {
    const rect = element.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  function hit(point: Point) {
    const world = worldPoint(view, point);
    if (world.x < 0 || world.y < 0 || world.x > page.width || world.y > page.height) return;
    const ctx = element.getContext('2d');
    if (!ctx) return;
    ctx.save();
    ctx.resetTransform();
    let result: DesignLayer | undefined;
    for (let index = page.layers.length - 1; index >= 0; index--) {
      const layer = page.layers[index];
      if (layer.hidden || layer.locked) continue;
      if (insideLayer(layer, world, (candidate, p) => candidate.kind === 'path' &&
        ctx.isPointInPath(designPath(candidate.path), p.x, p.y))) {
        result = layer;
        break;
      }
    }
    ctx.restore();
    return result;
  }

  function pinchPoints() {
    const [a, b] = touches.values();
    return {
      midpoint: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
      distance: Math.hypot(a.x - b.x, a.y - b.y)
    };
  }

  function pointerDown(event: PointerEvent) {
    if (event.button !== 0 && event.button !== 1) return;
    event.preventDefault();
    element.focus({ preventScroll: true });
    const start = local(event);
    element.setPointerCapture(event.pointerId);
    if (event.pointerType === 'touch') {
      touches.set(event.pointerId, start);
      if (touches.size === 2) {
        drag = null;
        draft = null;
        const { midpoint, distance } = pinchPoints();
        pinch = { view, midpoint, distance: Math.max(1, distance) };
      }
      if (touches.size > 1) return;
    }
    const base = { id: event.pointerId, start, moved: false };
    const canSelect = editing && event.button === 0 && !event.altKey;
    if (canSelect && selection && !selection.locked && !selection.hidden) {
      // Prefer opposite ends of the selection over layer hit-testing.
      const range = event.pointerType === 'touch' ? 15 : 8;
      const near = (point: Point) => Math.hypot(point.x - start.x, point.y - start.y) <= range;
      if (near(handlePoint(selection, { x: 0, y: -1 }, view, 29))) {
        drag = { ...base, mode: 'rotate', layer: selection };
        return;
      }
      const corner = corners.find((candidate) => near(handlePoint(selection, candidate, view)));
      if (corner) {
        drag = { ...base, mode: 'resize', layer: selection, corner };
        return;
      }
    }
    const layer = canSelect ? hit(start) : undefined;
    if (layer) {
      onSelect(layer.id);
      drag = { ...base, mode: 'move', layer };
    } else {
      drag = { ...base, mode: 'pan', origin: view, clearSelection: canSelect };
    }
  }

  function pointerMove(event: PointerEvent) {
    const point = local(event);
    if (touches.has(event.pointerId)) touches.set(event.pointerId, point);
    if (pinch && touches.size >= 2) {
      const { midpoint, distance } = pinchPoints();
      setView(zoomFrom(pinch.view, pinch.midpoint, midpoint, pinch.view.scale * distance / pinch.distance));
      return;
    }
    if (!drag || event.pointerId !== drag.id) return;
    const dx = point.x - drag.start.x;
    const dy = point.y - drag.start.y;
    if (!drag.moved && Math.hypot(dx, dy) < 3) return;
    drag.moved = true;
    if (drag.mode === 'pan') {
      setView({ ...drag.origin, x: drag.origin.x + dx, y: drag.origin.y + dy });
      return;
    }
    const layer = drag.layer;
    const delta = { x: dx / view.scale, y: dy / view.scale };
    if (drag.mode === 'move') {
      draft = { ...layer, x: layer.x + delta.x, y: layer.y + delta.y };
    } else if (drag.mode === 'resize') {
      draft = { ...layer, ...resizeFromCorner(layer, delta, drag.corner) };
    } else {
      const origin = center(layer);
      const angle = (p: Point) => {
        const world = worldPoint(view, p);
        return Math.atan2(world.y - origin.y, world.x - origin.x);
      };
      const offset = (angle(point) - angle(drag.start)) * 180 / Math.PI;
      const snap = event.shiftKey ? 15 : 1;
      const rotation = ((Math.round((layer.rotation + offset) / snap) * snap % 360) + 540) % 360 - 180;
      draft = { ...layer, rotation };
    }
  }

  function endPointer(event: PointerEvent, cancelled = false) {
    touches.delete(event.pointerId);
    if (pinch && touches.size < 2) pinch = null;
    if (!drag || drag.id !== event.pointerId) return;
    if (!cancelled && draft) onCommit(draft);
    if (!cancelled && drag.mode === 'pan' && !drag.moved && drag.clearSelection) onSelect(null);
    drag = null;
    draft = null;
  }

  function wheel(node: HTMLCanvasElement) {
    function handle(event: WheelEvent) {
      event.preventDefault();
      if (event.ctrlKey || event.metaKey) {
        const point = local(event);
        setView(zoomFrom(view, point, point, view.scale * Math.exp(-event.deltaY * 0.012)));
      } else {
        const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? height : 1;
        setView({ ...view, x: view.x - event.deltaX * unit, y: view.y - event.deltaY * unit });
      }
    }
    node.addEventListener('wheel', handle, { passive: false });
    return { destroy: () => node.removeEventListener('wheel', handle) };
  }
</script>

<div class="stage" bind:clientWidth={width} bind:clientHeight={height}>
  <canvas bind:this={element} use:wheel data-testid="design-canvas" data-scale={zoom}
    aria-label={`${page.name}, ${page.width} by ${page.height}, ${page.layers.length} layers`} tabindex="0"
    class:editing
    onpointerdown={pointerDown} onpointermove={pointerMove}
    onpointerup={endPointer} onpointercancel={(event) => endPointer(event, true)}
    onlostpointercapture={(event) => endPointer(event, true)}
    ondblclick={(event) => {
      if (!editing) return;
      const layer = hit(local(event));
      if (layer?.kind === 'text') onDoubleClick(layer.id);
    }}>
    {page.name}
  </canvas>
</div>

<style>
  .stage { position: absolute; inset: 0; }
  canvas {
    display: block;
    width: 100%;
    height: 100%;
    touch-action: none;
    cursor: grab;
  }
  canvas:active { cursor: grabbing; }
  canvas.editing { cursor: default; }
  canvas.editing:active { cursor: move; }
  canvas:focus-visible { outline: 2px solid var(--color-primary-start); outline-offset: -2px; }
</style>
