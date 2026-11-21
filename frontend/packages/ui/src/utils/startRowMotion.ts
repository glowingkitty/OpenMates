/**
 * Motion of the Chats start row (Marco, 21 Nov): a card that becomes active, or a new
 * chat, fades in from below into its slot while the other cards slide aside. Same
 * easing and duration as the chat sidebar (`--sidebar-ease: cubic-bezier(0.65, 0, 0.35, 1)`,
 * 300 ms, i.e. ease-in-out cubic). Reduced motion makes both instant.
 * Spec: daily-inspiration.start-row-active-first
 */
import { flip } from 'svelte/animate';
import { cubicInOut } from 'svelte/easing';

/** Duration shared with the sidebar (`--sidebar-duration`). */
export const START_ROW_MOTION_MS = 300;
/** Distance a new card rises while it fades in. */
const RISE_PX = 28;

function prefersReducedMotion(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function duration(enabled: boolean): number {
  return enabled && !prefersReducedMotion() ? START_ROW_MOTION_MS : 0;
}

/**
 * `in:` transition of a row card. `enabled` is false while the row is still filling
 * after the page opened, so loading does not look like new activity.
 */
export function startRowCardIn(_node: Element, { enabled }: { enabled: boolean }) {
  return {
    duration: duration(enabled),
    easing: cubicInOut,
    css: (t: number, u: number) => `opacity: ${t}; transform: translateY(${u * RISE_PX}px);`,
  };
}

/** `animate:` of a row card: the others slide to their new slot. */
export function startRowCardFlip(
  node: Element,
  rects: { from: DOMRect; to: DOMRect },
  { enabled }: { enabled: boolean },
) {
  return flip(node, rects, { duration: duration(enabled), easing: cubicInOut });
}
