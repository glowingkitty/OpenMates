import { center, rotate, type Box, type Point } from './designDocument';

export interface Viewport extends Point { scale: number }
export const MIN_ZOOM = 0.1;
export const MAX_ZOOM = 4;
export const corners: Point[] = [{ x: -1, y: -1 }, { x: 1, y: -1 }, { x: 1, y: 1 }, { x: -1, y: 1 }];

export function worldPoint(view: Viewport, point: Point): Point {
  return { x: (point.x - view.x) / view.scale, y: (point.y - view.y) / view.scale };
}

export function zoomFrom(view: Viewport, from: Point, to: Point, scale: number): Viewport {
  const world = worldPoint(view, from);
  const next = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, scale));
  return { scale: next, x: to.x - world.x * next, y: to.y - world.y * next };
}

export function handlePoint(box: Box, corner: Point, view: Viewport, lift = 0): Point {
  const origin = center(box);
  const offset = rotate({ x: corner.x * box.width / 2, y: corner.y * box.height / 2 - lift / view.scale }, box.rotation);
  return { x: (origin.x + offset.x) * view.scale + view.x, y: (origin.y + offset.y) * view.scale + view.y };
}

export function drawSelection(ctx: CanvasRenderingContext2D, box: Box, view: Viewport, color: string) {
  const points = corners.map((corner) => handlePoint(box, corner, view));
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (const point of points.slice(1)) ctx.lineTo(point.x, point.y);
  ctx.closePath();
  ctx.stroke();
  const top = handlePoint(box, { x: 0, y: -1 }, view);
  const rotation = handlePoint(box, { x: 0, y: -1 }, view, 29);
  ctx.beginPath();
  ctx.moveTo(top.x, top.y);
  ctx.lineTo(rotation.x, rotation.y);
  ctx.stroke();
  ctx.fillStyle = '#fff';
  ctx.beginPath();
  ctx.arc(rotation.x, rotation.y, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  for (const point of points) {
    ctx.fillRect(point.x - 4, point.y - 4, 8, 8);
    ctx.strokeRect(point.x - 4, point.y - 4, 8, 8);
  }
}
