import type { TransitionConfig } from 'svelte/transition';

export const WORKSPACE_PANE_DURATION = 320;
// Match the established workspace curve; evaluate its x coordinate for Svelte.
const paneEasing = (progress: number) => {
  if (progress === 0 || progress === 1) return progress;
  let lower = 0;
  let upper = 1;
  for (let step = 0; step < 24; step += 1) {
    const t = (lower + upper) / 2;
    const x = 3 * (1 - t) ** 2 * t * 0.32 + 3 * (1 - t) * t ** 2 * 0.2 + t ** 3;
    if (x < progress) lower = t; else upper = t;
  }
  const t = (lower + upper) / 2;
  return 3 * (1 - t) * t ** 2 + t ** 3;
};
const paneAnimations = new WeakMap<HTMLElement, Animation>();
const paneAnimationTargets = new WeakMap<HTMLElement, boolean>();
const reducedMotion = () => typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** One progress curve for both directions; Svelte can reverse an in-flight transition. */
export function workspacePaneMotion(): TransitionConfig {
  return {
    duration: reducedMotion() ? 0 : WORKSPACE_PANE_DURATION,
    // Curve the visual progress, so decreasing t follows the exact same path in reverse.
    easing: (progress) => progress,
    css: (progress) => {
      const eased = paneEasing(progress);
      return `transform: translateY(${(1 - eased) * 100}%); opacity: ${eased};`;
    },
  };
}

/** Keep the live chat mounted until the same slide/fade completes, then release its data. */
export async function animateWorkspacePane(node: HTMLElement | null, opening: boolean): Promise<() => void> {
  if (!node || reducedMotion()) return () => {};
  let animation = paneAnimations.get(node);
  if (animation && animation.playState !== 'finished') {
    const goingForward = animation.playbackRate > 0;
    if (goingForward !== opening) animation.reverse();
  } else {
    const previous = animation;
    animation = node.animate([
      { transform: 'translateY(100%)', opacity: 0 },
      { transform: 'translateY(0)', opacity: 1 },
    ], {
      duration: WORKSPACE_PANE_DURATION,
      easing: 'cubic-bezier(0.32, 0, 0.2, 1)',
      fill: 'both',
    });
    previous?.cancel();
    if (!opening) {
      animation.currentTime = WORKSPACE_PANE_DURATION;
      animation.reverse();
    }
    paneAnimations.set(node, animation);
  }
  paneAnimationTargets.set(node, opening);
  try { await animation.finished; } catch { /* A replaced or destroyed pane cancels its animation. */ }
  const release = () => {
    if (paneAnimations.get(node) === animation && paneAnimationTargets.get(node) === opening) {
      paneAnimations.delete(node);
      paneAnimationTargets.delete(node);
      animation.cancel();
    }
  };
  // Closing owns its final frame until the caller has finished async navigation/reset.
  if (opening) release();
  return release;
}
