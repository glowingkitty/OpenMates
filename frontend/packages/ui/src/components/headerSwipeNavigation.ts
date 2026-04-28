// frontend/packages/ui/src/components/headerSwipeNavigation.ts
// Shared touch-swipe decision helper for visual header banners.
// Used by chat and embed headers to map horizontal touch gestures to the
// same previous/next actions exposed by their arrow buttons.
// Keeps gesture thresholds consistent across header components.
// Architecture: docs/architecture/frontend/accessibility.md

const HEADER_SWIPE_DISTANCE_PX = 56;
const HEADER_SWIPE_VERTICAL_CANCEL_PX = 48;

export type HeaderSwipeNavigation = "previous" | "next" | null;

export function resolveHeaderSwipeNavigation({
  deltaX,
  deltaY,
  hasPrevious,
  hasNext,
}: {
  deltaX: number;
  deltaY: number;
  hasPrevious: boolean;
  hasNext: boolean;
}): HeaderSwipeNavigation {
  const absDeltaY = Math.abs(deltaY);
  const isMostlyHorizontal = Math.abs(deltaX) > absDeltaY * 1.2;

  if (absDeltaY > HEADER_SWIPE_VERTICAL_CANCEL_PX && !isMostlyHorizontal) {
    return null;
  }

  if (deltaX <= -HEADER_SWIPE_DISTANCE_PX && hasNext) {
    return "next";
  }

  if (deltaX >= HEADER_SWIPE_DISTANCE_PX && hasPrevious) {
    return "previous";
  }

  return null;
}
