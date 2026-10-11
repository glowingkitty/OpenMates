/** Map SVG geometry into the local coordinate system of an editable edge path. */
export interface DiagramAffine { a: number; b: number; c: number; d: number; e: number; f: number }
export interface DiagramBox { x: number; y: number; width: number; height: number }
export interface DiagramBounds { left: number; right: number; top: number; bottom: number; width: number; height: number }

export function diagramBoundsInTarget(
  box: DiagramBox,
  sourceToScreen: DiagramAffine | null,
  targetToScreen: DiagramAffine | null,
): DiagramBounds | null {
  if (!sourceToScreen || !targetToScreen) return null;
  const { a, b, c, d, e, f } = targetToScreen;
  const det = a * d - b * c;
  if (!Number.isFinite(det) || Math.abs(det) < 1e-12) return null;
  const inverse = { a: d / det, b: -b / det, c: -c / det, d: a / det,
    e: (c * f - d * e) / det, f: (b * e - a * f) / det };
  const points = [
    [box.x, box.y], [box.x + box.width, box.y],
    [box.x, box.y + box.height], [box.x + box.width, box.y + box.height]
  ].map(([x, y]) => {
    const screenX = sourceToScreen.a * x + sourceToScreen.c * y + sourceToScreen.e;
    const screenY = sourceToScreen.b * x + sourceToScreen.d * y + sourceToScreen.f;
    return { x: inverse.a * screenX + inverse.c * screenY + inverse.e,
      y: inverse.b * screenX + inverse.d * screenY + inverse.f };
  });
  const xs = points.map((point) => point.x), ys = points.map((point) => point.y);
  const left = Math.min(...xs), right = Math.max(...xs), top = Math.min(...ys), bottom = Math.max(...ys);
  return { left, right, top, bottom, width: right - left, height: bottom - top };
}
