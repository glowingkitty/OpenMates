/**
 * Keep touch gestures in the embroidery stage. At fit, one finger scrolls the
 * fullscreen body. A pinch zooms about its midpoint and zoomed media can pan.
 */
export function embroideryPreviewZoom(stage: HTMLElement, image: HTMLImageElement) {
  const maxScale = 5;
  let scale = 1;
  let x = 0;
  let y = 0;
  let gesture: { distance: number; scale: number; imageX: number; imageY: number } | undefined;

  function update(event: TouchEvent, start: boolean) {
    const [first, second] = Array.from(event.touches).filter((touch) => stage.contains(touch.target as Node));
    if (!first || (!second && scale === 1)) {
      gesture = undefined;
      return;
    }

    if (event.cancelable) event.preventDefault();
    const rect = stage.getBoundingClientRect();
    const midX = (first.clientX + (second?.clientX ?? first.clientX)) / 2 - rect.left - rect.width / 2;
    const midY = (first.clientY + (second?.clientY ?? first.clientY)) / 2 - rect.top - rect.height / 2;
    const distance = second ? Math.hypot(second.clientX - first.clientX, second.clientY - first.clientY) : 0;
    if (start || !gesture || Boolean(gesture.distance) !== Boolean(distance)) {
      gesture = { distance, scale, imageX: (midX - x) / scale, imageY: (midY - y) / scale };
      return;
    }

    if (!image.naturalWidth || !image.naturalHeight) return;
    if (distance && gesture.distance) scale = Math.min(maxScale, Math.max(1, gesture.scale * distance / gesture.distance));
    // Clamp to the fitted image rather than the surrounding letterbox.
    const fit = Math.min(rect.width / image.naturalWidth, rect.height / image.naturalHeight);
    const limitX = Math.max(0, (image.naturalWidth * fit * scale - rect.width) / 2);
    const limitY = Math.max(0, (image.naturalHeight * fit * scale - rect.height) / 2);
    x = Math.min(limitX, Math.max(-limitX, midX - gesture.imageX * scale));
    y = Math.min(limitY, Math.max(-limitY, midY - gesture.imageY * scale));
    image.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
    stage.classList.toggle('zoomed', scale > 1);
  }

  const start = (event: TouchEvent) => update(event, true);
  const move = (event: TouchEvent) => update(event, false);
  const end = () => { gesture = undefined; };
  const preventNativeZoom = (event: Event) => event.preventDefault();
  stage.addEventListener('touchstart', start, { passive: false });
  stage.addEventListener('touchmove', move, { passive: false });
  stage.addEventListener('touchend', end);
  stage.addEventListener('touchcancel', end);
  // Safari also exposes its native pinch as a separate gesture event.
  stage.addEventListener('gesturestart', preventNativeZoom);
  stage.addEventListener('gesturechange', preventNativeZoom);

  return {
    destroy() {
      stage.removeEventListener('touchstart', start);
      stage.removeEventListener('touchmove', move);
      stage.removeEventListener('touchend', end);
      stage.removeEventListener('touchcancel', end);
      stage.removeEventListener('gesturestart', preventNativeZoom);
      stage.removeEventListener('gesturechange', preventNativeZoom);
    },
  };
}
